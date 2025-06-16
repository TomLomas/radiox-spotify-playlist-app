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
from flask import Flask, jsonify, render_template, send_from_directory, send_file
import datetime
import pytz 
import smtplib 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque, Counter
import atexit
import base64
from dotenv import load_dotenv
import enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

# Reduce Werkzeug access log noise - suppress GET /status logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Custom log filter to suppress /status logs
class StatusLogFilter(logging.Filter):
    def filter(self, record):
        if 'GET /status' in record.getMessage():
            return False
        return True
log.addFilter(StatusLogFilter())

# --- Flask App Setup ---
app = Flask(__name__, 
    static_folder='frontend/build',
    static_url_path='')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching

# --- Configuration ---
load_dotenv()
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SPOTIFY_PLAYLIST_ID = os.getenv("SPOTIFY_PLAYLIST_ID")
RADIOX_STATION_SLUG = "radiox" 

# Script Operation Settings
CHECK_INTERVAL = 120  # seconds (restored from 10)
logging.info(f"CHECK_INTERVAL at startup: {CHECK_INTERVAL}")
DUPLICATE_CHECK_INTERVAL = 30 * 60 
MAX_PLAYLIST_SIZE = 500
MAX_FAILED_SEARCH_QUEUE_SIZE = 30 
MAX_FAILED_SEARCH_ATTEMPTS = 3    

# Active Time Window (BST/GMT Aware)
TIMEZONE = 'Europe/London'
START_TIME = datetime.time(7, 30)
END_TIME = datetime.time(22, 0)

# Email Summary Settings (from environment)
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = os.getenv("EMAIL_PORT") 
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

BOLD = '\033[1m'
RESET = '\033[0m'
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

print("PRINT TEST: Startup reached")
logging.info("LOGGING CONFIGURED: Startup log from main process.")

# --- Main Application Class ---

class ServiceState(enum.Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    OUT_OF_HOURS = "out_of_hours"
    MANUAL_OVERRIDE = "manual_override"

class RadioXBot:
    def __init__(self):
        """Initializes the RadioXBot with state variables, persistent cache setup, and logging."""
        # State Variables
        self.sp = None
        self.last_added_radiox_track_id = None
        self.herald_id_cache = {}
        self.last_duplicate_check_time = 0
        self.last_summary_log_date = datetime.date.today() - datetime.timedelta(days=1)
        self.startup_email_sent = False
        self.shutdown_summary_sent = False
        self.current_station_herald_id = None
        self.current_song_info = None
        self.is_running = False
        self.state_history = deque(maxlen=100)  # Track state transitions
        self.override_reset_day = datetime.date.today()
        self.next_check_time = time.time() + CHECK_INTERVAL
        self.last_check_time = time.time()  # Track when the last check was performed
        self.is_checking = False  # Flag to indicate if a check is in progress
        self.check_complete = True  # Flag to indicate if the last check completed successfully
        self.last_check_complete_time = time.time()  # Initialize with current time
        
        # Initialize service state based on current time
        now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
        if START_TIME <= now_local.time() <= END_TIME:
            self.service_state = ServiceState.PLAYING
            self.log_state_transition(self.service_state, reason="Startup during active hours")
        else:
            self.service_state = ServiceState.OUT_OF_HOURS
            self.log_state_transition(self.service_state, reason="Startup outside active hours")

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

        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(maxlen=200) 
        self.failed_search_queue = deque(maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
        self.daily_added_songs = [] 
        self.daily_search_failures = [] 
        self.event_log = deque(maxlen=50)
        self.log_event("Application instance created. Waiting for initialization.")
        self.file_lock = threading.Lock()

    def log_event(self, message):
        """Adds an event to the global log for the web UI and standard logging."""
        logging.info(message)
        clean_message = ANSI_ESCAPE.sub('', message) # Remove ANSI codes for web log
        self.event_log.appendleft(f"[{datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S')}] {clean_message}")

    def log_state_transition(self, new_state, reason=""):
        timestamp = datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S')
        entry = {"timestamp": timestamp, "state": new_state.value, "reason": reason}
        self.state_history.appendleft(entry)
        logging.info(f"STATE TRANSITION: {entry}")

    # --- Persistent State Management ---
    def save_state(self):
        """Save critical state to disk."""
        state = {
            'service_state': self.service_state.value,
            'state_history': list(self.state_history),
            'last_duplicate_check_time': self.last_duplicate_check_time,
            # ... add other state as needed ...
        }
        with open('bot_state.json', 'w') as f:
            json.dump(state, f)
        with self.file_lock:
            try:
                with open(self.RECENTLY_ADDED_CACHE_FILE, 'w') as f: json.dump(list(self.RECENTLY_ADDED_SPOTIFY_IDS), f)
                with open(self.FAILED_QUEUE_CACHE_FILE, 'w') as f: json.dump(list(self.failed_search_queue), f)
                with open(self.DAILY_ADDED_CACHE_FILE, 'w') as f: json.dump(self.daily_added_songs, f)
                with open(self.DAILY_FAILED_CACHE_FILE, 'w') as f: json.dump(self.daily_search_failures, f)
                logging.debug("Successfully saved application state to disk.")
            except Exception as e:
                logging.error(f"Failed to save state to disk: {e}")

    def load_state(self):
        """Load critical state from disk."""
        try:
            with open('bot_state.json', 'r') as f:
                state = json.load(f)
                self.service_state = ServiceState(state.get('service_state', ServiceState.PAUSED.value))
                self.state_history = deque(state.get('state_history', []), maxlen=100)
                self.last_duplicate_check_time = state.get('last_duplicate_check_time', 0)
        except FileNotFoundError:
            pass
        with self.file_lock:
            try:
                if os.path.exists(self.RECENTLY_ADDED_CACHE_FILE):
                    with open(self.RECENTLY_ADDED_CACHE_FILE, 'r') as f:
                        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=200)
                        logging.info(f"Loaded {len(self.RECENTLY_ADDED_SPOTIFY_IDS)} recent tracks from cache.")
                if os.path.exists(self.FAILED_QUEUE_CACHE_FILE):
                    with open(self.FAILED_QUEUE_CACHE_FILE, 'r') as f:
                        self.failed_search_queue = deque(json.load(f), maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
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

    # --- Authentication ---
    def authenticate_spotify(self):
        """Initializes and authenticates the Spotipy client using environment variables and cache, with detailed logging."""
        def mask_secret(val):
            if not val:
                return 'MISSING'
            if len(val) <= 6:
                return '*' * len(val)
            return val[:2] + '*' * (len(val)-4) + val[-2:]
        def write_cache():
            cache_content_b64 = os.getenv("SPOTIPY_CACHE_BASE64")
            if cache_content_b64:
                try:
                    cache_content_json = base64.b64decode(cache_content_b64).decode('utf-8')
                    with open(".spotipy_cache", 'w') as f: f.write(cache_content_json)
                    return True
                except Exception as e: logging.error(f"Error decoding/writing Spotify cache: {e}"); return False
            return False

        scope = "playlist-modify-public playlist-modify-private user-library-read"
        # Log all relevant environment variables (masking secrets)
        logging.info(f"SPOTIPY_CLIENT_ID: {mask_secret(SPOTIPY_CLIENT_ID)}")
        logging.info(f"SPOTIPY_CLIENT_SECRET: {mask_secret(SPOTIPY_CLIENT_SECRET)}")
        logging.info(f"SPOTIPY_REDIRECT_URI: {SPOTIPY_REDIRECT_URI if SPOTIPY_REDIRECT_URI else 'MISSING'}")
        logging.info(f"SPOTIFY_PLAYLIST_ID: {SPOTIFY_PLAYLIST_ID if SPOTIFY_PLAYLIST_ID else 'MISSING'}")
        try:
            write_cache()
            auth_manager = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET, redirect_uri=SPOTIPY_REDIRECT_URI, scope=scope, cache_path=".spotipy_cache") 
            token_info = auth_manager.get_cached_token()
            if token_info:
                self.sp = spotipy.Spotify(auth_manager=auth_manager)
                user = self.sp.current_user()
                if user:
                    self.log_event(f"Successfully authenticated with Spotify as {user['display_name']}.")
                    return True
                else: self.sp = None; self.log_event("ERROR: Could not get Spotify user details with token.")
            else: self.sp = None; self.log_event("ERROR: Failed to obtain Spotify token.")
        except Exception as e:
            self.sp = None
            logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
            logging.error(f"SPOTIPY_CLIENT_ID: {mask_secret(SPOTIPY_CLIENT_ID)}")
            logging.error(f"SPOTIPY_CLIENT_SECRET: {mask_secret(SPOTIPY_CLIENT_SECRET)}")
            logging.error(f"SPOTIPY_REDIRECT_URI: {SPOTIPY_REDIRECT_URI if SPOTIPY_REDIRECT_URI else 'MISSING'}")
            logging.error(f"SPOTIFY_PLAYLIST_ID: {SPOTIFY_PLAYLIST_ID if SPOTIFY_PLAYLIST_ID else 'MISSING'}")
        return False
    
    # --- API Wrappers and Helpers ---
    def spotify_api_call_with_retry(self, func, *args, **kwargs):
        """Wraps Spotify API calls with retry logic for network and rate limit errors."""
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
        """Fetches the heraldId for a given station slug from the Radio X API, with caching."""
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
        """Connects to the Radio X WebSocket and retrieves the current song info."""
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
        """Attempts to find a song on Spotify using several title cleaning strategies."""
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
        """Ensures the playlist does not exceed the maximum size by removing the oldest track if needed."""
        if not self.sp: return False
        try:
            playlist_details = self.spotify_api_call_with_retry(self.sp.playlist, playlist_id, fields='tracks.total')
            if not playlist_details: return False
            total_tracks = playlist_details['tracks']['total']
            self.log_event(f"Playlist size: {total_tracks}/{MAX_PLAYLIST_SIZE}")
            if total_tracks >= MAX_PLAYLIST_SIZE:
                self.log_event(f"Playlist at/over limit. Removing oldest song.")
                oldest_track_response = self.spotify_api_call_with_retry(self.sp.playlist_items, playlist_id, limit=1, offset=0, fields='items.track.uri')
                if oldest_track_response and oldest_track_response['items']:
                    oldest_track_uri = oldest_track_response['items'][0]['track']['uri']
                    self.spotify_api_call_with_retry(self.sp.playlist_remove_specific_occurrences_of_items, playlist_id, items=[{'uri': oldest_track_uri, 'positions': [0]}])
                    self.log_event(f"Removed oldest song.")
                    time.sleep(1)
                    return True
                return False
        except Exception as e: logging.error(f"Error managing playlist size: {e}"); return False
        return True

    def add_song_to_playlist(self, radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
        """Adds a song to the Spotify playlist, handling duplicates and logging results."""
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

            self.daily_added_songs.append({
                "timestamp": datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "radio_title": radio_x_title, 
                "radio_artist": radio_x_artist, 
                "spotify_title": spotify_name, 
                "spotify_artist": spotify_artists_str, 
                "spotify_id": spotify_track_id, 
                "release_date": release_date,
                "album_art_url": album_art_url
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
        """Attempts to re-search and add songs that previously failed to be found on Spotify."""
        if not self.failed_search_queue: return
        self.log_event(f"PFSQ: Processing 1 item from queue (size: {len(self.failed_search_queue)}).")
        item = self.failed_search_queue.popleft()
        item['attempts'] += 1
        spotify_id = self.search_song_on_spotify(item['title'], item['artist'], is_retry_from_queue=True)
        if spotify_id:
            self.add_song_to_playlist(item['title'], item['artist'], spotify_id, SPOTIFY_PLAYLIST_ID)
        elif item['attempts'] < MAX_FAILED_SEARCH_ATTEMPTS:
            self.failed_search_queue.append(item)
            self.log_event(f"PFSQ: Re-queued '{item['title']}' (Attempts: {item['attempts']}).")
        else:
            self.log_event(f"PFSQ: Max retries reached for '{item['title']}'. Discarding.")
            self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": item['title'], "radio_artist": item['artist'], "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."})

    # --- Email & Summary Functions ---
    def send_summary_email(self, html_body, subject):
        """Sends a summary email with the given HTML body and subject."""
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
        """Generates an HTML summary of daily stats for email or web display."""
        if not self.daily_added_songs and not self.daily_search_failures: return ""
        try:
            artist_counts = Counter(item['radio_artist'] for item in self.daily_added_songs)
            most_common = artist_counts.most_common(3)
            top_artists_str = ", ".join([f"{artist} ({count})" for artist, count in most_common]) if most_common else "N/A"
            unique_artist_count = len(artist_counts)
            failure_reasons = Counter(item['reason'] for item in self.daily_search_failures)
            failure_breakdown_str = "; ".join([f"{reason}: {count}" for reason, count in failure_reasons.items()]) or "None"
            total_processed = len(self.daily_added_songs) + len(self.daily_search_failures)
            success_rate = (len(self.daily_added_songs) / total_processed * 100) if total_processed > 0 else 100
            busiest_hour_str, newest_song_str, oldest_song_str, decade_breakdown_str = "N/A", "N/A", "N/A", ""
            if self.daily_added_songs:
                hour_counts = Counter(datetime.datetime.fromisoformat(item['timestamp']).hour for item in self.daily_added_songs)
                busiest_hour, song_count = hour_counts.most_common(1)[0]
                busiest_hour_str = f"{busiest_hour:02d}:00 - {busiest_hour:02d}:59 ({song_count} songs)"
                songs_with_dates = [s for s in self.daily_added_songs if s.get('release_date') and '-' in s['release_date']]
                if songs_with_dates:
                    songs_with_dates.sort(key=lambda x: x['release_date'])
                    oldest_song, newest_song = songs_with_dates[0], songs_with_dates[-1]
                    oldest_song_str = f"{oldest_song['spotify_title']} by {oldest_song['spotify_artist']} ({oldest_song['release_date'][:4]})"
                    newest_song_str = f"{newest_song['spotify_title']} by {newest_song['spotify_artist']} ({newest_song['release_date'][:4]})"
                    decade_counts = Counter((int(s['release_date'][:4]) // 10) * 10 for s in songs_with_dates)
                    total_dated_songs = len(songs_with_dates)
                    decade_breakdown_str = " | ".join([f"<b>{decade}s:</b> {((decade_counts[decade] / total_dated_songs) * 100):.0f}%%" for decade in sorted(decade_counts.keys())])
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
        """Logs and sends the daily summary email if new songs or failures occurred."""
        if not self.daily_added_songs and not self.daily_search_failures:
            self.log_event("No songs or failures today. Skipping summary email.")
            self.daily_added_songs.clear(); self.daily_search_failures.clear(); self.save_state()
            return
        summary_date = self.last_summary_log_date.isoformat()
        stats_html = self.get_daily_stats_html()
        html = f"""
        <html><head><meta name='viewport' content='width=device-width, initial-scale=1'><style>
        body{{font-family:sans-serif;background:#f4f4f9;margin:0;padding:0;}}
        .container{{max-width:600px;margin:auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08);}}
        h2{{color:#1DB954;border-bottom:2px solid #eee;padding-bottom:8px;}}
        h3{{margin-top:24px;color:#333;}}
        table{{border-collapse:collapse;width:100%;margin-top:10px;}}
        th,td{{border:1px solid #ddd;padding:8px;text-align:left;}}
        th{{background:#f2f2f2;}}
        tr:nth-child(even){{background:#fafafa;}}
        .stat{{font-size:1.1em;margin-bottom:8px;}}
        @media (max-width:700px){{.container{{padding:5px;}}table,th,td{{font-size:0.95em;}}}}
        </style></head><body><div class='container'>
            <h2>Radio X Spotify Adder Daily Summary: {summary_date}</h2>{stats_html}<h3>ADDED (Total: {len(self.daily_added_songs)})</h3>
        """
        if self.daily_added_songs:
            html += "<table><tr><th>Title</th><th>Artist</th></tr>" + "".join([f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td></tr>" for item in self.daily_added_songs]) + "</table>"
        else: html += "<p>No songs were added today.</p>"
        html += f"<h3>FAILED (Total: {len(self.daily_search_failures)})</h3>"
        if self.daily_search_failures:
            html += "<table><tr><th>Title</th><th>Artist</th><th>Reason</th></tr>" + "".join([f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td><td>{item['reason']}</td></tr>" for item in self.daily_search_failures]) + "</table>"
        else: html += "<p>No unresolved failures today.</p>"
        html += "</div></body></html>"
        self.send_summary_email(html, subject=f"Radio X Spotify Adder Daily Summary - {summary_date}")
        self.daily_added_songs.clear(); self.daily_search_failures.clear(); self.save_state()

    def send_startup_notification(self, status_report_html_rows):
        """Sends a startup notification email with diagnostic results."""
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
        
    def run_startup_diagnostics(self, send_email=False):
        """Runs startup diagnostics and optionally emails the results."""
        self.log_event("--- Running Startup Diagnostics ---")
        results = []
        try:
            if self.sp: results.append("<tr><td>Spotify Authentication</td><td style='color:green;'>SUCCESS</td><td>Authenticated successfully.</td></tr>")
            else: raise Exception("Spotify client not initialized.")
            playlist = self.spotify_api_call_with_retry(self.sp.playlist, SPOTIFY_PLAYLIST_ID, fields='name,id'); results.append(f"<tr><td>Playlist Access</td><td style='color:green;'>SUCCESS</td><td>Accessed playlist '{playlist['name']}'.</td></tr>")
            if self.search_song_on_spotify("Wonderwall", "Oasis"): results.append("<tr><td>Test Search</td><td style='color:green;'>SUCCESS</td><td>Test search for 'Wonderwall' was successful.</td></tr>")
            else: results.append("<tr><td>Test Search</td><td style='color:red;'>FAIL</td><td>Test search for 'Wonderwall' returned no results.</td></tr>")
            tz = pytz.timezone(TIMEZONE); now = datetime.datetime.now(tz).strftime('%Z'); results.append(f"<tr><td>Timezone Check</td><td style='color:green;'>SUCCESS</td><td>Timezone '{TIMEZONE}' loaded (Current: {now}).</td></tr>")
            if all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]): results.append("<tr><td>Email Configuration</td><td style='color:green;'>SUCCESS</td><td>All email environment variables are set.</td></tr>")
            else: results.append("<tr><td>Email Configuration</td><td style='color:orange;'>WARNING</td><td>One or more email environment variables are missing.</td></tr>")
        except Exception as e:
            results.append(f"<tr><td colspan='3' style='color:red;'>A diagnostic check failed critically: {e}</td></tr>")
        
        if send_email:
            self.send_startup_notification("".join(results))

    def should_run(self):
        """Determines if the bot should run based on manual override, active hours, and pause state."""
        now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
        # Move 'new day' reset to 07:00
        reset_time = datetime.time(7, 0)
        if (now_local.date() > self.override_reset_day or
            (now_local.date() == self.override_reset_day and now_local.time() >= reset_time and not hasattr(self, '_reset_done_today'))):
            self.override_reset_day = now_local.date()
            self._reset_done_today = True
            self.set_service_state(ServiceState.PLAYING, "Daily reset")
        
        # If manually paused, always pause
        if self.service_state == ServiceState.PAUSED:
            return False
            
        # If in hours, run
        if START_TIME <= now_local.time() <= END_TIME:
            if self.service_state != ServiceState.PLAYING:
                self.set_service_state(ServiceState.PLAYING, "In hours")
            return True
            
        # If out of hours, only run if manually resumed
        if self.service_state == ServiceState.MANUAL_OVERRIDE:
            return True
            
        # Otherwise, mark as out of hours
        if self.service_state != ServiceState.OUT_OF_HOURS:
            self.set_service_state(ServiceState.OUT_OF_HOURS, "Out of hours")
        return False

    def toggle_pause(self, reason="Admin toggle"):
        if self.service_state == ServiceState.PLAYING:
            self.set_service_state(ServiceState.PAUSED, reason)
        elif self.service_state == ServiceState.PAUSED:
            self.set_service_state(ServiceState.PLAYING, reason)

    def set_out_of_hours(self, reason="Out of hours"):
        if self.service_state != ServiceState.OUT_OF_HOURS:
            self.set_service_state(ServiceState.OUT_OF_HOURS, reason)

    def set_service_state(self, new_state, reason=""):
        if self.service_state != new_state:
            self.service_state = new_state
            self.log_state_transition(new_state, reason)
            self.save_state()

    def retry_all_failed_songs(self):
        """Attempts to re-process all failed song searches in the queue."""
        self.log_event("Admin: Retrying all failed songs in the queue.")
        while self.failed_search_queue:
            self.process_failed_search_queue()

    def update_next_check_time(self):
        """Set the next check time to now + CHECK_INTERVAL."""
        current_time = time.time()
        self.next_check_time = current_time + CHECK_INTERVAL
        self.last_check_complete_time = current_time
        self.check_complete = True
        self.is_checking = False
        logging.info(f"[Timer] Updated next check time: {datetime.datetime.fromtimestamp(self.next_check_time).strftime('%H:%M:%S')}")
        logging.info(f"[Timer] Last check complete time: {datetime.datetime.fromtimestamp(self.last_check_complete_time).strftime('%H:%M:%S')}")

    def get_seconds_until_next_check(self):
        """Return seconds until the next scheduled check."""
        return max(0, int(self.next_check_time - time.time()))

    # --- Main Application Loop ---
    def run(self):
        logging.info("[Main Loop] Entered run() method. Main loop starting.")
        while True:
            logging.info("[Main Loop] Heartbeat - main loop is alive.")
            self.load_state()  # Always reload state at the start of each tick
            now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
            in_hours = START_TIME <= now_local.time() <= END_TIME
            logging.info(f"[Main Loop] PID={os.getpid()} TID={threading.get_ident()} should_run={self.should_run()}, in_hours={in_hours}")
            if self.should_run():
                self.process_main_cycle()
            else:
                logging.info("[Main Loop] Service is paused (manual or out of hours). Skipping check.")
            time.sleep(CHECK_INTERVAL)

    def process_main_cycle(self):
        """Processes the main cycle: fetches now playing, searches Spotify, adds to playlist, and saves state."""
        # Ensure Spotify is authenticated
        if self.sp is None:
            self.log_event("Spotify client not initialized. Attempting to authenticate...")
            if not self.authenticate_spotify():
                self.log_event("ERROR: Could not authenticate with Spotify. Skipping cycle.")
                return
        if not self.current_station_herald_id: self.current_station_herald_id = self.get_station_herald_id(RADIOX_STATION_SLUG)
        if not self.current_station_herald_id: return
        
        self.is_checking = True
        self.check_complete = False
        self.last_check_time = time.time()
        logging.info(f"[Timer] Starting check at {datetime.datetime.fromtimestamp(self.last_check_time).strftime('%H:%M:%S')}")
        
        current_song_info = self.get_current_radiox_song(self.current_station_herald_id)
        self.current_song_info = current_song_info
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
        
        self.is_checking = False
        self.check_complete = True
        self.last_check_complete_time = time.time()
        logging.info(f"[Timer] Check completed at {datetime.datetime.fromtimestamp(self.last_check_complete_time).strftime('%H:%M:%S')}")
        
        self.update_next_check_time()
        self.save_state()


# --- Flask Routes & Script Execution ---
bot_instance = RadioXBot()
atexit.register(bot_instance.save_state)

@app.route('/force_duplicates')
def force_duplicates():
    """Manually triggers a duplicate check on the playlist."""
    bot_instance.log_event("Duplicate check manually triggered via web.")
    threading.Thread(target=bot_instance.check_and_remove_duplicates, args=(SPOTIFY_PLAYLIST_ID,)).start()
    return "Duplicate check has been triggered. Check logs for progress."

@app.route('/force_queue')
def force_queue():
    """Manually processes one item from the failed search queue."""
    bot_instance.log_event("Failed queue processing manually triggered via web.")
    threading.Thread(target=bot_instance.process_failed_search_queue).start()
    return "Processing of one item from the failed search queue has been triggered. Check logs for progress."

@app.route('/force_diagnostics')
def force_diagnostics():
    """Manually runs diagnostics and emails the results."""
    bot_instance.log_event("Diagnostic check manually triggered via web.")
    threading.Thread(target=bot_instance.run_startup_diagnostics, kwargs={'send_email': True}).start()
    return "Diagnostic check has been triggered. Results will be emailed shortly."

@app.route('/test')
def test():
    print("TEST ENDPOINT HIT")
    return jsonify({"message": "API routing works!"})

@app.route('/status')
def status():
    try:
        with bot_instance.file_lock:
            with open(bot_instance.DAILY_ADDED_CACHE_FILE, 'r') as f: daily_added = json.load(f)
            with open(bot_instance.DAILY_FAILED_CACHE_FILE, 'r') as f: daily_failed = json.load(f)
            with open(bot_instance.FAILED_QUEUE_CACHE_FILE, 'r') as f: failed_queue = json.load(f)
    except FileNotFoundError:
        daily_added, daily_failed, failed_queue = [], [], []
    except Exception as e:
        logging.error(f"Error reading state for /status endpoint: {e}")
        daily_added, daily_failed, failed_queue = [], [], []

    # Compute stats for frontend
    artist_counts = Counter(item['radio_artist'] for item in daily_added)
    most_common = artist_counts.most_common(3)
    top_artists = ", ".join([f"{artist} ({count})" for artist, count in most_common]) if most_common else "N/A"
    unique_artists = len(artist_counts)
    failure_reasons = Counter(item['reason'] for item in daily_failed)
    most_common_failure = failure_reasons.most_common(1)[0][0] if failure_reasons else "N/A"
    total_processed = len(daily_added) + len(daily_failed)
    success_rate = (len(daily_added) / total_processed * 100) if total_processed > 0 else 100

    # Determine pause reason
    now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
    in_hours = START_TIME <= now_local.time() <= END_TIME
    if bot_instance.service_state == ServiceState.PAUSED:
        paused_reason = 'manual'
    elif not in_hours:
        paused_reason = 'out_of_hours'
    else:
        paused_reason = 'none'

    stats = {
        'top_artists': top_artists,
        'unique_artists': unique_artists,
        'most_common_failure': most_common_failure,
        'success_rate': f"{success_rate:.1f}%",
        'service_paused': bot_instance.service_state == ServiceState.PAUSED or not in_hours,
        'paused_reason': paused_reason
    }

    seconds_until_next_check = bot_instance.get_seconds_until_next_check()
    if seconds_until_next_check == 0:
        bot_instance.update_next_check_time()
        seconds_until_next_check = bot_instance.get_seconds_until_next_check()
    
    logging.info(f"[Timer] Status endpoint - seconds until next check: {seconds_until_next_check}")
    logging.info(f"[Timer] Status endpoint - last check complete time: {datetime.datetime.fromtimestamp(bot_instance.last_check_complete_time).strftime('%H:%M:%S')}")

    return jsonify({
        'last_song_added': daily_added[-1] if daily_added else None,
        'current_song': bot_instance.current_song_info["title"] + " - " + bot_instance.current_song_info["artist"] if bot_instance.current_song_info else None,
        'queue_size': len(failed_queue),
        'daily_added': daily_added,
        'daily_failed': daily_failed,
        'stats': stats,
        'seconds_until_next_check': seconds_until_next_check,
        'service_state': bot_instance.service_state.value,
        'state_history': list(bot_instance.state_history),
        'last_check_time': bot_instance.last_check_time,
        'is_checking': bot_instance.is_checking,
        'check_complete': bot_instance.check_complete,
        'last_check_complete_time': bot_instance.last_check_complete_time,
        'next_check_time': datetime.datetime.fromtimestamp(bot_instance.next_check_time, pytz.timezone(TIMEZONE)).isoformat() if hasattr(bot_instance, 'next_check_time') else None
    })

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

@app.route('/health')
def health():
    """Health check endpoint for deployment platforms."""
    return jsonify({"status": "ok"}), 200

@app.route('/admin/send_summary', methods=['POST'])
def admin_send_summary():
    """Manually send the daily summary email now."""
    bot_instance.log_event("Admin: Manual summary email triggered via web.")
    bot_instance.log_and_send_daily_summary()
    return "Summary email sent."

@app.route('/admin/retry_failed', methods=['POST'])
def admin_retry_failed():
    """Manually retry all failed songs in the queue in a background thread."""
    def do_retry_failed():
        if bot_instance.sp is None:
            bot_instance.log_event("Spotify client not initialized. Attempting to authenticate...")
            if not bot_instance.authenticate_spotify():
                bot_instance.log_event("ERROR: Could not authenticate with Spotify. Skipping retry failed.")
                return
        bot_instance.retry_all_failed_songs()
    threading.Thread(target=do_retry_failed).start()
    return "Retrying all failed songs in background. Check logs for progress."

@app.route('/admin/force_duplicates', methods=['POST'])
def admin_force_duplicates():
    """Manually trigger a duplicate check on the playlist in a background thread."""
    def do_force_duplicates():
        if bot_instance.sp is None:
            bot_instance.log_event("Spotify client not initialized. Attempting to authenticate...")
            if not bot_instance.authenticate_spotify():
                bot_instance.log_event("ERROR: Could not authenticate with Spotify. Skipping duplicate check.")
                return
        bot_instance.check_and_remove_duplicates(SPOTIFY_PLAYLIST_ID)
    threading.Thread(target=do_force_duplicates).start()
    return "Duplicate check started in background. Check logs for progress."

@app.route('/admin/pause_resume', methods=['POST'])
def admin_pause_resume():
    """Toggle pause/resume override for the service. If resuming, immediately trigger a check."""
    was_paused = bot_instance.service_state == ServiceState.PAUSED or not bot_instance.should_run()
    paused = bot_instance.toggle_pause()
    status = "paused" if paused else "resumed"
    bot_instance.log_event(f"Admin: Service {status} via web override.")
    # If we just resumed, trigger a check immediately
    if was_paused and not paused:
        threading.Thread(target=bot_instance.process_main_cycle).start()
    return f"Service {status}."

@app.route('/admin/refresh', methods=['GET'])
def admin_refresh():
    """Return the latest status (same as /status, for refresh button)."""
    return status()

@app.route('/admin/force_check', methods=['POST'])
def admin_force_check():
    """Immediately perform a new track check and reset the check timer in a background thread."""
    def do_force_check():
        if bot_instance.sp is None:
            bot_instance.log_event("Spotify client not initialized. Attempting to authenticate...")
            if not bot_instance.authenticate_spotify():
                bot_instance.log_event("ERROR: Could not authenticate with Spotify. Skipping force check.")
                return
        bot_instance.process_main_cycle()
        bot_instance.update_next_check_time()
    bot_instance.log_event("Admin: Manual force check triggered via web.")
    threading.Thread(target=do_force_check).start()
    return "Track check started in background. Check logs for progress."

@app.route('/admin/send_debug_log', methods=['POST'])
def admin_send_debug_log():
    """Emails the full app.log to the configured EMAIL_RECIPIENT."""
    try:
        with open('app.log', 'r', encoding='utf-8') as f:
            log_content = f.read()
        subject = f"[RadioX Spotify] Debug Log ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        msg = MIMEMultipart()
        msg['From'] = EMAIL_HOST_USER
        msg['To'] = EMAIL_RECIPIENT
        msg['Subject'] = subject
        body = MIMEText("Debug log attached.", 'plain')
        msg.attach(body)
        attachment = MIMEText(log_content, 'plain')
        attachment.add_header('Content-Disposition', 'attachment', filename='app.log')
        msg.attach(attachment)
        with smtplib.SMTP(EMAIL_HOST, int(EMAIL_PORT)) as server:
            server.starttls()
            server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
            server.sendmail(EMAIL_HOST_USER, EMAIL_RECIPIENT, msg.as_string())
        return "Debug log emailed successfully."
    except Exception as e:
        logging.error(f"Failed to send debug log: {e}")
        return f"Failed to send debug log: {e}", 500

@app.route('/admin/state_history', methods=['GET'])
def admin_state_history():
    """Return the recent service state transition history for admin review."""
    return jsonify({
        'state_history': list(bot_instance.state_history)
    })

@app.route('/admin/pause', methods=['POST'])
def admin_pause():
    """Pause the service."""
    if bot_instance.service_state == ServiceState.PLAYING:
        bot_instance.set_service_state(ServiceState.PAUSED, "Admin pause")
        bot_instance.log_event("Admin: Service paused via web override.")
        return "Service paused."
    return "Service already paused."

@app.route('/admin/resume', methods=['POST'])
def admin_resume():
    """Resume the service and trigger an immediate check."""
    if bot_instance.service_state == ServiceState.PAUSED:
        bot_instance.set_service_state(ServiceState.PLAYING, "Admin resume")
        bot_instance.log_event("Admin: Service resumed via web override.")
        # Trigger a check immediately
        threading.Thread(target=bot_instance.process_main_cycle).start()
        return "Service resumed."
    return "Service already running."

@app.route('/admin/stats')
def admin_stats():
    """Return detailed admin statistics."""
    try:
        # Get current time in local timezone
        now = datetime.datetime.now(pytz.timezone(TIMEZONE))
        seven_days_ago = now - datetime.timedelta(days=7)
        
        # Get daily stats
        daily_added = get_daily_added()
        daily_failed = get_daily_failed()
        
        # Convert string/float/int timestamps to datetime objects for comparison
        def parse_timestamp(ts):
            try:
                if isinstance(ts, str):
                    ts = float(ts)
                return datetime.datetime.fromtimestamp(ts, pytz.timezone(TIMEZONE))
            except Exception:
                return datetime.datetime.min.replace(tzinfo=pytz.timezone(TIMEZONE))
        
        songs_last_week = [
            song for song in daily_added 
            if parse_timestamp(song.get('timestamp', 0)) > seven_days_ago
        ]
        
        failed_last_week = [
            song for song in daily_failed 
            if parse_timestamp(song.get('timestamp', 0)) > seven_days_ago
        ]
        
        # Compute stats for frontend
        artist_counts = Counter(item['radio_artist'] for item in daily_added)
        most_common = artist_counts.most_common(3)
        top_artists = ", ".join([f"{artist} ({count})" for artist, count in most_common]) if most_common else "N/A"
        unique_artists = len(artist_counts)
        failure_reasons = Counter(item['reason'] for item in daily_failed)
        most_common_failure = failure_reasons.most_common(1)[0][0] if failure_reasons else "N/A"
        total_processed = len(daily_added) + len(daily_failed)
        success_rate = (len(daily_added) / total_processed * 100) if total_processed > 0 else 100
        
        # Calculate average songs per day (based on last 7 days)
        songs_last_week_count = len(songs_last_week)
        average_songs_per_day = songs_last_week_count / 7 if songs_last_week_count > 0 else 0
        
        # Calculate song insights
        song_durations = []
        song_years = []
        newest_song = None
        oldest_song = None
        
        for song in daily_added:
            if 'duration_ms' in song:
                song_durations.append(song['duration_ms'] / 1000)  # Convert to seconds
            if 'year' in song:
                year = int(song['year'])
                song_years.append(year)
                if not newest_song or year > int(newest_song['year']):
                    newest_song = song
                if not oldest_song or year < int(oldest_song['year']):
                    oldest_song = song
        
        # Calculate decade spread
        decade_counts = Counter()
        for year in song_years:
            decade = (year // 10) * 10
            decade_counts[decade] += 1
        
        total_songs = len(song_years)
        decade_spread = {
            f"{decade}s": round((count / total_songs * 100) if total_songs > 0 else 0, 1)
            for decade, count in decade_counts.items()
        }
        
        stats = {
            'total_songs_added': len(daily_added),
            'total_failures': len(daily_failed),
            'success_rate': round(success_rate, 1),
            'average_songs_per_day': round(average_songs_per_day, 1),
            'most_common_artist': top_artists,
            'unique_artists': unique_artists,
            'most_common_failure': most_common_failure,
            'average_duration': round(sum(song_durations) / len(song_durations)) if song_durations else None,
            'decade_spread': decade_spread,
            'newest_song': newest_song,
            'oldest_song': oldest_song,
            'last_check_time': now.strftime('%H:%M:%S'),
            'next_check_time': (now + datetime.timedelta(seconds=CHECK_INTERVAL)).strftime('%H:%M:%S')
        }
        
        return jsonify({
            'stats': stats,
            'daily_failed': daily_failed
        })
    except Exception as e:
        logging.error(f"Error reading state for /admin/stats endpoint: {e}")
        return jsonify({
            'stats': {},
            'daily_failed': []
        }), 500

def start_background_tasks():
    """Start background tasks in a non-daemon thread"""
    def run_bot():
        try:
            bot_instance.authenticate_spotify()
            bot_instance.load_state()
            bot_instance.run_startup_diagnostics(send_email=False)
            bot_instance.run()
        except Exception as e:
            logging.error(f"Error in background bot thread: {e}")
            # Attempt to restart the thread after a delay
            time.sleep(60)
            start_background_tasks()

    thread = threading.Thread(target=run_bot, daemon=False)
    thread.start()
    logging.info("Started background bot thread")

# Start background tasks when the app starts
start_background_tasks()

# --- Script Execution ---
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def get_daily_added():
    try:
        with open('.cache/daily_added.json', 'r') as f:
            return json.load(f)
    except Exception:
        return []

def get_daily_failed():
    try:
        with open('.cache/daily_failed.json', 'r') as f:
            return json.load(f)
    except Exception:
        return []
