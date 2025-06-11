# Radio X to Spotify Playlist Adder
# v6.1 - Final with All Features and Corrected Startup Logic
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
from flask import Flask, jsonify, render_template
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
                if user: self.log_event(f"Successfully authenticated with Spotify as {user['display_name']}."); return True
                else: self.sp = None; self.log_event("ERROR: Could not get Spotify user details with token.")
            else: self.sp = None; self.log_event("ERROR: Failed to obtain Spotify token.")
        except Exception as e:
            self.sp = None; logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
        return False
    
    # --- API Wrappers and Helpers ---
    def spotify_api_call_with_retry(self, func, *args, **kwargs):
        # ... same logic as before ...
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
                    retry_after = int(e.headers.get('Retry-After', base_delay * (2**attempt)))
                    logging.info(f"Rate limited. Retrying after {retry_after}s..."); time.sleep(retry_after)
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
            for brand in brands_data:
                if brand.get('brandSlug', '').lower() == station_slug_to_find:
                    self.herald_id_cache[station_slug_to_find] = brand.get('heraldId'); return brand.get('heraldId')
        except Exception as e: self.log_event(f"ERROR: Error fetching brands: {e}")
        return None

    def get_current_radiox_song(self, station_herald_id):
        if not station_herald_id: return None
        ws = None
        try:
            ws = websocket.create_connection("wss://metadata.musicradio.com/v2/now-playing", timeout=10)
            ws.send(json.dumps({"actions": [{"type": "subscribe", "service": str(station_herald_id)}]}))
            for _ in range(3):
                raw_message = ws.recv()
                if raw_message:
                    message_data = json.loads(raw_message)
                    if message_data.get('now_playing', {}).get('type') == 'track':
                        now_playing = message_data['now_playing']
                        title, artist = now_playing.get('title'), now_playing.get('artist')
                        if title and artist:
                            return {"title": title.strip(), "artist": artist.strip(), "id": now_playing.get('id') or f"{station_herald_id}_{title}_{artist}".replace(" ", "_")}
            return None
        except Exception as e: logging.error(f"WebSocket error: {e}", exc_info=True)
        finally:
            if ws:
                try: ws.close()
                except: pass
        return None

    def search_song_on_spotify(self, original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
        if not self.sp: return None
        def _attempt(title, desc):
            try:
                results = self.spotify_api_call_with_retry(self.sp.search, q=f"track:{title} artist:{artist}", type="track", limit=1)
                if results and results["tracks"]["items"]: return results["tracks"]["items"][0]["id"]
            except Exception: pass
            return None

        spotify_id = _attempt(original_title, "original")
        if spotify_id: return spotify_id
        
        cleaned_paren = re.sub(r'\s*\(.*?\)\s*', ' ', original_title).strip()
        if cleaned_paren.lower() != original_title.lower():
            spotify_id = _attempt(cleaned_paren, "parentheses removed")
            if spotify_id: return spotify_id

        cleaned_feat = re.sub(r'\s*\[.*?\]\s*|feat\..*', ' ', original_title, flags=re.IGNORECASE).strip()
        if cleaned_feat.lower() != original_title.lower() and cleaned_feat.lower() != cleaned_paren.lower():
            spotify_id = _attempt(cleaned_feat, "features removed")
            if spotify_id: return spotify_id
        
        self.log_event(f"FAIL: Song '{original_title}' not found.")
        if not is_retry_from_queue: self.daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify"})
        return None
    
    # ... all other class methods here, they are mostly unchanged ...
    # (The full script is in the canvas)

# --- Flask Routes & Script Execution ---
bot_instance = RadioXBot()
atexit.register(bot_instance.save_state)

@app.route('/force_duplicates')
def force_duplicates():
    bot_instance.log_event("Duplicate check manually triggered via web.")
    with open(os.path.join(bot_instance.CACHE_DIR, 'force_duplicates.cmd'), 'w') as f: f.write('1')
    return "Duplicate check command sent. It will run on the next cycle."

# ... (other routes like force_queue, email_summary, toggle_pause, skip_song) ...

@app.route('/status')
def status():
    """Reads the current state from cache files and returns it as JSON."""
    try:
        with bot_instance.file_lock:
            with open(bot_instance.STATUS_CACHE_FILE, 'r') as f: data = json.load(f)
            return jsonify(data)
    except (FileNotFoundError, json.JSONDecodeError):
        # Return a default empty state if files don't exist yet
        return jsonify({
            'last_detected_song': None,
            'queue_size': 0,
            'failed_queue': [],
            'daily_added': [],
            'daily_failed': [],
            'is_paused': False,
            'log': list(bot_instance.event_log) # Use in-memory log as a fallback
        })

@app.route('/')
def index_page():
    return render_template('index.html', active_hours=f"{START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}")

def initialize_and_run_bot():
    """Handles the slow startup tasks and then runs the main loop."""
    bot_instance.log_event("Background initialization started.")
    if bot_instance.authenticate_spotify():
        bot_instance.load_state() 
        bot_instance.run_startup_diagnostics()
        bot_instance.run()
    else:
        bot_instance.log_event("CRITICAL: Spotify authentication failed. Monitoring thread will not start.")

# --- Script Execution ---
if __name__ == "__main__":
    # Local development startup
    threading.Thread(target=initialize_and_run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
else:
    # Gunicorn startup
    threading.Thread(target=initialize_and_run_bot, daemon=True).start()
