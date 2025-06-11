# Radio X to Spotify Playlist Adder
# v6.0 - Full Featured with Interactive Controls and Enhanced Stats
# Includes: Startup diagnostics, class-based structure, time-windowed operation, 
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
        self.paused = False # For Pause/Resume feature

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

    # --- Persistent State Management ---
    def save_state(self):
        """Saves the queues and daily summaries to disk."""
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
        """Loads the queues and daily summaries from disk on startup."""
        with self.file_lock:
            try:
                if os.path.exists(self.RECENTLY_ADDED_CACHE_FILE):
                    with open(self.RECENTLY_ADDED_CACHE_FILE, 'r') as f: self.RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=200)
                if os.path.exists(self.FAILED_QUEUE_CACHE_FILE):
                    with open(self.FAILED_QUEUE_CACHE_FILE, 'r') as f: self.failed_search_queue = deque(json.load(f), maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
                if os.path.exists(self.DAILY_ADDED_CACHE_FILE):
                    with open(self.DAILY_ADDED_CACHE_FILE, 'r') as f: self.daily_added_songs = json.load(f)
                if os.path.exists(self.DAILY_FAILED_CACHE_FILE):
                    with open(self.DAILY_FAILED_CACHE_FILE, 'r') as f: self.daily_search_failures = json.load(f)
                logging.info("Loaded state from cache files.")
            except Exception as e:
                logging.error(f"Failed to load state from disk: {e}")

    # --- Authentication ---
    def authenticate_spotify(self):
        """Initializes and authenticates the Spotipy client."""
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
            self.sp = None
            logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
        return False
    
    # --- API Wrappers and Helpers ---
    # ... (spotify_api_call_with_retry, get_station_herald_id, etc. remain the same) ...

    # --- Main Application Loop ---
    def run(self):
        self.log_event("--- run_radio_monitor thread initiated. ---")
        if not self.sp: self.log_event("ERROR: Spotify client is None. Thread cannot perform Spotify actions."); return
        if self.last_summary_log_date is None: self.last_summary_log_date = datetime.date.today()
        while True:
            try:
                self.check_for_commands() # New step: check for commands from UI
                self.check_and_reset_daily_state()
                
                if self.paused:
                    self.log_event("Script is paused. Skipping main cycle.")
                    time.sleep(CHECK_INTERVAL)
                    continue

                if not self.is_in_active_hours():
                    self.handle_inactive_period()
                    continue
                
                self.process_main_cycle()

            except Exception as e: logging.error(f"CRITICAL UNHANDLED ERROR in main loop: {e}", exc_info=True); time.sleep(CHECK_INTERVAL * 2) 
            self.log_event(f"Cycle complete. Waiting {CHECK_INTERVAL}s..."); time.sleep(CHECK_INTERVAL)

    def process_main_cycle(self):
        # ... (This function remains largely the same, but will now check a skip_id) ...
        # Check for a skip command at the start of the cycle
        skip_file_path = os.path.join(self.CACHE_DIR, 'skip.cmd')
        song_to_skip = None
        if os.path.exists(skip_file_path):
            with open(skip_file_path, 'r') as f:
                song_to_skip = f.read().strip()
            os.remove(skip_file_path)
            self.log_event(f"Received command to skip song ID: {song_to_skip}")

        # ... (rest of the song processing logic) ...
        current_song_info = self.get_current_radiox_song(self.current_station_herald_id)
        self.last_detected_song = current_song_info # Update for UI

        if current_song_info and current_song_info["id"] == song_to_skip:
            self.log_event(f"Skipping song '{current_song_info['title']}' as requested by user.")
            self.last_added_radiox_track_id = current_song_info["id"] # Mark as processed to prevent re-adding
            return
        
        # ... (the rest of the song adding logic) ...
        if current_song_info and current_song_info.get("title"):
            # ... (as before) ...
    
    def check_for_commands(self):
        """Checks for command files created by the web UI."""
        pause_cmd = os.path.join(self.CACHE_DIR, 'pause.cmd')
        resume_cmd = os.path.join(self.CACHE_DIR, 'resume.cmd')
        
        if os.path.exists(pause_cmd):
            self.paused = True
            self.log_event("Received pause command from web UI.")
            os.remove(pause_cmd)

        if os.path.exists(resume_cmd):
            self.paused = False
            self.log_event("Received resume command from web UI.")
            os.remove(resume_cmd)
            
# --- Flask Routes & Script Execution ---
bot_instance = RadioXBot()
atexit.register(bot_instance.save_state)

# ... (force_duplicates and force_queue now use the command file method) ...
@app.route('/force_duplicates')
def force_duplicates():
    bot_instance.log_event("Duplicate check manually triggered via web.")
    with open(os.path.join(bot_instance.CACHE_DIR, 'force_duplicates.cmd'), 'w') as f:
        f.write('1')
    return "Duplicate check command has been sent. It will run on the next cycle."

# ... (new routes for new controls) ...
@app.route('/toggle_pause')
def toggle_pause():
    if bot_instance.paused:
        with open(os.path.join(bot_instance.CACHE_DIR, 'resume.cmd'), 'w') as f: f.write('1')
        return "Resume command sent."
    else:
        with open(os.path.join(bot_instance.CACHE_DIR, 'pause.cmd'), 'w') as f: f.write('1')
        return "Pause command sent."

@app.route('/skip_song', methods=['POST'])
def skip_song():
    song_id = request.form.get('song_id')
    if song_id:
        with open(os.path.join(bot_instance.CACHE_DIR, 'skip.cmd'), 'w') as f:
            f.write(song_id)
        return f"Skip command sent for song ID: {song_id}"
    return "No song ID provided.", 400

@app.route('/email_summary')
def email_summary():
    bot_instance.log_event("Manual daily summary triggered via web.")
    threading.Thread(target=bot_instance.log_and_send_daily_summary).start()
    return "Daily summary generation and email has been triggered."

@app.route('/status')
def status():
    # Corrected: reads directly from cache files for UI consistency
    try:
        with bot_instance.file_lock:
            with open(bot_instance.DAILY_ADDED_CACHE_FILE, 'r') as f: daily_added = json.load(f)
            with open(bot_instance.DAILY_FAILED_CACHE_FILE, 'r') as f: daily_failed = json.load(f)
            with open(bot_instance.FAILED_QUEUE_CACHE_FILE, 'r') as f: failed_queue = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        daily_added, daily_failed, failed_queue = [], [], []

    return jsonify({
        'last_detected_song': bot_instance.last_detected_song,
        'queue_size': len(failed_queue),
        'failed_queue': list(failed_queue),
        'daily_added': daily_added,
        'daily_failed': daily_failed,
        'is_paused': bot_instance.paused,
    })

# ... (index_page and main execution logic) ...
@app.route('/')
def index_page():
    return render_template('index.html', active_hours=f"{START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}")
