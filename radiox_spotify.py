# Radio X to Spotify Playlist Adder
# v6.0 - Final with Stable Web UI and All Features
# Includes: Startup diagnostic tests, class-based structure, time-windowed operation, 
#           playlist size limit, daily HTML email summaries with detailed stats,
#           persistent caches, web UI with manual triggers, robust networking, and enhanced title cleaning.

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import time
import os
import json 
import logging
import re 
import websocket 
import threading 
from flask import Flask, jsonify, render_template, Response
import datetime
import pytz 
import smtplib 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque, Counter
import atexit
import base64
from dotenv import load_dotenv
from flask_sse import sse
import redis

try:
    import psutil
except ImportError:
    psutil = None

# --- Custom Log Handler for Debug Logs ---
class DebugLogHandler(logging.Handler):
    def __init__(self, max_entries=1000):
        super().__init__()
        self.log_entries = deque(maxlen=max_entries)
        self.lock = threading.Lock()
    
    def emit(self, record):
        with self.lock:
            # Format the log entry
            formatted_entry = self.format(record)
            self.log_entries.append({
                'timestamp': record.created,
                'level': record.levelname,
                'message': formatted_entry,
                'module': record.module,
                'funcName': record.funcName,
                'lineno': record.lineno
            })
    
    def get_logs(self, level_filter=None, max_entries=None):
        """Get stored log entries, optionally filtered by level."""
        with self.lock:
            logs = list(self.log_entries)
            if level_filter:
                # Convert level names to numeric values for comparison
                level_nums = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}
                filter_level = level_nums.get(level_filter.upper(), 0)
                logs = [log for log in logs if level_nums.get(log['level'], 0) >= filter_level]
            
            if max_entries:
                logs = logs[-max_entries:]
            
            return logs
    
    def clear_logs(self):
        """Clear stored log entries."""
        with self.lock:
            self.log_entries.clear()

# --- Flask App Setup ---
app = Flask(__name__)
app.config["REDIS_URL"] = "redis://redis:6379"
app.config["SSE_REDIS_URL"] = "redis://redis:6379"
app.register_blueprint(sse, url_prefix='/stream')

# Initialize Redis client for SSE
try:
    redis_client = redis.from_url("redis://redis:6379")
    redis_client.ping()  # Test connection
    logging.info("Redis connection established successfully")
except Exception as e:
    logging.error(f"Failed to connect to Redis: {e}")
    redis_client = None

# --- Configuration ---
load_dotenv()

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SPOTIFY_PLAYLIST_ID = os.getenv("SPOTIFY_PLAYLIST_ID")
RADIOX_STATION_SLUG = "radiox" 

# Script Operation Settings
CHECK_INTERVAL = 120  
DUPLICATE_CHECK_INTERVAL = 2 * 60 * 60  # 7200 seconds
MAX_PLAYLIST_SIZE = 500
MAX_FAILED_SEARCH_QUEUE_SIZE = 30 
MAX_FAILED_SEARCH_ATTEMPTS = 3    

# Active Time Window (BST/GMT Aware)
TIMEZONE = 'Europe/London'
START_TIME = datetime.time(7, 0)
END_TIME = datetime.time(22, 0)  # Changed to 22:00 (10:00 PM)

# Email Summary Settings (from environment)
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = os.getenv("EMAIL_PORT")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

BOLD = '\033[1m'
RESET = '\033[0m'
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Set up logging with custom handler for debug logs
debug_log_handler = DebugLogHandler(max_entries=2000)
debug_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configure root logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
root_logger = logging.getLogger()
root_logger.addHandler(debug_log_handler)

BACKEND_VERSION = "1.2.9"

# --- Main Application Class ---

class RadioXBot:
    def __init__(self):
        # State Variables
        self.sp = None
        self.last_added_radiox_track_id = None
        self.herald_id_cache = {}
        self.last_duplicate_check_time = 0
        self.last_summary_log_date = datetime.date.today() - datetime.timedelta(days=1)
        self.startup_email_sent = False
        self.shutdown_summary_sent = False
        self.current_station_herald_id = None
        self.is_running = False
        self.service_state = ''
        self.paused_reason = ''
        self.seconds_until_next_check = 0
        self.is_checking = False
        self.check_complete = False
        self.last_check_time = 0
        self.last_check_complete_time = 0
        self.next_check_time = ''
        self.stats = {}
        self.state_history = []

        # Persistent Data Structures
        self.CACHE_DIR = ".cache"
        if os.path.isfile(self.CACHE_DIR):
            logging.warning(f"A file named '{self.CACHE_DIR}' exists. Removing it to create cache directory.")
            os.remove(self.CACHE_DIR)
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        
        self.RECENTLY_ADDED_CACHE_FILE = os.path.join(self.CACHE_DIR, "recent_tracks.json")
        self.FAILED_QUEUE_CACHE_FILE = os.path.join(self.CACHE_DIR, "failed_queue.json")
        self.DAILY_ADDED_CACHE_FILE = os.path.join(self.CACHE_DIR, "daily_added.json")
        self.DAILY_FAILED_CACHE_FILE = os.path.join(self.CACHE_DIR, "daily_failed.json")
        self.LAST_CHECK_COMPLETE_FILE = os.path.join(self.CACHE_DIR, "last_check_complete_time.txt")

        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(maxlen=20)
        self.failed_search_queue = deque(maxlen=5)
        self.daily_added_songs = [] 
        self.daily_search_failures = [] 
        self.event_log = deque(maxlen=10)
        self.log_event("Application instance created. Waiting for initialization.")
        self.file_lock = threading.Lock()
        self.update_service_state('initializing')

    def log_event(self, message):
        """Adds an event to the global log for the web UI and standard logging."""
        logging.info(message)
        clean_message = ANSI_ESCAPE.sub('', message) # Remove ANSI codes for web log
        timestamp = f"[{datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S')}]"
        log_entry = f"{timestamp} {clean_message}"
        self.event_log.appendleft(log_entry)
        try:
            with app.app_context():
                sse.publish({"log_entry": log_entry}, type='new_log')
                logging.debug(f"SSE: Published new_log event")
        except Exception as e:
            logging.error(f"SSE: Failed to publish new_log event: {e}")

    def update_service_state(self, new_state, reason=''):
        """Updates the service state and adds an entry to the state history."""
        if new_state != self.service_state:
            self.service_state = new_state
            self.paused_reason = reason
            timestamp = datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat()
            self.state_history.append({
                'timestamp': timestamp,
                'state': new_state,
                'reason': reason
            })
            # Keep only the last 50 state changes
            self.state_history = self.state_history[-50:]
            self.log_event(f"Service state changed to {new_state}" + (f" (reason: {reason})" if reason else ""))
            try:
                with app.app_context():
                    sse.publish({"state": new_state, "reason": reason}, type='state_change')
                    logging.debug(f"SSE: Published state_change event")
            except Exception as e:
                logging.error(f"SSE: Failed to publish state_change event: {e}")

    # --- Persistent State Management ---
    def save_state(self):
        """Saves the queues and daily summaries to disk."""
        with self.file_lock:
            try:
                with open(self.RECENTLY_ADDED_CACHE_FILE, 'w') as f: json.dump(list(self.RECENTLY_ADDED_SPOTIFY_IDS), f)
                with open(self.FAILED_QUEUE_CACHE_FILE, 'w') as f: json.dump(list(self.failed_search_queue), f)
                with open(self.DAILY_ADDED_CACHE_FILE, 'w') as f: json.dump(self.daily_added_songs[-50:], f)
                with open(self.DAILY_FAILED_CACHE_FILE, 'w') as f: json.dump(self.daily_search_failures[-50:], f)
                logging.debug("Successfully saved application state to disk.")
            except Exception as e:
                logging.error(f"Failed to save state to disk: {e}")

    def load_state(self):
        """Loads the queues and daily summaries from disk on startup."""
        with self.file_lock:
            try:
                if os.path.exists(self.RECENTLY_ADDED_CACHE_FILE):
                    with open(self.RECENTLY_ADDED_CACHE_FILE, 'r') as f:
                        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=20)
                        logging.info(f"Loaded {len(self.RECENTLY_ADDED_SPOTIFY_IDS)} recent tracks from cache.")
                if os.path.exists(self.FAILED_QUEUE_CACHE_FILE):
                    with open(self.FAILED_QUEUE_CACHE_FILE, 'r') as f:
                        self.failed_search_queue = deque(json.load(f), maxlen=5)
                        logging.info(f"Loaded {len(self.failed_search_queue)} failed searches from cache.")
                if os.path.exists(self.DAILY_ADDED_CACHE_FILE):
                    with open(self.DAILY_ADDED_CACHE_FILE, 'r') as f:
                        self.daily_added_songs = json.load(f)
                        logging.info(f"Loaded {len(self.daily_added_songs)} daily added songs from cache.")
                if os.path.exists(self.DAILY_FAILED_CACHE_FILE):
                    with open(self.DAILY_FAILED_CACHE_FILE, 'r') as f:
                        self.daily_search_failures = json.load(f)
                        logging.info(f"Loaded {len(self.daily_search_failures)} daily failed searches from cache.")
            except Exception as e:
                logging.error(f"Failed to load state from disk: {e}")
        # After loading, immediately calculate stats from the cache
        self.update_stats()

    def save_last_check_complete_time(self):
        with open(self.LAST_CHECK_COMPLETE_FILE, 'w') as f:
            f.write(str(self.last_check_complete_time))

    def load_last_check_complete_time(self):
        if os.path.exists(self.LAST_CHECK_COMPLETE_FILE):
            with open(self.LAST_CHECK_COMPLETE_FILE, 'r') as f:
                try:
                    self.last_check_complete_time = int(f.read().strip())
                except Exception:
                    self.last_check_complete_time = 0

    # --- Authentication ---
    def authenticate_spotify(self):
        """Initializes and authenticates the Spotipy client using refresh token."""
        try:
            auth_manager = spotipy.oauth2.SpotifyOAuth(
                client_id=SPOTIPY_CLIENT_ID,
                client_secret=SPOTIPY_CLIENT_SECRET,
                redirect_uri=SPOTIPY_REDIRECT_URI,
                scope="playlist-modify-public playlist-modify-private",
                open_browser=True,
                cache_handler=spotipy.cache_handler.CacheFileHandler(cache_path=".spotipy_cache")
            )
            
            # Try to get a token from cache first
            token_info = auth_manager.get_cached_token()
            
            if not token_info:
                # If no cached token, prompt user to authenticate
                token_info = auth_manager.get_access_token(as_dict=True)
            
            if not token_info:
                # If no cached token, we need to get a new one
                # For now, we'll use a dummy token that will fail gracefully
                self.sp = None
                logging.warning("No cached token found. Please run the application locally first to generate a token.")
                return False
            
            # If we have a token, use it
            if auth_manager.is_token_expired(token_info):
                token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            # Test the connection
            self.sp.current_user()
            self.log_event("Successfully authenticated with Spotify using refresh token.")
            return True
        except Exception as e:
            self.sp = None
            logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
        return False
    
    # --- API Wrappers and Helpers ---
    def spotify_api_call_with_retry(self, func, *args, **kwargs):
        max_retries=3; base_delay=5; retryable_spotify_exceptions=(500, 502, 503, 504)
        last_exception = None
        for attempt in range(max_retries):
            try: return func(*args, **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
                last_exception = e; logging.warning(f"Network error on {func.__name__} (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries-1: time.sleep(base_delay * (2**attempt))
                else: raise
            except spotipy.SpotifyException as e:
                last_exception = e; logging.warning(f"Spotify API Exception on {func.__name__} (attempt {attempt+1}/{max_retries}): HTTP {e.http_status} - {e.msg}")
                if e.http_status == 429:
                    retry_after_header = e.headers.get('Retry-After'); retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else (base_delay * (2**attempt)); logging.info(f"Rate limited. Retrying after {retry_after} seconds..."); time.sleep(retry_after)
                elif e.http_status in retryable_spotify_exceptions:
                    if attempt < max_retries-1: time.sleep(base_delay * (2**attempt))
                    else: raise
                else: raise
        if last_exception: raise last_exception
        raise Exception(f"{func.__name__} failed after all retries.")

    def get_station_herald_id(self, station_slug_to_find):
        if station_slug_to_find in self.herald_id_cache: return self.herald_id_cache[station_slug_to_find]
        url = "https://bff-web-guacamole.musicradio.com/globalplayer/brands"; headers = {'User-Agent': 'RadioXToSpotifyApp/1.0','Accept': 'application/vnd.global.8+json'}
        self.log_event(f"Fetching heraldId for {station_slug_to_find}...")
        try:
            response = requests.get(url, headers=headers, timeout=10); response.raise_for_status(); brands_data = response.json()
            if not isinstance(brands_data, list): logging.error("Brands API did not return a list."); return None
            for brand in brands_data:
                if brand.get('brandSlug', '').lower() == station_slug_to_find:
                    herald_id = brand.get('heraldId')
                    if herald_id: self.herald_id_cache[station_slug_to_find] = herald_id; return herald_id
            logging.warning(f"Could not find heraldId for slug '{station_slug_to_find}'.")
            return None
        except Exception as e: self.log_event(f"ERROR: Error fetching brands: {e}"); return None

    def get_current_radiox_song(self, station_herald_id):
        if not station_herald_id: return None
        websocket_url = "wss://metadata.musicradio.com/v2/now-playing"
        logging.info(f"Connecting to WebSocket: {websocket_url}")
        ws = None
        try:
            ws = websocket.create_connection(websocket_url, timeout=10)
            ws.send(json.dumps({"actions": [{"type": "subscribe", "service": str(station_herald_id)}]}))
            message_received = None; ws.settimeout(10) 
            for _ in range(3):
                raw_message = ws.recv(); logging.debug(f"Raw WebSocket: {raw_message[:200]}...") 
                if raw_message:
                    message_data = json.loads(raw_message)
                    if message_data.get('now_playing') and message_data['now_playing'].get('type') == 'track':
                        message_received = message_data; break 
                    elif message_data.get('type') == 'heartbeat': logging.debug("WebSocket heartbeat."); continue 
                time.sleep(0.2) 
            if not message_received: logging.info("No track update from WebSocket."); return None
            now_playing = message_received.get('now_playing', {})
            title, artist, track_id_api = now_playing.get('title'), now_playing.get('artist'), now_playing.get('id')
            if title and artist:
                title, artist = title.strip(), artist.strip()
                if title and artist: 
                    unique_id = track_id_api or f"{station_herald_id}_{title}_{artist}".replace(" ", "_")
                    return {"title": title, "artist": artist, "id": unique_id}
            return None
        except websocket.WebSocketTimeoutException: logging.warning("WebSocket timeout.")
        except Exception as e: logging.error(f"WebSocket error: {e}", exc_info=True)
        finally:
            if ws:
                try: ws.close()
                except Exception as e_ws_close: logging.error(f"Error closing WebSocket: {e_ws_close}")
        return None
    
    def search_song_on_spotify(self, original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
        if not self.sp: logging.error("Spotify not initialized for search."); return None
        search_attempts_details = []
        def _attempt_search_spotify(title_to_search, attempt_description):
            nonlocal search_attempts_details
            query = f"track:{title_to_search} artist:{artist}"
            try:
                results = self.spotify_api_call_with_retry(self.sp.search, q=query, type="track", limit=1)
                if results and results["tracks"]["items"]:
                    track = results["tracks"]["items"][0]
                    self.log_event(f"Found on Spotify ({attempt_description}): '{track['name']}'")
                    return track["id"]
                else: search_attempts_details.append(f"Attempt '{attempt_description}': Not found."); return None
            except Exception as e:
                self.log_event(f"ERROR: Persistent network/API error during search for '{title_to_search}'.")
                if radiox_id_for_queue and not is_retry_from_queue: self.add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
                return "NETWORK_ERROR_FLAG"

        spotify_id = _attempt_search_spotify(original_title, "original title")
        if spotify_id is not None: return spotify_id if spotify_id != "NETWORK_ERROR_FLAG" else None
        cleaned_title_paren = re.sub(r'\s*\(.*?\)\s*', ' ', original_title).strip()
        if cleaned_title_paren and cleaned_title_paren.lower() != original_title.lower():
            spotify_id = _attempt_search_spotify(cleaned_title_paren, "parentheses removed")
            if spotify_id is not None: return spotify_id if spotify_id != "NETWORK_ERROR_FLAG" else None
        cleaned_title_feat = re.sub(r'\s*\[.*?\]\s*|feat\..*', ' ', original_title, flags=re.IGNORECASE).strip()
        if cleaned_title_feat and cleaned_title_feat.lower() != original_title.lower() and cleaned_title_feat.lower() != cleaned_title_paren.lower():
            spotify_id = _attempt_search_spotify(cleaned_title_feat, "features/brackets removed")
            if spotify_id is not None: return spotify_id if spotify_id != "NETWORK_ERROR_FLAG" else None
        self.log_event(f"FAIL: Song '{original_title}' by '{artist}' not found after all attempts.")
        if not is_retry_from_queue: self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify after all attempts."})
        return None

    def manage_playlist_size(self, playlist_id):
        try:
            # Fetch only the first (oldest) track
            results = self.sp.playlist_items(playlist_id, limit=1, offset=0, fields='items.track.id,total')
            total = results.get('total', 0)
            if total >= MAX_PLAYLIST_SIZE and results['items']:
                oldest_track = results['items'][0]['track']
                if oldest_track:
                    oldest_track_id = oldest_track['id']
                    self.sp.playlist_remove_all_occurrences_of_items(playlist_id, [oldest_track_id])
                    self.log_event(f"Playlist at/over limit. Removed oldest song (ID: {oldest_track_id}).")
            return True
        except Exception as e:
            self.log_event(f"Error managing playlist size: {e}")
            return False

    def add_song_to_playlist(self, radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
        if not self.sp: return False
        if spotify_track_id in self.RECENTLY_ADDED_SPOTIFY_IDS:
            self.log_event(f"Track '{radio_x_title}' recently processed. Skipping add.")
            return True
        if not self.manage_playlist_size(playlist_id_to_use):
            self.log_event("WARNING: Could not manage playlist size. Adding anyway.")
        try:
            track_details = self.spotify_api_call_with_retry(self.sp.track, spotify_track_id)
            if not track_details: raise Exception(f"Could not fetch details for track ID {spotify_track_id}")
            self.spotify_api_call_with_retry(self.sp.playlist_add_items, playlist_id_to_use, [spotify_track_id])
            
            spotify_name = track_details.get('name', 'Unknown')
            spotify_artists_str = ", ".join([a.get('name', '') for a in track_details.get('artists', [])])
            release_date = track_details.get('album', {}).get('release_date', 'N/A')
            album_art_url = track_details['album']['images'][1]['url'] if track_details.get('album', {}).get('images') and len(track_details['album']['images']) > 1 else None
            album_name = track_details.get('album', {}).get('name', 'N/A')

            self.log_event(f"DEBUG: Album details found. Name: '{album_name}', Art URL present: {album_art_url is not None}")

            self.daily_added_songs.append({
                "timestamp": datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "added_at": int(time.time()),  # Use current Unix timestamp for accuracy
                "radio_title": radio_x_title, 
                "radio_artist": radio_x_artist, 
                "spotify_title": spotify_name, 
                "spotify_artist": spotify_artists_str, 
                "spotify_id": spotify_track_id, 
                "release_date": release_date,
                "album_art_url": album_art_url,
                "album_name": album_name
            })
            self.log_event(f"SUCCESS: Added '{BOLD}{radio_x_title}{RESET}' by '{BOLD}{radio_x_artist}{RESET}' to playlist.")
            self.RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id)
            return True
        except spotipy.SpotifyException as e:
            reason = f"API Error: HTTP {e.http_status} - {e.msg}"
            if e.http_status == 403 and "duplicate" in e.msg.lower(): 
                 self.RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id)
                 reason = "Spotify blocked add as duplicate (already in playlist)"
            else: logging.error(f"Error adding track '{radio_x_title}': {e}")
            self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": reason})
            return False
        except Exception as e:
            logging.error(f"Unexpected error adding track '{radio_x_title}': {e}")
            self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": f"Unexpected error during add: {e}"})
            return False

    def check_and_remove_duplicates(self, playlist_id):
        """Checks for and removes duplicate tracks in the playlist."""
        if not self.sp: return
        self.log_event("Starting periodic duplicate check...")
        try:
            all_tracks, offset, limit = [], 0, 100
            while True:
                results = self.spotify_api_call_with_retry(self.sp.playlist_items, playlist_id, limit=limit, offset=offset, fields="items(track(id,uri,name)),next")
                if not results or not results['items']: break
                for item in results['items']:
                    if item.get('track') and item['track'].get('id'): all_tracks.append(item['track'])
                if results['next']: offset += 100
                else: break
            self.log_event(f"DUPLICATE_CLEANUP: Fetched {len(all_tracks)} tracks.")
            if not all_tracks: return
            track_counts = Counter(t['id'] for t in all_tracks if t['id'])
            for track_id, count in track_counts.items():
                if count > 1:
                    track_uri = next((t['uri'] for t in all_tracks if t['id'] == track_id), None)
                    track_name = next((t['name'] for t in all_tracks if t['id'] == track_id), "Unknown")
                    if track_uri:
                        self.log_event(f"DUPLICATE_CLEANUP: Track '{track_name}' found {count} times. Re-processing.")
                        self.spotify_api_call_with_retry(self.sp.playlist_remove_all_occurrences_of_items, playlist_id, [track_uri])
                        time.sleep(0.5); self.spotify_api_call_with_retry(self.sp.playlist_add_items, playlist_id, [track_uri])
                        self.RECENTLY_ADDED_SPOTIFY_IDS.append(track_id)
                        time.sleep(1)
        except Exception as e: self.log_event(f"ERROR during duplicate cleanup: {e}")

    def process_failed_search_queue(self):
        if not self.failed_search_queue: return
        self.log_event(f"PFSQ: Processing 1 item from queue (size: {len(self.failed_search_queue)}).")
        item = self.failed_search_queue.popleft()
        item['attempts'] += 1
        spotify_id = self.search_song_on_spotify(item['title'], item['artist'], is_retry_from_queue=True)
        if spotify_id:
            self.add_song_to_playlist(item.get('title', 'Unknown'), item.get('artist', 'Unknown'), spotify_id, SPOTIFY_PLAYLIST_ID)
        elif item.get('attempts', 0) < MAX_FAILED_SEARCH_ATTEMPTS:
            self.failed_search_queue.append(item)
            self.log_event(f"PFSQ: Re-queued '{item.get('title', 'Unknown')}' (Attempts: {item.get('attempts', 0)}).")
        else:
            self.log_event(f"PFSQ: Max retries reached for '{item.get('title', 'Unknown')}'. Discarding.")
            self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": item.get('title', 'Unknown'), "radio_artist": item.get('artist', 'Unknown'), "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."})

    # --- Email & Summary Functions ---
    def send_summary_email(self, html_body, subject):
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
            self.log_event("Email settings not configured. Skipping email.")
            return False
        self.log_event(f"Attempting to send email to {EMAIL_RECIPIENT}...")
        try:
            port = int(EMAIL_PORT); msg = MIMEMultipart('alternative'); msg['Subject'] = subject; msg['From'] = EMAIL_HOST_USER; msg['To'] = EMAIL_RECIPIENT; msg.attach(MIMEText(html_body, 'html'))
            with smtplib.SMTP(EMAIL_HOST, port) as server:
                server.starttls(); server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD); server.send_message(msg)
            logging.info("Email sent successfully.")
            return True
        except Exception as e: logging.error(f"Failed to send email: {e}"); return False

    def get_daily_stats_html(self):
        if not self.daily_added_songs and not self.daily_search_failures: return ""
        try:
            artist_counts = Counter(item.get('radio_artist', 'Unknown') for item in self.daily_added_songs)
            most_common = artist_counts.most_common(5)
            top_artists_str = ", ".join([f"{artist} ({count})" for artist, count in most_common]) if most_common else "N/A"
            unique_artist_count = len(artist_counts)
            failure_reasons = Counter(item.get('reason', 'Unknown') for item in self.daily_search_failures)
            failure_breakdown_str = "; ".join([f"{reason}: {count}" for reason, count in failure_reasons.items()]) or "None"
            total_processed = len(self.daily_added_songs) + len(self.daily_search_failures)
            success_rate = (len(self.daily_added_songs) / total_processed * 100) if total_processed > 0 else 100
            busiest_hour_str, newest_song_str, oldest_song_str, decade_breakdown_str = "N/A", "N/A", "N/A", ""
            if self.daily_added_songs:
                hour_counts = Counter(datetime.datetime.fromisoformat(item.get('timestamp', '')).hour for item in self.daily_added_songs if item.get('timestamp'))
                busiest_hour, song_count = hour_counts.most_common(1)[0]
                busiest_hour_str = f"{busiest_hour:02d}:00 - {busiest_hour:02d}:59 ({song_count} songs)"
                songs_with_dates = [s for s in self.daily_added_songs if s.get('release_date') and '-' in s['release_date']]
                if songs_with_dates:
                    songs_with_dates.sort(key=lambda x: x['release_date'])
                    oldest_song, newest_song = songs_with_dates[0], songs_with_dates[-1]
                    oldest_song_str = f"{oldest_song.get('spotify_title', 'Unknown')} by {oldest_song.get('spotify_artist', 'Unknown')} ({oldest_song.get('release_date', 'Unknown')[:4] if oldest_song.get('release_date') else 'Unknown'})"
                    newest_song_str = f"{newest_song.get('spotify_title', 'Unknown')} by {newest_song.get('spotify_artist', 'Unknown')} ({newest_song.get('release_date', 'Unknown')[:4] if newest_song.get('release_date') else 'Unknown'})"
                    decade_counts = Counter((int(s['release_date'][:4]) // 10) * 10 for s in songs_with_dates)
                    total_dated_songs = len(songs_with_dates)
                    sorted_decades = decade_counts.most_common(5)
                    decade_breakdown_str = " | ".join([f"<b>{decade}s:</b> {((count / total_dated_songs) * 100):.0f}%%" for decade, count in sorted_decades])
            stats_html = f"""
            <h3>Daily Stats</h3>
            <p><b>Success Rate:</b> {success_rate:.1f}%% ({len(self.daily_added_songs)} added / {total_processed} processed)<br>
            <b>Unique Artists Added:</b> {unique_artist_count}<br>
            <b>Top Artists:</b> {top_artists_str}<br>
            <b>Busiest Hour:</b> {busiest_hour_str}<br>
            <b>Oldest Song Added:</b> {oldest_song_str}<br>
            <b>Newest Song Added:</b> {newest_song_str}<br>
            <b>Decade Breakdown:</b> {decade_breakdown_str}<br>
            <b>Failure Breakdown:</b> {failure_breakdown_str}<br>
            <b>Items in Retry Queue at EOD:</b> {len(self.failed_search_queue)}</p>
            """
            return stats_html
        except Exception as e: logging.error(f"Could not generate daily stats: {e}"); return ""

    def log_and_send_daily_summary(self):
        if not self.daily_added_songs and not self.daily_search_failures:
            self.log_event("Daily summary skipped: No new songs added or failed.")
            self.daily_added_songs.clear()
            self.daily_search_failures.clear()
            self.save_state()
            return

        summary_date = self.last_summary_log_date.isoformat()
        
        # Get current playlist stats
        try:
            playlist_details = self.spotify_api_call_with_retry(self.sp.playlist, SPOTIFY_PLAYLIST_ID, fields='name,tracks.total')
            playlist_name = playlist_details['name'] if playlist_details else 'Unknown'
            playlist_size = playlist_details['tracks']['total'] if playlist_details and 'tracks' in playlist_details else 0
        except Exception as e:
            playlist_name = 'Error fetching'
            playlist_size = 0
        
        # Calculate rich statistics
        total_processed = len(self.daily_added_songs) + len(self.daily_search_failures)
        success_rate = (len(self.daily_added_songs) / total_processed * 100) if total_processed > 0 else 100
        
        # Artist statistics
        artist_counts = Counter(item.get('radio_artist', 'Unknown') for item in self.daily_added_songs)
        top_artists = artist_counts.most_common(5)
        unique_artist_count = len(artist_counts)
        
        # Decade analysis
        songs_with_dates = [s for s in self.daily_added_songs if s.get('release_date') and '-' in s['release_date']]
        decade_spread = []
        if songs_with_dates:
            decade_counts = Counter((int(s['release_date'][:4]) // 10) * 10 for s in songs_with_dates)
            total_dated_songs = len(songs_with_dates)
            sorted_decades = decade_counts.most_common(5)
            decade_spread = [
                (f"{decade}s", f"{((count / total_dated_songs) * 100):.0f}%")
                for decade, count in sorted_decades
            ]
        
        # Time analysis
        hour_counts = Counter()
        if self.daily_added_songs:
            for item in self.daily_added_songs:
                try:
                    timestamp = datetime.datetime.fromisoformat(item.get('timestamp', ''))
                    hour_counts[timestamp.hour] += 1
                except:
                    pass
        
        busiest_hour = hour_counts.most_common(1)[0] if hour_counts else (0, 0)
        
        # Failure analysis
        failure_reasons = Counter(item.get('reason', 'Unknown') for item in self.daily_search_failures)
        
        # Create the enhanced email
        def format_release_date(item):
            release_date = item.get('release_date', '')
            if release_date and len(release_date) >= 4:
                return f" • Released: {release_date[:4]}"
            return ""
        
        def format_timestamp(item):
            timestamp = item.get('timestamp')
            if timestamp:
                try:
                    return datetime.datetime.fromisoformat(timestamp).strftime('%H:%M:%S')
                except:
                    return 'Unknown'
            return 'Unknown'
        
        def format_song_item(item):
            title = item.get('radio_title', 'Unknown')
            artist = item.get('radio_artist', 'Unknown')
            timestamp = format_timestamp(item)
            release_date = format_release_date(item)
            return f'''
                    <div class="list-item">
                        <div class="song-title">{title}</div>
                        <div class="song-artist">{artist}</div>
                        <div class="song-meta">
                            Added at {timestamp}
                            {release_date}
                        </div>
                    </div>
                    '''
        
        def format_failure_item(item):
            title = item.get('radio_title', 'Unknown')
            artist = item.get('radio_artist', 'Unknown')
            reason = item.get('reason', 'Unknown')
            return f'''
                    <div class="list-item failure-item">
                        <div class="song-title">{title}</div>
                        <div class="song-artist">{artist}</div>
                        <div class="failure-reason">Reason: {reason}</div>
                    </div>
                    '''
        
        def format_artist_item(idx, artist, count):
            return f'''
                        <li>
                            <div style="display: flex; align-items: center; gap: 15px;">
                                <div class="artist-rank">{idx + 1}</div>
                                <span style="font-weight: bold;">{artist}</span>
                            </div>
                            <div class="artist-count">{count}</div>
                        </li>
                        '''
        
        def format_decade_item(decade, percentage):
            return f'''
                        <div class="decade-item">
                            <span style="font-weight: bold;">{decade}</span>
                            <div class="decade-percentage">{percentage}</div>
                        </div>
                        '''
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Radio X Daily Summary - {summary_date}</title>
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 20px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                
                .header {{
                    background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                    color: white;
                    padding: 40px 30px;
                    text-align: center;
                }}
                
                .header h1 {{
                    font-size: 2.5em;
                    font-weight: 300;
                    margin-bottom: 10px;
                }}
                
                .header .date {{
                    font-size: 1.2em;
                    opacity: 0.9;
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    padding: 30px;
                    background: #f8f9fa;
                }}
                
                .stat-card {{
                    background: white;
                    padding: 25px;
                    border-radius: 15px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                    text-align: center;
                    transition: transform 0.3s ease;
                }}
                
                .stat-card:hover {{
                    transform: translateY(-5px);
                }}
                
                .stat-number {{
                    font-size: 2.5em;
                    font-weight: bold;
                    color: #1e3c72;
                    margin-bottom: 10px;
                }}
                
                .stat-label {{
                    color: #666;
                    font-size: 0.9em;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }}
                
                .progress-bar {{
                    width: 100%;
                    height: 8px;
                    background: #e9ecef;
                    border-radius: 4px;
                    overflow: hidden;
                    margin-top: 10px;
                }}
                
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, #28a745, #20c997);
                    border-radius: 4px;
                    transition: width 0.3s ease;
                }}
                
                .section {{
                    padding: 30px;
                    border-bottom: 1px solid #e9ecef;
                }}
                
                .section:last-child {{
                    border-bottom: none;
                }}
                
                .section h2 {{
                    color: #1e3c72;
                    font-size: 1.8em;
                    margin-bottom: 20px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                
                .section h2::before {{
                    content: '';
                    width: 4px;
                    height: 30px;
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    border-radius: 2px;
                }}
                
                .list-item {{
                    background: #f8f9fa;
                    padding: 15px;
                    margin-bottom: 10px;
                    border-radius: 10px;
                    border-left: 4px solid #667eea;
                }}
                
                .song-title {{
                    font-weight: bold;
                    color: #1e3c72;
                    font-size: 1.1em;
                }}
                
                .song-artist {{
                    color: #666;
                    font-style: italic;
                }}
                
                .song-meta {{
                    font-size: 0.9em;
                    color: #888;
                    margin-top: 5px;
                }}
                
                .failure-item {{
                    background: #fff5f5;
                    border-left-color: #dc3545;
                }}
                
                .failure-reason {{
                    color: #dc3545;
                    font-weight: bold;
                }}
                
                .top-artists-list {{
                    list-style: none;
                }}
                
                .top-artists-list li {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 10px 0;
                    border-bottom: 1px solid #e9ecef;
                }}
                
                .top-artists-list li:last-child {{
                    border-bottom: none;
                }}
                
                .artist-rank {{
                    background: #667eea;
                    color: white;
                    width: 25px;
                    height: 25px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 0.8em;
                    font-weight: bold;
                }}
                
                .artist-count {{
                    background: #e9ecef;
                    color: #1e3c72;
                    padding: 4px 12px;
                    border-radius: 15px;
                    font-weight: bold;
                }}
                
                .decade-item {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 8px 0;
                }}
                
                .decade-percentage {{
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    color: white;
                    padding: 4px 12px;
                    border-radius: 15px;
                    font-weight: bold;
                }}
                
                .empty-state {{
                    text-align: center;
                    padding: 40px;
                    color: #666;
                    font-style: italic;
                }}
                
                .footer {{
                    background: #1e3c72;
                    color: white;
                    text-align: center;
                    padding: 20px;
                    font-size: 0.9em;
                }}
                
                @media (max-width: 600px) {{
                    .stats-grid {{
                        grid-template-columns: 1fr;
                    }}
                    
                    .header h1 {{
                        font-size: 2em;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎵 Radio X Daily Summary</h1>
                    <div class="date">{summary_date}</div>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number">{len(self.daily_added_songs)}</div>
                        <div class="stat-label">Songs Added</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {success_rate}%"></div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-number">{success_rate:.1f}%</div>
                        <div class="stat-label">Success Rate</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {success_rate}%"></div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-number">{unique_artist_count}</div>
                        <div class="stat-label">Unique Artists</div>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-number">{playlist_size}</div>
                        <div class="stat-label">Playlist Size</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {(playlist_size/MAX_PLAYLIST_SIZE)*100}%"></div>
                        </div>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-number">{busiest_hour[1]}</div>
                        <div class="stat-label">Busiest Hour ({busiest_hour[0]:02d}:00)</div>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-number">{len(self.failed_search_queue)}</div>
                        <div class="stat-label">In Retry Queue</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>🏆 Top Artists Today</h2>
                    {f'''
                    <ul class="top-artists-list">
                        {''.join([format_artist_item(idx, artist, count) for idx, (artist, count) in enumerate(top_artists)])}
                    </ul>
                    ''' if top_artists else '<div class="empty-state">No artists added today</div>'}
                </div>
                
                {f'''
                <div class="section">
                    <h2>📊 Decade Breakdown</h2>
                    <div style="margin-top: 15px;">
                        {''.join([format_decade_item(decade, percentage) for decade, percentage in decade_spread])}
                    </div>
                </div>
                ''' if decade_spread else ''}
                
                <div class="section">
                    <h2>✅ Successfully Added ({len(self.daily_added_songs)})</h2>
                    {''.join([format_song_item(item) for item in self.daily_added_songs]) if self.daily_added_songs else '<div class="empty-state">No songs were added today</div>'}
                </div>
                
                <div class="section">
                    <h2>❌ Failed Searches ({len(self.daily_search_failures)})</h2>
                    {''.join([format_failure_item(item) for item in self.daily_search_failures]) if self.daily_search_failures else '<div class="empty-state">No failures today - great job!</div>'}
                </div>
                
                <div class="footer">
                    <p>Generated by Radio X Spotify Adder v{BACKEND_VERSION}</p>
                    <p>Playlist: {playlist_name}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        self.send_summary_email(html, subject=f"🎵 Radio X Daily Summary - {summary_date}")
        self.daily_added_songs.clear()
        self.daily_search_failures.clear()
        self.save_state()

    def send_startup_notification(self, status_report_html_rows):
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
            self.log_event("Email settings not configured. Skipping startup notification.")
            return
        self.log_event("Sending startup notification email...")
        now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
        subject = f"Radio X Spotify Adder Service Started"
        html_body = f"""
        <html><head><style>body{{font-family:sans-serif}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px}} th{{background-color:#f2f2f2}}</style></head>
        <body><h2>Radio X Spotify Adder: Service Startup Diagnostics</h2>
            <p>The script started successfully at <b>{now_local.strftime("%Y-%m-%d %H:%M:%S %Z")}</b>.</p>
            <h3>System Checks:</h3>
            <table><tr><th>Check</th><th>Status</th><th>Details</th></tr>{status_report_html_rows}</table>
        </body></html>
        """
        self.send_summary_email(html_body, subject=subject)

    def send_debug_log(self):
        """Sends a debug log email with actual log entries from the application runtime."""
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
            self.log_event("Email settings not configured. Skipping debug log.")
            return
        
        self.log_event("Sending debug log email...")
        now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
        subject = f"Radio X Spotify Adder Debug Log - {now_local.strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Get all log entries from the debug handler
        all_logs = debug_log_handler.get_logs()
        
        # Filter for errors, warnings, and critical messages (most important for debugging)
        error_logs = debug_log_handler.get_logs(level_filter='ERROR')
        warning_logs = debug_log_handler.get_logs(level_filter='WARNING')
        critical_logs = debug_log_handler.get_logs(level_filter='CRITICAL')
        
        # Get recent info logs (last 50) for context
        recent_info_logs = debug_log_handler.get_logs(level_filter='INFO', max_entries=50)
        
        # Format log entries for email
        def format_log_section(title, logs, max_entries=None):
            if not logs:
                return f"<h3>{title}</h3><p>No entries found.</p>"
            
            if max_entries:
                logs = logs[-max_entries:]
            
            html = f"<h3>{title} ({len(logs)} entries)</h3>"
            html += "<table style='border-collapse: collapse; width: 100%; font-family: monospace; font-size: 12px;'>"
            html += "<tr style='background-color: #f2f2f2;'><th style='border: 1px solid #ddd; padding: 8px;'>Time</th><th style='border: 1px solid #ddd; padding: 8px;'>Level</th><th style='border: 1px solid #ddd; padding: 8px;'>Message</th><th style='border: 1px solid #ddd; padding: 8px;'>Location</th></tr>"
            
            for log in logs:
                timestamp = datetime.datetime.fromtimestamp(log['timestamp'], pytz.timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
                level_color = {
                    'DEBUG': '#808080',
                    'INFO': '#000000', 
                    'WARNING': '#FF8C00',
                    'ERROR': '#FF0000',
                    'CRITICAL': '#8B0000'
                }.get(log['level'], '#000000')
                
                location = f"{log.get('module', 'unknown')}.{log.get('funcName', 'unknown')}:{log.get('lineno', 'unknown')}"
                html += f"<tr><td style='border: 1px solid #ddd; padding: 4px;'>{timestamp}</td><td style='border: 1px solid #ddd; padding: 4px; color: {level_color}; font-weight: bold;'>{log.get('level', 'UNKNOWN')}</td><td style='border: 1px solid #ddd; padding: 4px;'>{log.get('message', 'No message')}</td><td style='border: 1px solid #ddd; padding: 4px; font-size: 10px;'>{location}</td></tr>"
            
            html += "</table>"
            return html
        
        # Build email content
        html_body = f"""
        <html><head><style>
            body {{ font-family: sans-serif; margin: 20px; }}
            h2 {{ border-bottom: 2px solid #ccc; padding-bottom: 5px; }}
            h3 {{ margin-top: 20px; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; font-weight: bold; }}
            .summary {{ background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        </style></head>
        <body>
            <h2>Radio X Spotify Adder Debug Log</h2>
            <p>Generated at <b>{now_local.strftime("%Y-%m-%d %H:%M:%S %Z")}</b></p>
            
            <div class="summary">
                <h3>Log Summary</h3>
                <p><strong>Total Log Entries:</strong> {len(all_logs)}</p>
                <p><strong>Critical Messages:</strong> {len(critical_logs)}</p>
                <p><strong>Error Messages:</strong> {len(error_logs)}</p>
                <p><strong>Warning Messages:</strong> {len(warning_logs)}</p>
                <p><strong>Info Messages:</strong> {len(recent_info_logs)} (showing last 50)</p>
            </div>
            
            {format_log_section("Critical Messages", critical_logs)}
            {format_log_section("Error Messages", error_logs)}
            {format_log_section("Warning Messages", warning_logs)}
            {format_log_section("Recent Info Messages", recent_info_logs)}
            
            <p style='margin-top: 30px; font-size: 12px; color: #666;'>
                This debug log contains all log entries captured during the application runtime. 
                Critical, Error, and Warning messages are shown in full, while Info messages are limited to the most recent 50 entries.
            </p>
        </body></html>
        """
        
        self.send_summary_email(html_body, subject=subject)
        self.log_event("Debug log email sent successfully.")
        
    def test_daily_summary_with_cached_data(self):
        """Creates a test daily summary using cached data from previous days."""
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
            self.log_event("Email settings not configured. Skipping test daily summary.")
            return
        
        self.log_event("Creating test daily summary with cached data...")
        
        # Load cached data
        cached_added_songs = []
        cached_failed_songs = []
        
        try:
            with self.file_lock:
                if os.path.exists(self.DAILY_ADDED_CACHE_FILE):
                    with open(self.DAILY_ADDED_CACHE_FILE, 'r') as f:
                        cached_added_songs = json.load(f)
                if os.path.exists(self.DAILY_FAILED_CACHE_FILE):
                    with open(self.DAILY_FAILED_CACHE_FILE, 'r') as f:
                        cached_failed_songs = json.load(f)
        except Exception as e:
            self.log_event(f"Error loading cached data: {e}")
            return
        
        if not cached_added_songs and not cached_failed_songs:
            self.log_event("No cached data found for test summary.")
            return
        
        # Temporarily replace current daily data with cached data
        original_added = self.daily_added_songs.copy()
        original_failed = self.daily_search_failures.copy()
        original_summary_date = self.last_summary_log_date
        
        try:
            self.daily_added_songs = cached_added_songs
            self.daily_search_failures = cached_failed_songs
            
            # Set the summary date to yesterday for the test
            yesterday = datetime.date.today() - datetime.timedelta(days=1)
            self.last_summary_log_date = yesterday
            
            # Create and send the test summary
            self.log_and_send_daily_summary()
            
            self.log_event("Test daily summary sent successfully using cached data.")
            
        finally:
            # Restore original data
            self.daily_added_songs = original_added
            self.daily_search_failures = original_failed
            self.last_summary_log_date = original_summary_date
        
    def run_startup_diagnostics(self, send_email=False):
        self.log_event("--- Running Startup Diagnostics ---")
        results = []
        try:
            if self.sp: results.append("<tr><td>Spotify Authentication</td><td style='color:green;'>SUCCESS</td><td>Authenticated successfully.</td></tr>")
            else: raise Exception("Spotify client not initialized.")
            playlist = self.spotify_api_call_with_retry(self.sp.playlist, SPOTIFY_PLAYLIST_ID, fields='name,id'); results.append(f"<tr><td>Playlist Access</td><td style='color:green;'>SUCCESS</td><td>Accessed playlist '{playlist.get('name', 'Unknown')}'.</td></tr>")
            if self.search_song_on_spotify("Wonderwall", "Oasis"): results.append("<tr><td>Test Search</td><td style='color:green;'>SUCCESS</td><td>Test search for 'Wonderwall' was successful.</td></tr>")
            else: results.append("<tr><td>Test Search</td><td style='color:red;'>FAIL</td><td>Test search for 'Wonderwall' returned no results.</td></tr>")
            tz = pytz.timezone(TIMEZONE); now = datetime.datetime.now(tz).strftime('%Z'); results.append(f"<tr><td>Timezone Check</td><td style='color:green;'>SUCCESS</td><td>Timezone '{TIMEZONE}' loaded (Current: {now}).</td></tr>")
            if all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]): results.append("<tr><td>Email Configuration</td><td style='color:green;'>SUCCESS</td><td>All email environment variables are set.</td></tr>")
            else: results.append("<tr><td>Email Configuration</td><td style='color:orange;'>WARNING</td><td>One or more email environment variables are missing.</td></tr>")
        except Exception as e:
            results.append(f"<tr><td colspan='3' style='color:red;'>A diagnostic check failed critically: {e}</td></tr>")
        
        if send_email:
            self.send_startup_notification("".join(results))

    def update_stats(self):
        """Calculates and updates the bot's statistics."""
        try:
            # Get current playlist size
            playlist_details = self.spotify_api_call_with_retry(self.sp.playlist, SPOTIFY_PLAYLIST_ID, fields='tracks.total')
            playlist_size = playlist_details['tracks']['total'] if playlist_details and 'tracks' in playlist_details else 0
            self.log_event(f"Current playlist size: {playlist_size}/{MAX_PLAYLIST_SIZE}")
        except Exception as e:
            playlist_size = 0 # Default on error
            logging.error(f"Could not fetch playlist size for stats: {e}")

        artist_counts = Counter(item.get('radio_artist', 'Unknown') for item in self.daily_added_songs)
        most_common = artist_counts.most_common(5)
        top_artists_list = [(artist, count) for artist, count in most_common] if most_common else []
        unique_artist_count = len(artist_counts)
        total_processed = len(self.daily_added_songs) + len(self.daily_search_failures)
        success_rate = f"{(len(self.daily_added_songs) / total_processed * 100):.1f}%" if total_processed > 0 else "0%"
        
        songs_with_dates = [s for s in self.daily_added_songs if s.get('release_date') and '-' in s['release_date']]
        decade_spread = []
        if songs_with_dates:
            decade_counts = Counter((int(s['release_date'][:4]) // 10) * 10 for s in songs_with_dates)
            total_dated_songs = len(songs_with_dates)
            sorted_decades = decade_counts.most_common(5)
            decade_spread = [
                (f"{decade}s", f"{((count / total_dated_songs) * 100):.0f}%")
                for decade, count in sorted_decades
            ]

        self.stats = {
            "playlist_size": playlist_size,
            "max_playlist_size": MAX_PLAYLIST_SIZE,
            "top_artists": top_artists_list,
            "unique_artists": unique_artist_count,
            "decade_spread": decade_spread,
            "success_rate": success_rate,
            "service_paused": self.service_state == "paused",
            "paused_reason": self.paused_reason,
        }

    # --- Main Application Loop ---
    def run(self):
        """Main monitoring loop."""
        self.is_running = True
        self.update_service_state('playing')
        self.log_event("--- run_radio_monitor thread initiated. ---")
        if not self.sp: self.log_event("ERROR: Spotify client is None. Thread cannot perform Spotify actions."); return
        if self.last_summary_log_date is None: self.last_summary_log_date = datetime.date.today()
        
        # Start timer update thread
        def timer_update_loop():
            while self.is_running:
                try:
                    # Only send timer updates during active hours when service is playing
                    if (START_TIME <= datetime.datetime.now(pytz.timezone(TIMEZONE)).time() <= END_TIME and 
                        self.service_state == 'playing'):
                        with app.app_context():
                            sse.publish({"timer_update": True}, type='status_update')
                            logging.debug(f"SSE: Published timer_update event")
                    time.sleep(30)  # Update every 30 seconds
                except Exception as e:
                    # Don't log timer update errors to avoid spam
                    logging.debug(f"SSE: Timer update error (suppressed): {e}")
                    time.sleep(30)
        
        timer_thread = threading.Thread(target=timer_update_loop, daemon=True)
        timer_thread.start()
        
        while True:
            try:
                now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
                if self.last_summary_log_date < now_local.date():
                    self.log_event(f"New day detected ({now_local.date().isoformat()}). Resetting daily flags.")
                    self.startup_email_sent, self.shutdown_summary_sent = False, False
                    self.daily_added_songs.clear(); self.daily_search_failures.clear(); self.save_state()
                    self.last_summary_log_date = now_local.date()
                # Handle time window that spans midnight (7am to 6am)
                if START_TIME <= now_local.time() <= END_TIME:
                    self.service_state = 'playing'
                    self.paused_reason = ''
                    if not self.startup_email_sent:
                        self.log_event("Active hours started."); self.send_startup_notification("<tr><td>Daily Operation</td><td style='color:green;'>SUCCESS</td><td>Entered active hours.</td></tr>"); self.startup_email_sent = True; self.shutdown_summary_sent = False
                    self.process_main_cycle()
                else:
                    self.update_service_state('paused', 'out_of_hours')
                    if not self.shutdown_summary_sent:
                        self.log_event("End of active day. Generating and sending daily summary."); self.log_and_send_daily_summary(); self.shutdown_summary_sent = True; self.startup_email_sent = False
                    time.sleep(CHECK_INTERVAL * 5); continue
            except Exception as e: logging.error(f"CRITICAL UNHANDLED ERROR in main loop: {e}", exc_info=True); time.sleep(CHECK_INTERVAL * 2) 
            self.log_event(f"Cycle complete. Waiting {CHECK_INTERVAL}s..."); time.sleep(CHECK_INTERVAL)

    def process_main_cycle(self):
        if not self.current_station_herald_id: self.current_station_herald_id = self.get_station_herald_id(RADIOX_STATION_SLUG)
        if not self.current_station_herald_id: return
        
        current_song_info = self.get_current_radiox_song(self.current_station_herald_id)
        song_added = False
        if current_song_info:
            title, artist, radiox_id = current_song_info["title"], current_song_info["artist"], current_song_info["id"]
            if not title or not artist: logging.warning("Empty title or artist from Radio X.")
            elif radiox_id == self.last_added_radiox_track_id: logging.info(f"Song '{title}' by '{artist}' (ID: {radiox_id}) same as last. Skipping.")
            else:
                self.log_event(f"New song: '{title}' by '{artist}'")
                spotify_track_id = self.search_song_on_spotify(title, artist, radiox_id) 
                if spotify_track_id:
                    if self.add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID): song_added = True 
                self.last_added_radiox_track_id = radiox_id 
        else: self.log_event("No new track info from Radio X.")
        
        if self.failed_search_queue and (song_added or (time.time() % (CHECK_INTERVAL * 4) < CHECK_INTERVAL)): self.process_failed_search_queue()
        
        current_time = time.time()
        if current_time - self.last_duplicate_check_time >= DUPLICATE_CHECK_INTERVAL:
            self.check_and_remove_duplicates(SPOTIFY_PLAYLIST_ID); self.last_duplicate_check_time = current_time
        
        self.update_stats()
        self.last_check_time = int(current_time)
        self.is_checking = True
        self.check_complete = True
        self.last_check_complete_time = int(time.time())
        self.save_last_check_complete_time()
        self.save_state()
        self.is_checking = False
        try:
            with app.app_context():
                sse.publish({"last_check_complete_time": self.last_check_complete_time}, type='status_update')
                logging.debug(f"SSE: Published status_update event after main cycle")
        except Exception as e:
            logging.error(f"SSE: Failed to publish status_update event: {e}")

        if psutil:
            mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
            self.log_event(f"[MEMORY] Backend RSS: {mem:.1f} MiB")


# --- Flask Routes & Script Execution ---
bot_instance = RadioXBot()
atexit.register(bot_instance.save_state)

@app.route('/force_duplicates')
def force_duplicates():
    bot_instance.log_event("Duplicate check manually triggered via web.")
    threading.Thread(target=bot_instance.check_and_remove_duplicates, args=(SPOTIFY_PLAYLIST_ID,)).start()
    return "Duplicate check has been triggered. Check logs for progress."

@app.route('/admin/force_duplicates', methods=['POST'])
def admin_force_duplicates():
    return force_duplicates()

@app.route('/force_queue')
def force_queue():
    bot_instance.log_event("Failed queue processing manually triggered via web.")
    threading.Thread(target=bot_instance.process_failed_search_queue).start()
    return "Processing of one item from the failed search queue has been triggered. Check logs for progress."

@app.route('/admin/force_queue', methods=['POST'])
def admin_force_queue():
    return force_queue()

@app.route('/force_diagnostics')
def force_diagnostics():
    bot_instance.log_event("Diagnostic check manually triggered via web.")
    threading.Thread(target=bot_instance.run_startup_diagnostics, kwargs={'send_email': True}).start()
    return "Diagnostic check has been triggered. Results will be emailed shortly."

@app.route('/admin/force_diagnostics', methods=['POST'])
def admin_force_diagnostics():
    return force_diagnostics()

@app.route('/admin/force_check', methods=['POST'])
def admin_force_check():
    bot_instance.log_event("Manual check triggered via web.")
    
    def run_manual_check():
        try:
            bot_instance.process_main_cycle()
            # Publish status update after manual check completes
            with app.app_context():
                sse.publish({"last_check_complete_time": bot_instance.last_check_complete_time}, type='status_update')
                logging.debug(f"SSE: Published status_update event after manual check")
        except Exception as e:
            bot_instance.log_event(f"Error during manual check: {e}")
    
    threading.Thread(target=run_manual_check).start()
    return "Manual check has been triggered. Check logs for progress."

@app.route('/admin/pause_resume', methods=['POST'])
def admin_pause_resume():
    if bot_instance.service_state == 'playing':
        bot_instance.update_service_state('paused', 'manual')
    else:
        bot_instance.update_service_state('playing')
    return f"Service {bot_instance.service_state}"

@app.route('/admin/send_summary', methods=['POST'])
def admin_send_summary():
    bot_instance.log_event("Daily summary manually triggered via web.")
    threading.Thread(target=bot_instance.log_and_send_daily_summary).start()
    return "Daily summary has been triggered. Check email for results."

@app.route('/admin/retry_failed', methods=['POST'])
def admin_retry_failed():
    bot_instance.log_event("Failed songs retry manually triggered via web.")
    threading.Thread(target=bot_instance.process_failed_search_queue).start()
    return "Retrying failed songs. Check logs for progress."

@app.route('/admin/send_debug_log', methods=['POST'])
def admin_send_debug_log():
    bot_instance.log_event("Debug log manually triggered via web.")
    threading.Thread(target=bot_instance.send_debug_log).start()
    return "Debug log has been triggered. Check email for results."

@app.route('/admin/test_daily_summary', methods=['POST'])
def admin_test_daily_summary():
    bot_instance.log_event("Daily summary test manually triggered via web.")
    threading.Thread(target=bot_instance.test_daily_summary_with_cached_data).start()
    return "Daily summary test has been triggered. Check email for results."

@app.route('/status')
def status():
    # Reads state from files to ensure consistency across processes
    try:
        with bot_instance.file_lock:
            with open(bot_instance.DAILY_ADDED_CACHE_FILE, 'r') as f: daily_added = json.load(f)
            with open(bot_instance.DAILY_FAILED_CACHE_FILE, 'r') as f: daily_failed = json.load(f)
            with open(bot_instance.FAILED_QUEUE_CACHE_FILE, 'r') as f: failed_queue = json.load(f)
            bot_instance.load_last_check_complete_time()
    except FileNotFoundError:
        daily_added, daily_failed, failed_queue = [], [], []
    except Exception as e:
        logging.error(f"Error reading state for /status endpoint: {e}")
        daily_added, daily_failed, failed_queue = [], [], []

    # Calculate seconds until next check based on last_check_complete_time
    last_check_time = getattr(bot_instance, 'last_check_complete_time', 0)
    current_time = int(time.time())
    
    # Always calculate next check time based on last completed check
    next_check_time = last_check_time + CHECK_INTERVAL
    seconds_until_next = max(0, next_check_time - current_time)

    # Format next check time
    next_check_time_str = datetime.datetime.fromtimestamp(next_check_time, pytz.timezone(TIMEZONE)).isoformat() if last_check_time else ''

    # Provide safe defaults for all expected frontend fields
    return jsonify({
        'last_song_added': daily_added[-1] if daily_added else None,
        'queue_size': len(failed_queue),
        'daily_added': daily_added,
        'daily_failed': daily_failed,
        'service_state': getattr(bot_instance, 'service_state', 'error'),
        'paused_reason': getattr(bot_instance, 'paused_reason', ''),
        'seconds_until_next_check': seconds_until_next,
        'is_checking': getattr(bot_instance, 'is_checking', False),
        'check_complete': getattr(bot_instance, 'check_complete', False),
        'last_check_time': getattr(bot_instance, 'last_check_time', 0),
        'last_check_complete_time': last_check_time,
        'next_check_time': next_check_time_str,
        'stats': getattr(bot_instance, 'stats', {}),
        'state_history': getattr(bot_instance, 'state_history', []),
        'backend_version': BACKEND_VERSION,
    })

@app.route('/')
def index_page():
    return render_template('index.html', active_hours=f"{START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}")

def log_backend_version():
    logging.info(f"RadioX Spotify Backend Version: {BACKEND_VERSION}")

@app.route('/version')
def version():
    return jsonify({"backend_version": BACKEND_VERSION})

def initialize_bot():
    """Handles the slow startup tasks in the background."""
    logging.info("Background initialization started.")
    # Log version at startup
    log_backend_version()
    
    # Try to authenticate with Spotify, but don't fail if it doesn't work
    auth_success = bot_instance.authenticate_spotify()
    if auth_success:
        bot_instance.load_state() 
        bot_instance.run_startup_diagnostics(send_email=False) # Run checks but don't email on auto-start
        
        monitor_thread = threading.Thread(target=bot_instance.run, daemon=True)
        monitor_thread.start()
        logging.info("Background initialization completed successfully.")
    else:
        logging.warning("Spotify authentication failed. The main monitoring thread will not start, but the web interface will still be available.")
        bot_instance.update_service_state('error', 'Spotify authentication failed')

@app.route('/test_sse')
def test_sse():
    """Test endpoint to verify SSE is working."""
    try:
        with app.app_context():
            sse.publish({"test": "SSE is working!", "timestamp": datetime.datetime.now().isoformat()}, type='test')
        return "SSE test event sent"
    except Exception as e:
        return f"SSE test failed: {e}"

@app.route('/stream')
def stream():
    """SSE endpoint."""
    logging.info("Client connected to /stream endpoint.")
    def event_stream():
        if redis_client is None:
            yield f"data: {json.dumps({'error': 'Redis not available'})}\n\n"
            return
        
        # Continuously yield messages from Redis pub/sub
        try:
            pubsub = redis_client.pubsub()
            pubsub.subscribe('radiox_spotify_events')
            for message in pubsub.listen():
                if message['type'] == 'message':
                    yield f"data: {message['data'].decode('utf-8')}\n\n"
        except Exception as e:
            logging.error(f"Error in SSE stream: {e}")
            yield f"data: {json.dumps({'error': 'Stream error'})}\n\n"

    return Response(event_stream(), content_type='text/event-stream')

# --- Script Execution ---
if __name__ == "__main__":
    # This block runs for local development
    logging.info("Script being run directly for local testing.")
    initialize_bot()
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        print("\nWARNING: Email environment variables not set. Emails will not be sent.\n")
    port = int(os.environ.get("PORT", 8080)) 
    logging.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) 
else:
    # This block runs when deployed on Gunicorn (like on Render)
    threading.Thread(target=initialize_bot, daemon=True).start()
