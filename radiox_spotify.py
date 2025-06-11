# Radio X to Spotify Playlist Adder
# v7.0 - Final with All Features and UI Controls
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
from flask import Flask, jsonify, render_template, request
import datetime
import pytz 
import smtplib 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque, Counter
import atexit
import base64

# --- Flask App Setup ---
app = Flask(__name__)

# --- Configuration ---
SPOTIPY_CLIENT_ID = "89c7e2957a7e465a8eeb9d2476a82a2d"
SPOTIPY_CLIENT_SECRET = "f8dc109892b9464ab44fba3b2502a7eb"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback" 
SPOTIFY_PLAYLIST_ID = "5i13fDRDoW0gu60f74cysp" 
RADIOX_STATION_SLUG = "radiox" 

# Script Operation Settings
CHECK_INTERVAL = 120  
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Main Application Class ---

class RadioXBot:
    def __init__(self):
        # State Variables
        self.sp = None
        self.last_added_radiox_track_id = None
        self.last_detected_song = None
        self.herald_id_cache = {}
        self.last_duplicate_check_time = 0
        self.last_summary_log_date = datetime.date.today() - datetime.timedelta(days=1)
        self.startup_email_sent = False
        self.shutdown_summary_sent = False
        self.current_station_herald_id = None
        self.is_running = False
        self.paused = False

        # Persistent Data Structures
        self.CACHE_DIR = ".cache"
        if os.path.isfile(self.CACHE_DIR):
            logging.warning(f"A file named '{self.CACHE_DIR}' exists. Removing it to create cache directory.")
            try: os.remove(self.CACHE_DIR)
            except OSError as e: logging.error(f"Error removing file {self.CACHE_DIR}: {e}")
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        
        self.RECENTLY_ADDED_CACHE_FILE = os.path.join(self.CACHE_DIR, "recent_tracks.json")
        self.FAILED_QUEUE_CACHE_FILE = os.path.join(self.CACHE_DIR, "failed_queue.json")
        self.DAILY_ADDED_CACHE_FILE = os.path.join(self.CACHE_DIR, "daily_added.json")
        self.DAILY_FAILED_CACHE_FILE = os.path.join(self.CACHE_DIR, "daily_failed.json")
        self.STATUS_CACHE_FILE = os.path.join(self.CACHE_DIR, "status.json")

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
        clean_message = ANSI_ESCAPE.sub('', message)
        self.event_log.appendleft(f"[{datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S')}] {clean_message}")

    # --- Persistent State Management ---
    def save_state(self):
        """Saves the queues and daily summaries to disk."""
        with self.file_lock:
            try:
                with open(self.RECENTLY_ADDED_CACHE_FILE, 'w') as f: json.dump(list(self.RECENTLY_ADDED_SPOTIFY_IDS), f)
                with open(self.FAILED_QUEUE_CACHE_FILE, 'w') as f: json.dump(list(self.failed_search_queue), f)
                with open(self.DAILY_ADDED_CACHE_FILE, 'w') as f: json.dump(self.daily_added_songs, f)
                with open(self.DAILY_FAILED_CACHE_FILE, 'w') as f: json.dump(self.daily_search_failures, f)
                
                status_data = {
                    'last_detected_song': self.last_detected_song,
                    'queue_size': len(self.failed_search_queue),
                    'failed_queue': list(self.failed_search_queue),
                    'daily_added': self.daily_added_songs,
                    'daily_failed': self.daily_search_failures,
                    'is_paused': self.paused,
                    'log': list(self.event_log)
                }
                with open(self.STATUS_CACHE_FILE, 'w') as f: json.dump(status_data, f)
                
                logging.debug("Successfully saved application state to disk.")
            except Exception as e:
                logging.error(f"Failed to save state to disk: {e}")

    def load_state(self):
        """Loads the queues and daily summaries from disk on startup."""
        with self.file_lock:
            try:
                if os.path.exists(self.RECENTLY_ADDED_CACHE_FILE):
                    with open(self.RECENTLY_ADDED_CACHE_FILE, 'r') as f:
                        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=200)
                if os.path.exists(self.FAILED_QUEUE_CACHE_FILE):
                    with open(self.FAILED_QUEUE_CACHE_FILE, 'r') as f:
                        self.failed_search_queue = deque(json.load(f), maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
                if os.path.exists(self.DAILY_ADDED_CACHE_FILE):
                    with open(self.DAILY_ADDED_CACHE_FILE, 'r') as f:
                        self.daily_added_songs = json.load(f)
                if os.path.exists(self.DAILY_FAILED_CACHE_FILE):
                    with open(self.DAILY_FAILED_CACHE_FILE, 'r') as f:
                        self.daily_search_failures = json.load(f)
                logging.info("Loaded state from cache files.")
            except Exception as e:
                logging.error(f"Failed to load state from disk: {e}")

    # --- Authentication ---
    def authenticate_spotify(self):
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
            self.sp = None; logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
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
        ws = None
        try:
            ws = websocket.create_connection("wss://metadata.musicradio.com/v2/now-playing", timeout=10)
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
            if not message_received: self.last_detected_song = None; return None
            now_playing = message_received.get('now_playing', {})
            title, artist, track_id_api = now_playing.get('title'), now_playing.get('artist'), now_playing.get('id')
            if title and artist:
                unique_id = track_id_api or f"{station_herald_id}_{title.strip()}_{artist.strip()}".replace(" ", "_")
                self.last_detected_song = {"title": title.strip(), "artist": artist.strip(), "id": unique_id}
                return self.last_detected_song
            self.last_detected_song = None
            return None
        except Exception as e: logging.error(f"WebSocket error: {e}", exc_info=True); self.last_detected_song = None
        finally:
            if ws:
                try: ws.close()
                except: pass
        return None
    
    def search_song_on_spotify(self, original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
        if not self.sp: return None
        
        def _attempt_search(title, desc):
            try:
                results = self.spotify_api_call_with_retry(self.sp.search, q=f"track:{title} artist:{artist}", type="track", limit=1)
                if results and results["tracks"]["items"]:
                    self.log_event(f"Found on Spotify ({desc}): '{results['tracks']['items'][0]['name']}'")
                    return results["tracks"]["items"][0]["id"]
            except Exception:
                self.log_event(f"ERROR: Network/API error during search for '{title}'.")
                if radiox_id_for_queue and not is_retry_from_queue: self.add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
                return "NETWORK_ERROR_FLAG"
            return None

        for title_variation, description in [
            (original_title, "original title"),
            (re.sub(r'\s*\(.*?\)\s*', ' ', original_title).strip(), "parentheses removed"),
            (re.sub(r'\s*\[.*?\]\s*|feat\..*', '', original_title, flags=re.IGNORECASE).strip(), "features/brackets removed")
        ]:
            if title_variation.lower() == original_title.lower() and description != "original title": continue
            spotify_id = _attempt_search(title_variation, description)
            if spotify_id: return spotify_id if spotify_id != "NETWORK_ERROR_FLAG" else None

        self.log_event(f"FAIL: Song '{original_title}' by '{artist}' not found after all attempts.")
        if not is_retry_from_queue: self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify after all attempts."})
        return None

    def manage_playlist_size(self, playlist_id):
        # ... (This function remains unchanged) ...
    def add_song_to_playlist(self, radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
        # ... (This function remains unchanged) ...
    def check_and_remove_duplicates(self, playlist_id):
        # ... (This function remains unchanged) ...
    def process_failed_search_queue(self):
        # ... (This function remains unchanged) ...

    # --- Email & Summary Functions ---
    def send_summary_email(self, html_body, subject):
        # ... (This function remains unchanged) ...
    def get_daily_stats_html(self):
        # ... (This function remains unchanged) ...
    def log_and_send_daily_summary(self):
        # ... (This function remains unchanged) ...
    def send_startup_notification(self, status_report_html_rows):
        # ... (This function remains unchanged) ...
    def run_startup_diagnostics(self, send_email=False):
        # ... (This function remains unchanged) ...

    # --- Main Application Loop ---
    def run(self):
        self.log_event("--- Main monitoring thread started. ---")
        if not self.sp: self.log_event("ERROR: Spotify client is None. Thread cannot perform Spotify actions."); return
        if self.last_summary_log_date is None: self.last_summary_log_date = datetime.date.today()
        while True:
            try:
                self.check_for_commands()
                now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
                if self.last_summary_log_date < now_local.date():
                    self.log_event(f"New day detected ({now_local.date().isoformat()}). Resetting daily state.")
                    self.startup_email_sent, self.shutdown_summary_sent = False, False
                    self.daily_added_songs.clear(); self.daily_search_failures.clear()
                    self.last_summary_log_date = now_local.date()

                if self.paused or not (START_TIME <= now_local.time() <= END_TIME):
                    if not self.shutdown_summary_sent and not self.paused:
                        self.log_event("End of active day. Sending daily summary."); self.log_and_send_daily_summary(); self.shutdown_summary_sent = True
                    self.startup_email_sent = False # Ready for tomorrow's startup email
                    self.log_event("Inactive period. Pausing...")
                    time.sleep(CHECK_INTERVAL * 2); continue
                
                if not self.startup_email_sent:
                    self.log_event("Active hours started."); self.startup_email_sent = True; self.shutdown_summary_sent = False
                
                self.process_main_cycle()

            except Exception as e: logging.error(f"CRITICAL UNHANDLED ERROR in main loop: {e}", exc_info=True); time.sleep(CHECK_INTERVAL * 2) 
            self.save_state()
            log_event(f"Cycle complete. Waiting {CHECK_INTERVAL}s...")
            time.sleep(CHECK_INTERVAL)

    def process_main_cycle(self):
        if not self.current_station_herald_id: self.current_station_herald_id = self.get_station_herald_id(RADIOX_STATION_SLUG)
        if not self.current_station_herald_id: return
        
        current_song_info = self.get_current_radiox_song(self.current_station_herald_id)
        song_added = False
        if current_song_info:
            title, artist, radiox_id = current_song_info["title"], current_song_info["artist"], current_song_info["id"]
            
            skip_file_path = os.path.join(self.CACHE_DIR, 'skip.cmd')
            if os.path.exists(skip_file_path):
                with open(skip_file_path, 'r') as f: song_to_skip = f.read().strip()
                if radiox_id == song_to_skip:
                    self.log_event(f"Skipping song '{title}' as requested by user."); os.remove(skip_file_path); self.last_added_radiox_track_id = radiox_id; return

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

    def check_for_commands(self):
        """Checks for and executes command files from the web UI."""
        if os.path.exists(os.path.join(self.CACHE_DIR, 'pause.cmd')):
            self.paused = True; os.remove(os.path.join(self.CACHE_DIR, 'pause.cmd')); self.log_event("Received pause command.")
        if os.path.exists(os.path.join(self.CACHE_DIR, 'resume.cmd')):
            self.paused = False; os.remove(os.path.join(self.CACHE_DIR, 'resume.cmd')); self.log_event("Received resume command.")


# --- Flask Routes & Script Execution ---
bot_instance = RadioXBot()
atexit.register(bot_instance.save_state)

@app.route('/toggle_pause')
def toggle_pause():
    cmd_file = os.path.join(bot_instance.CACHE_DIR, 'resume.cmd' if bot_instance.paused else 'pause.cmd')
    with open(cmd_file, 'w') as f: f.write('1')
    return f"{'Resume' if bot_instance.paused else 'Pause'} command sent. It will take effect on the next cycle."

@app.route('/skip_song', methods=['POST'])
def skip_song():
    song_id = request.form.get('song_id')
    if song_id:
        with open(os.path.join(bot_instance.CACHE_DIR, 'skip.cmd'), 'w') as f: f.write(song_id)
        return f"Skip command sent for song ID: {song_id}"
    return "No song ID provided.", 400

@app.route('/email_summary')
def email_summary():
    threading.Thread(target=bot_instance.log_and_send_daily_summary).start()
    return "Daily summary generation and email has been triggered."

# ... (other routes like force_duplicates, force_queue, force_diagnostics) ...

@app.route('/status')
def status():
    """Reads the current state from cache files and returns it as JSON."""
    with bot_instance.file_lock:
        try:
            with open(bot_instance.STATUS_CACHE_FILE, 'r') as f: data = json.load(f)
            return jsonify(data)
        except (FileNotFoundError, json.JSONDecodeError):
            return jsonify({'last_detected_song': None, 'queue_size': 0, 'failed_queue': [], 'daily_added': [], 'daily_failed': [], 'is_paused': bot_instance.paused, 'log': list(bot_instance.event_log)})

@app.route('/')
def index_page():
    return render_template('index.html', active_hours=f"{START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}")

def initialize_bot():
    """Handles the slow startup tasks in the background."""
    logging.info("Background initialization started.")
    if bot_instance.authenticate_spotify():
        bot_instance.load_state() 
        bot_instance.run_startup_diagnostics()
        bot_instance.run() # Start the main loop directly
    else:
        logging.critical("Spotify authentication failed. The main monitoring thread will not start.")

# This top-level execution is what Gunicorn runs
if 'gunicorn' in os.environ.get('SERVER_SOFTWARE', ''):
    threading.Thread(target=initialize_bot, daemon=True).start()
