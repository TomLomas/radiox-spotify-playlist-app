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
from flask import Flask, jsonify, render_template, Response, request
import datetime
import pytz 
import smtplib 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from collections import deque, Counter
import atexit
import base64
from dotenv import load_dotenv
from flask_sse import sse
import redis
import sys
import logging.handlers

try:
    import psutil
except ImportError:
    psutil = None

# --- NEW: Smart Search Strategy Class ---
class SmartSearchStrategy:
    def __init__(self):
        self.artist_success_patterns = {}
        self.search_strategy_weights = {
            'original': 1.0,
            'no_parentheses': 0.8,
            'no_features': 0.6
        }
        self.load_patterns()
    
    def load_patterns(self):
        """Load artist success patterns from cache."""
        try:
            if os.path.exists('.cache/artist_patterns.json'):
                with open('.cache/artist_patterns.json', 'r') as f:
                    self.artist_success_patterns = json.load(f)
        except Exception as e:
            logging.warning(f"Could not load artist patterns: {e}")
    
    def save_patterns(self):
        """Save artist success patterns to cache."""
        try:
            os.makedirs('.cache', exist_ok=True)
            with open('.cache/artist_patterns.json', 'w') as f:
                json.dump(self.artist_success_patterns, f)
        except Exception as e:
            logging.warning(f"Could not save artist patterns: {e}")
    
    def get_optimal_search_order(self, artist, title):
        """Return search strategies in order of likely success for this artist."""
        artist_lower = artist.lower()
        
        # Check if we have patterns for this artist
        if artist_lower in self.artist_success_patterns:
            patterns = self.artist_success_patterns[artist_lower]
            # Sort by success rate
            sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)
            return [pattern[0] for pattern in sorted_patterns]
        
        # Default order for new artists
        return ['original', 'no_parentheses', 'no_features']
    
    def update_success_rate(self, artist, strategy, success):
        """Update success rate for an artist's search strategy."""
        artist_lower = artist.lower()
        
        if artist_lower not in self.artist_success_patterns:
            self.artist_success_patterns[artist_lower] = {
                'original': 0.5,
                'no_parentheses': 0.5,
                'no_features': 0.5
            }
        
        # Update with exponential moving average
        current_rate = self.artist_success_patterns[artist_lower].get(strategy, 0.5)
        new_rate = current_rate * 0.9 + (1.0 if success else 0.0) * 0.1
        self.artist_success_patterns[artist_lower][strategy] = new_rate
        
        # Save patterns periodically
        if time.time() % 300 < 1:  # Save every 5 minutes
            self.save_patterns()

# --- NEW: Real-Time WebSocket Listener ---
class RealTimeWebSocketListener:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.websocket = None
        self.is_running = False
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        
    def start_listening(self):
        """Start the real-time WebSocket listener."""
        if not self.bot.sp:
            logging.warning("Cannot start WebSocket listener - Spotify client not available")
            return
            
        self.is_running = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        logging.info("Real-time WebSocket listener started")
    
    def stop_listening(self):
        """Stop the real-time WebSocket listener."""
        self.is_running = False
        if self.websocket:
            try:
                self.websocket.close()
            except:
                pass
        logging.info("Real-time WebSocket listener stopped")
    
    def _listen_loop(self):
        """Main listening loop with automatic reconnection."""
        while self.is_running:
            try:
                self._connect_and_listen()
            except Exception as e:
                logging.error(f"WebSocket listener error: {e}")
                if self.is_running:
                    time.sleep(self.reconnect_delay)
                    self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
    
    def _connect_and_listen(self):
        """Connect to WebSocket and listen for song changes."""
        if not self.bot.current_station_herald_id:
            logging.debug("WebSocket listener waiting for station herald ID...")
            time.sleep(5)
            return
        
        websocket_url = "wss://metadata.musicradio.com/v2/now-playing"
        logging.info(f"Connecting to real-time WebSocket: {websocket_url}")
        
        self.websocket = websocket.create_connection(websocket_url, timeout=10)
        self.websocket.send(json.dumps({
            "actions": [{"type": "subscribe", "service": str(self.bot.current_station_herald_id)}]
        }))
        
        self.reconnect_delay = 5  # Reset reconnect delay on successful connection
        
        while self.is_running:
            try:
                raw_message = self.websocket.recv()
                if raw_message:
                    self._handle_message(raw_message)
            except websocket.WebSocketTimeoutException:
                continue  # Just continue listening
            except Exception as e:
                logging.error(f"WebSocket message error: {e}")
                break
    
    def _handle_message(self, raw_message):
        """Handle incoming WebSocket messages."""
        try:
            message_data = json.loads(raw_message)
            
            # Handle heartbeat
            if message_data.get('type') == 'heartbeat':
                return
            
            # Handle song change
            if message_data.get('now_playing') and message_data['now_playing'].get('type') == 'track':
                now_playing = message_data['now_playing']
                title, artist, track_id_api = now_playing.get('title'), now_playing.get('artist'), now_playing.get('id')
                
                if title and artist:
                    title, artist = title.strip(), artist.strip()
                    if title and artist:
                        unique_id = track_id_api or f"{self.bot.current_station_herald_id}_{title}_{artist}".replace(" ", "_")
                        
                        # Check if this is a new song
                        if unique_id != self.bot.last_added_radiox_track_id:
                            self.bot.log_event(f"🔄 REAL-TIME: New song detected: {title} by {artist}")
                            self.bot.activity_tracker.add_activity(
                                'song_detected',
                                f"Real-time: New song detected: {title} by {artist}",
                                success=None,
                                details={"title": title, "artist": artist}
                            )
                            # Process the song immediately
                            self._process_song_immediately(title, artist, unique_id)
                        else:
                            logging.debug(f"🔄 REAL-TIME: Same song still playing: {title} by {artist}")
            
        except Exception as e:
            logging.error(f"Error handling WebSocket message: {e}")
    
    def _process_song_immediately(self, title, artist, radiox_id):
        """Process a new song immediately when detected."""
        try:
            # Check if we're within active hours
            now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
            if not (START_TIME <= now_local.time() <= END_TIME):
                self.bot.log_event(f"⏰ REAL-TIME: Skipping '{title}' by '{artist}' - outside active hours ({START_TIME.strftime('%H:%M')}-{END_TIME.strftime('%H:%M')})")
                self.bot.activity_tracker.add_activity(
                    'skipped_out_of_hours',
                    f"Real-time: Skipped '{title}' by '{artist}' - outside active hours",
                    success=None,
                    details={"title": title, "artist": artist, "reason": "outside_active_hours"}
                )
                return
            
            # Use smart search strategy
            spotify_track_id = self.bot.search_song_on_spotify_smart(title, artist, radiox_id)
            
            if spotify_track_id:
                if self.bot.add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID):
                    self.bot.log_event(f"✅ REAL-TIME: Successfully added '{title}' by '{artist}'")
                    self.bot.last_added_radiox_track_id = radiox_id
                    self.bot.activity_tracker.add_activity(
                        'song_added',
                        f"Real-time: Added '{title}' by '{artist}' to playlist",
                        success=True,
                        details={"title": title, "artist": artist, "spotify_id": spotify_track_id}
                    )
                else:
                    self.bot.log_event(f"❌ REAL-TIME: Failed to add '{title}' by '{artist}' to playlist")
                    self.bot.activity_tracker.add_activity(
                        'add_failed',
                        f"Real-time: Failed to add '{title}' by '{artist}' to playlist",
                        success=False,
                        details={"title": title, "artist": artist, "spotify_id": spotify_track_id}
                    )
            else:
                self.bot.log_event(f"❌ REAL-TIME: Could not find '{title}' by '{artist}' on Spotify")
                self.bot.activity_tracker.add_activity(
                    'search_failed',
                    f"Real-time: Could not find '{title}' by '{artist}' on Spotify",
                    success=False,
                    details={"title": title, "artist": artist}
                )
                
        except Exception as e:
            logging.error(f"Error processing song immediately: {e}")
            self.bot.log_event(f"❌ REAL-TIME: Error processing '{title}' by '{artist}': {e}")
            self.bot.activity_tracker.add_activity(
                'error',
                f"Real-time: Error processing '{title}' by '{artist}': {e}",
                success=False,
                details={"title": title, "artist": artist, "error": str(e)}
            )

# --- NEW: Activity Tracker for Live Dashboard ---
class ActivityTracker:
    def __init__(self, max_activities=50):
        self.activities = deque(maxlen=max_activities)
        self.stats = {
            'total_songs_processed': 0,
            'successful_adds': 0,
            'failed_searches': 0,
            'api_calls': 0,
            'start_time': time.time()
        }
    
    def add_activity(self, activity_type, message, success=None, details=None):
        """Add an activity to the tracker."""
        activity = {
            'timestamp': datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
            'type': activity_type,
            'message': message,
            'success': success,
            'details': details
        }
        
        self.activities.appendleft(activity)
        
        # Update stats
        self.stats['total_songs_processed'] += 1
        if success is True:
            self.stats['successful_adds'] += 1
        elif success is False:
            self.stats['failed_searches'] += 1
        
        # Publish to frontend via SSE
        try:
            with app.app_context():
                sse.publish({
                    "activity": activity,
                    "stats": self.stats
                }, type='activity_update')
        except Exception as e:
            logging.error(f"Failed to publish activity update: {e}")
    
    def get_recent_activities(self, limit=20):
        """Get recent activities for the dashboard."""
        return list(self.activities)[:limit]
    
    def get_stats(self):
        """Get current stats."""
        uptime = time.time() - self.stats['start_time']
        success_rate = (self.stats['successful_adds'] / max(self.stats['total_songs_processed'], 1)) * 100
        
        return {
            **self.stats,
            'uptime_seconds': uptime,
            'uptime_formatted': f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
            'success_rate': f"{success_rate:.1f}%",
            'songs_per_hour': (self.stats['total_songs_processed'] / max(uptime / 3600, 1))
        }

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

# Problematic keywords for filtering
PROBLEM_KEYWORDS = [
    'error', 'fail', 'not found', 'critical', 'exception', 'warning', 'timeout',
    'unable', 'could not', 'refused', 'denied', 'invalid', 'missing', 'unavailable',
    'retry', 'disconnect', 'traceback'
]

# Normal/expected messages to exclude from debug logs
NORMAL_MESSAGES = [
    'websocket timeout'  # These are normal browser reconnection behavior
]

class ProblemLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage().lower()
        
        # First check if it's a normal/expected message to exclude
        if any(normal_msg in msg for normal_msg in NORMAL_MESSAGES):
            return False
            
        # Then check if it contains problematic keywords
        return any(word in msg for word in PROBLEM_KEYWORDS)

log_file = 'radiox_debug.log'

# Clear any existing handlers to avoid conflicts
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Set up logging: all logs to stdout, filtered logs to file
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.INFO)
stdout_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=2)
file_handler.setLevel(logging.WARNING)  # Only warnings and errors to file
file_handler.addFilter(ProblemLogFilter())
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[stdout_handler, file_handler],
    force=True  # Force reconfiguration
)

# Ensure immediate flushing
sys.stdout.flush()
sys.stderr.flush()

# Test logging immediately
logging.info("=== RadioX Spotify Backend Starting ===")
logging.info("Logging system initialized successfully")

BACKEND_VERSION = "2.0.2"

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
        
        # --- NEW: Persistent Daily Cache System ---
        self.DAILY_CACHE_DIR = os.path.join(self.CACHE_DIR, "daily")
        os.makedirs(self.DAILY_CACHE_DIR, exist_ok=True)
        self.current_date = datetime.datetime.now(pytz.timezone(TIMEZONE)).date()
        self.current_daily_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{self.current_date.isoformat()}_added.json")
        self.current_daily_failed_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{self.current_date.isoformat()}_failed.json")

        self.RECENTLY_ADDED_SPOTIFY_IDS = deque(maxlen=20)
        self.failed_search_queue = deque(maxlen=5)
        self.daily_added_songs = [] 
        self.daily_search_failures = [] 
        self.event_log = deque(maxlen=10)

        # --- NEW: Essential Optimizations ---
        self.smart_search = SmartSearchStrategy()
        self.realtime_listener = RealTimeWebSocketListener(self)
        self.activity_tracker = ActivityTracker()

        self.log_event("Application instance created. Waiting for initialization.")
        self.update_service_state('initializing')

        # Note: Real-time listener will be started after initialization is complete

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
        try:
            # Save without blocking - use temporary files then rename
            temp_recently_added = f"{self.RECENTLY_ADDED_CACHE_FILE}.tmp"
            temp_failed_queue = f"{self.FAILED_QUEUE_CACHE_FILE}.tmp"
            
            with open(temp_recently_added, 'w') as f: 
                json.dump(list(self.RECENTLY_ADDED_SPOTIFY_IDS), f)
            with open(temp_failed_queue, 'w') as f: 
                json.dump(list(self.failed_search_queue), f)
            
            # Atomic rename operations
            os.replace(temp_recently_added, self.RECENTLY_ADDED_CACHE_FILE)
            os.replace(temp_failed_queue, self.FAILED_QUEUE_CACHE_FILE)
            
            # Save daily cache using new persistent system
            self.save_daily_cache()
            
            logging.debug("Successfully saved application state to disk.")
        except Exception as e:
            logging.error(f"Failed to save state to disk: {e}")

    def load_state(self):
        """Loads the queues and daily summaries from disk on startup."""
        try:
            # Load without blocking - read files directly
            if os.path.exists(self.RECENTLY_ADDED_CACHE_FILE):
                with open(self.RECENTLY_ADDED_CACHE_FILE, 'r') as f:
                    self.RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=20)
                    logging.info(f"Loaded {len(self.RECENTLY_ADDED_SPOTIFY_IDS)} recent tracks from cache.")
            if os.path.exists(self.FAILED_QUEUE_CACHE_FILE):
                with open(self.FAILED_QUEUE_CACHE_FILE, 'r') as f:
                    self.failed_search_queue = deque(json.load(f), maxlen=5)
                    logging.info(f"Loaded {len(self.failed_search_queue)} failed searches from cache.")
            
            # Load daily cache using new persistent system
            self.load_daily_cache()
            
        except Exception as e:
            logging.error(f"Error in load_state: {e}")
        
        # After loading, immediately calculate stats from the cache
        try:
            self.update_stats()
        except Exception as e:
            logging.error(f"Failed to update stats: {e}")

    def save_last_check_complete_time(self):
        try:
            # Save without blocking - use temporary file then rename
            temp_file = f"{self.LAST_CHECK_COMPLETE_FILE}.tmp"
            with open(temp_file, 'w') as f:
                f.write(str(self.last_check_complete_time))
            # Atomic rename operation
            os.replace(temp_file, self.LAST_CHECK_COMPLETE_FILE)
        except Exception as e:
            logging.error(f"Error saving last check complete time: {e}")

    def load_last_check_complete_time(self):
        try:
            if os.path.exists(self.LAST_CHECK_COMPLETE_FILE):
                with open(self.LAST_CHECK_COMPLETE_FILE, 'r') as f:
                    try:
                        self.last_check_complete_time = int(f.read().strip())
                    except Exception:
                        self.last_check_complete_time = 0
        except Exception as e:
            logging.error(f"Error loading last check complete time: {e}")
            self.last_check_complete_time = 0

    # --- NEW: Persistent Daily Cache Management ---
    def check_and_update_daily_cache(self):
        """Check if we need to roll over to a new day and update cache files accordingly."""
        current_date = datetime.datetime.now(pytz.timezone(TIMEZONE)).date()
        
        if current_date != self.current_date:
            self.log_event(f"🔄 Daily cache rollover: {self.current_date} → {current_date}")
            
            # Save current day's data before switching
            self.save_daily_cache()
            
            # Update to new date
            self.current_date = current_date
            self.current_daily_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{self.current_date.isoformat()}_added.json")
            self.current_daily_failed_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{self.current_date.isoformat()}_failed.json")
            
            # Load new day's data (or start fresh)
            self.load_daily_cache()
            
            # Clean up old cache files (keep last 7 days)
            self.cleanup_old_daily_caches()
    
    def save_daily_cache(self):
        """Save current day's added songs and failures to persistent cache."""
        try:
            # Save without blocking - use temporary files then rename
            temp_added_file = f"{self.current_daily_cache_file}.tmp"
            temp_failed_file = f"{self.current_daily_failed_cache_file}.tmp"
            
            with open(temp_added_file, 'w') as f:
                json.dump(self.daily_added_songs, f, indent=2)
            with open(temp_failed_file, 'w') as f:
                json.dump(self.daily_search_failures, f, indent=2)
            
            # Atomic rename operations
            os.replace(temp_added_file, self.current_daily_cache_file)
            os.replace(temp_failed_file, self.current_daily_failed_cache_file)
            
            logging.debug(f"Saved daily cache for {self.current_date}: {len(self.daily_added_songs)} added, {len(self.daily_search_failures)} failed")
        except Exception as e:
            logging.error(f"Error in save_daily_cache: {e}")
    
    def load_daily_cache(self):
        """Load current day's added songs and failures from persistent cache."""
        try:
            # Load without blocking - read files directly
            # Load added songs
            if os.path.exists(self.current_daily_cache_file):
                with open(self.current_daily_cache_file, 'r') as f:
                    self.daily_added_songs = json.load(f)
                logging.info(f"Loaded {len(self.daily_added_songs)} added songs from daily cache for {self.current_date}")
            else:
                self.daily_added_songs = []
                logging.info(f"Starting fresh daily cache for {self.current_date}")
            
            # Load failed searches
            if os.path.exists(self.current_daily_failed_cache_file):
                with open(self.current_daily_failed_cache_file, 'r') as f:
                    self.daily_search_failures = json.load(f)
                logging.info(f"Loaded {len(self.daily_search_failures)} failed searches from daily cache for {self.current_date}")
            else:
                self.daily_search_failures = []
                logging.info(f"Starting fresh failed searches cache for {self.current_date}")
                
        except Exception as e:
            logging.error(f"Error in load_daily_cache: {e}")
            self.daily_added_songs = []
            self.daily_search_failures = []
    
    def cleanup_old_daily_caches(self):
        """Remove daily cache files older than 7 days."""
        try:
            cutoff_date = datetime.datetime.now(pytz.timezone(TIMEZONE)).date() - datetime.timedelta(days=7)
            removed_count = 0
            
            for filename in os.listdir(self.DAILY_CACHE_DIR):
                if filename.endswith('.json'):
                    try:
                        # Extract date from filename (format: YYYY-MM-DD_added.json or YYYY-MM-DD_failed.json)
                        date_str = filename.split('_')[0]
                        file_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                        
                        if file_date < cutoff_date:
                            file_path = os.path.join(self.DAILY_CACHE_DIR, filename)
                            os.remove(file_path)
                            removed_count += 1
                            logging.debug(f"Removed old daily cache: {filename}")
                    except (ValueError, IndexError):
                        # Skip files that don't match expected format
                        continue
            
            if removed_count > 0:
                logging.info(f"Cleaned up {removed_count} old daily cache files")
                
        except Exception as e:
            logging.error(f"Error during daily cache cleanup: {e}")
    
    def add_song_to_daily_cache(self, song_data):
        """Add a song to the daily cache and save immediately."""
        self.daily_added_songs.append(song_data)
        self.save_daily_cache()
    
    def add_failure_to_daily_cache(self, failure_data):
        """Add a failure to the daily cache and save immediately."""
        self.daily_search_failures.append(failure_data)
        self.save_daily_cache()

    def create_daily_cache_attachments(self, date_str=None):
        """Create JSON files with daily cache data for email attachments."""
        if date_str is None:
            date_str = self.current_date.isoformat()
        
        attachments = []
        
        try:
            # Create added songs attachment
            added_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{date_str}_added.json")
            if os.path.exists(added_cache_file):
                with open(added_cache_file, 'r') as f:
                    added_data = json.load(f)
                
                # Create a comprehensive JSON file
                added_summary = {
                    "date": date_str,
                    "summary": {
                        "total_songs_added": len(added_data),
                        "unique_artists": len(set(song['radio_artist'] for song in added_data)),
                        "success_rate": "100%" if added_data else "0%"
                    },
                    "songs": added_data
                }
                
                # Create temporary file for attachment
                temp_added_file = f"/tmp/radiox_added_{date_str}.json"
                with open(temp_added_file, 'w') as f:
                    json.dump(added_summary, f, indent=2)
                
                attachments.append({
                    'filepath': temp_added_file,
                    'filename': f"radiox_songs_added_{date_str}.json",
                    'description': f"Complete list of {len(added_data)} songs added on {date_str}"
                })
            
            # Create failed searches attachment
            failed_cache_file = os.path.join(self.DAILY_CACHE_DIR, f"{date_str}_failed.json")
            if os.path.exists(failed_cache_file):
                with open(failed_cache_file, 'r') as f:
                    failed_data = json.load(f)
                
                # Create a comprehensive JSON file
                failed_summary = {
                    "date": date_str,
                    "summary": {
                        "total_failed_searches": len(failed_data),
                        "failure_reasons": dict(Counter(item['reason'] for item in failed_data))
                    },
                    "failed_searches": failed_data
                }
                
                # Create temporary file for attachment
                temp_failed_file = f"/tmp/radiox_failed_{date_str}.json"
                with open(temp_failed_file, 'w') as f:
                    json.dump(failed_summary, f, indent=2)
                
                attachments.append({
                    'filepath': temp_failed_file,
                    'filename': f"radiox_failed_searches_{date_str}.json",
                    'description': f"Complete list of {len(failed_data)} failed searches on {date_str}"
                })
            
            # Create combined daily summary attachment
            combined_summary = {
                "date": date_str,
                "generated_at": datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
                "summary": {
                    "total_songs_added": len(added_data) if os.path.exists(added_cache_file) else 0,
                    "total_failed_searches": len(failed_data) if os.path.exists(failed_cache_file) else 0,
                    "success_rate": "100%" if (os.path.exists(added_cache_file) and added_data) else "0%"
                },
                "songs_added": added_data if os.path.exists(added_cache_file) else [],
                "failed_searches": failed_data if os.path.exists(failed_cache_file) else []
            }
            
            # Create temporary file for combined attachment
            temp_combined_file = f"/tmp/radiox_daily_summary_{date_str}.json"
            with open(temp_combined_file, 'w') as f:
                json.dump(combined_summary, f, indent=2)
            
            attachments.append({
                'filepath': temp_combined_file,
                'filename': f"radiox_daily_summary_{date_str}.json",
                'description': f"Complete daily summary for {date_str} (includes both added songs and failed searches)"
            })
            
        except Exception as e:
            logging.error(f"Error creating daily cache attachments: {e}")
        
        return attachments

    # --- Authentication ---
    def authenticate_spotify(self):
        """Initializes and authenticates the Spotipy client using refresh token."""
        try:
            auth_manager = spotipy.oauth2.SpotifyOAuth(
                client_id=SPOTIPY_CLIENT_ID,
                client_secret=SPOTIPY_CLIENT_SECRET,
                redirect_uri=SPOTIPY_REDIRECT_URI,
                scope="playlist-modify-public playlist-modify-private",
                open_browser=False,  # Disable browser opening in container
                cache_handler=spotipy.cache_handler.CacheFileHandler(cache_path=".spotipy_cache")
            )
            
            # Try to get a token from cache first
            token_info = auth_manager.get_cached_token()
            
            if not token_info:
                # If no cached token, we can't authenticate in a container
                # The Flask server should still start, but the bot won't work
                self.sp = None
                logging.warning("No cached Spotify token found. The bot will not function until a token is provided.")
                logging.warning("To fix this, you need to:")
                logging.warning("1. Run the application locally first to generate a token")
                logging.warning("2. Copy the .spotipy_cache file to the server")
                logging.warning("3. Restart the application")
                return False
            
            # If we have a token, use it
            if auth_manager.is_token_expired(token_info):
                try:
                    token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
                except Exception as refresh_error:
                    logging.error(f"Failed to refresh token: {refresh_error}")
                    self.sp = None
                    return False
            
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
        if not is_retry_from_queue: self.add_failure_to_daily_cache({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify after all attempts."})
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

            song_data = {
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
            }
            self.add_song_to_daily_cache(song_data)
            self.log_event(f"SUCCESS: Added '{BOLD}{radio_x_title}{RESET}' by '{BOLD}{radio_x_artist}{RESET}' to playlist.")
            self.RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id)
            return True
        except spotipy.SpotifyException as e:
            reason = f"API Error: HTTP {e.http_status} - {e.msg}"
            if e.http_status == 403 and "duplicate" in e.msg.lower(): 
                 self.RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id)
                 reason = "Spotify blocked add as duplicate (already in playlist)"
            else: logging.error(f"Error adding track '{radio_x_title}': {e}")
            self.add_failure_to_daily_cache({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": reason})
            return False
        except Exception as e:
            logging.error(f"Unexpected error adding track '{radio_x_title}': {e}")
            self.add_failure_to_daily_cache({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": f"Unexpected error during add: {e}"})
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
            self.add_song_to_playlist(item['title'], item['artist'], spotify_id, SPOTIFY_PLAYLIST_ID)
        elif item['attempts'] < MAX_FAILED_SEARCH_ATTEMPTS:
            self.failed_search_queue.append(item)
            self.log_event(f"PFSQ: Re-queued '{item['title']}' (Attempts: {item['attempts']}).")
        else:
            self.log_event(f"PFSQ: Max retries reached for '{item['title']}'. Discarding.")
            self.add_failure_to_daily_cache({"timestamp": datetime.datetime.now().isoformat(), "radio_title": item['title'], "radio_artist": item['artist'], "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."})

    # --- Email & Summary Functions ---
    def send_summary_email(self, html_body, subject, attachments=None):
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
            self.log_event("Email settings not configured. Skipping email.")
            return False
        self.log_event(f"Attempting to send email to {EMAIL_RECIPIENT}...")
        try:
            port = int(EMAIL_PORT)
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = EMAIL_HOST_USER
            msg['To'] = EMAIL_RECIPIENT
            msg.attach(MIMEText(html_body, 'html'))
            
            # Add attachments if provided
            if attachments:
                for attachment in attachments:
                    try:
                        with open(attachment['filepath'], 'rb') as f:
                            part = MIMEBase('application', 'json')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                'Content-Disposition',
                                f'attachment; filename= {attachment["filename"]}'
                            )
                            msg.attach(part)
                        self.log_event(f"Added attachment: {attachment['filename']} ({attachment['description']})")
                    except Exception as e:
                        logging.error(f"Failed to add attachment {attachment['filename']}: {e}")
            
            with smtplib.SMTP(EMAIL_HOST, port) as server:
                server.starttls()
                server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
                server.send_message(msg)
            
            # Clean up temporary attachment files
            if attachments:
                for attachment in attachments:
                    try:
                        os.remove(attachment['filepath'])
                    except:
                        pass
            
            logging.info("Email sent successfully.")
            return True
        except Exception as e:
            logging.error(f"Failed to send email: {e}")
            return False

    def get_daily_stats_html(self):
        """Generate enhanced daily statistics HTML with modern styling."""
        if not self.daily_added_songs and not self.daily_search_failures:
            return ""
        
        try:
            # Calculate statistics
            total_added = len(self.daily_added_songs)
            total_failed = len(self.daily_search_failures)
            total_processed = total_added + total_failed
            success_rate = (total_added / total_processed * 100) if total_processed > 0 else 100
            
            # Artist statistics
            artist_counts = Counter(item['radio_artist'] for item in self.daily_added_songs)
            unique_artists = len(artist_counts)
            top_artists = artist_counts.most_common(5)
            
            # Time analysis
            hour_counts = Counter()
            if self.daily_added_songs:
                for item in self.daily_added_songs:
                    try:
                        timestamp = datetime.datetime.fromisoformat(item['timestamp'])
                        hour_counts[timestamp.hour] += 1
                    except:
                        pass
            
            busiest_hour = hour_counts.most_common(1)[0] if hour_counts else (0, 0)
            
            # Release date analysis
            songs_with_dates = [s for s in self.daily_added_songs if s.get('release_date') and '-' in s['release_date']]
            decade_counts = Counter()
            oldest_song = None
            newest_song = None
            
            if songs_with_dates:
                songs_with_dates.sort(key=lambda x: x['release_date'])
                oldest_song = songs_with_dates[0]
                newest_song = songs_with_dates[-1]
                decade_counts = Counter((int(s['release_date'][:4]) // 10) * 10 for s in songs_with_dates)
            
            # Failure analysis
            failure_reasons = Counter(item['reason'] for item in self.daily_search_failures)
            
            # Generate enhanced HTML
            html = f"""
            <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background: #f8f9fa; padding: 20px; border-radius: 10px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
                    <h1 style="margin: 0; font-size: 2.5em; font-weight: 300;">📊 Daily Summary</h1>
                    <p style="margin: 10px 0 0 0; font-size: 1.2em; opacity: 0.9;">RadioX Spotify Playlist</p>
                </div>
                
                <!-- Songs Added Today -->
                {self._format_songs_added_section() if self.daily_added_songs else ''}
                
                <!-- Key Metrics -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px;">
                    <div style="background: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <div style="font-size: 2.5em; font-weight: bold; color: #28a745;">{total_added}</div>
                        <div style="color: #6c757d; font-weight: 500;">Songs Added</div>
                    </div>
                    <div style="background: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <div style="font-size: 2.5em; font-weight: bold; color: #dc3545;">{total_failed}</div>
                        <div style="color: #6c757d; font-weight: 500;">Failed Searches</div>
                    </div>
                    <div style="background: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <div style="font-size: 2.5em; font-weight: bold; color: #17a2b8;">{unique_artists}</div>
                        <div style="color: #6c757d; font-weight: 500;">Unique Artists</div>
                    </div>
                    <div style="background: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <div style="font-size: 2.5em; font-weight: bold; color: #ffc107;">{success_rate:.1f}%</div>
                        <div style="color: #6c757d; font-weight: 500;">Success Rate</div>
                    </div>
                </div>
                
                <!-- Success Rate Progress Bar -->
                <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h3 style="margin: 0 0 15px 0; color: #495057;">Success Rate</h3>
                    <div style="background: #e9ecef; border-radius: 10px; height: 20px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #28a745, #20c997); height: 100%; width: {success_rate}%; transition: width 0.3s ease; border-radius: 10px;"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 0.9em; color: #6c757d;">
                        <span>{total_added} successful</span>
                        <span>{total_failed} failed</span>
                    </div>
                </div>
                
                <!-- Top Artists -->
                {self._format_top_artists_section(top_artists) if top_artists else ''}
                
                <!-- Decade Breakdown -->
                {self._format_decade_section(decade_counts) if decade_counts else ''}
                
                <!-- Time Analysis -->
                {self._format_time_analysis(hour_counts, busiest_hour) if hour_counts else ''}
                
                <!-- Song Range -->
                {self._format_song_range(oldest_song, newest_song) if oldest_song and newest_song else ''}
                
                <!-- Failure Analysis -->
                {self._format_failure_analysis(failure_reasons) if failure_reasons else ''}
                
                <!-- Queue Status -->
                <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h3 style="margin: 0 0 15px 0; color: #495057;">🔄 Retry Queue Status</h3>
                    <div style="display: flex; align-items: center; gap: 15px;">
                        <div style="font-size: 2em; margin-right: 12px;">{len(self.failed_search_queue)}</div>
                        <div>
                            <div style="font-weight: 500; color: #495057;">Items in Queue</div>
                            <div style="font-size: 0.9em; color: #6c757d;">Will be retried automatically</div>
                        </div>
                    </div>
                </div>
            </div>
            """
            
            return html
            
        except Exception as e:
            logging.error(f"Could not generate enhanced daily stats: {e}")
            return ""

    def _format_top_artists_section(self, top_artists):
        """Format the top artists section."""
        if not top_artists:
            return ""
        
        max_count = max(count for _, count in top_artists)
        artists_html = ""
        
        for i, (artist, count) in enumerate(top_artists):
            percentage = (count / max_count) * 100
            artists_html += f"""
            <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
                <div style="background: #007bff; color: white; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 0.9em; margin-right: 12px;">{i+1}</div>
                <div style="flex: 1;">
                    <div style="font-weight: 500; color: #495057;">{artist}</div>
                    <div style="background: #e9ecef; border-radius: 5px; height: 8px; overflow: hidden; margin-top: 5px;">
                        <div style="background: linear-gradient(90deg, #007bff, #0056b3); height: 100%; width: {percentage}%; border-radius: 5px;"></div>
                    </div>
                </div>
                <div style="font-weight: bold; color: #007bff; min-width: 40px; text-align: right;">{count}</div>
            </div>
            """
        
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 20px 0; color: #495057;">🎤 Top Artists</h3>
            {artists_html}
        </div>
        """

    def _format_decade_section(self, decade_counts):
        """Format the decade breakdown section."""
        if not decade_counts:
            return ""
        
        total_songs = sum(decade_counts.values())
        decades_html = ""
        
        for decade, count in decade_counts.most_common(5):
            percentage = (count / total_songs) * 100
            decades_html += f"""
            <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
                <div style="background: #6f42c1; color: white; padding: 5px 12px; border-radius: 15px; font-weight: bold; font-size: 0.9em;">{decade}s</div>
                <div style="flex: 1;">
                    <div style="background: #e9ecef; border-radius: 5px; height: 8px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #6f42c1, #5a32a3); height: 100%; width: {percentage}%; border-radius: 5px;"></div>
                    </div>
                </div>
                <div style="font-weight: bold; color: #6f42c1; min-width: 60px; text-align: right;">{percentage:.0f}%</div>
            </div>
            """
        
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 20px 0; color: #495057;">📅 Decade Breakdown</h3>
            {decades_html}
        </div>
        """

    def _format_time_analysis(self, hour_counts, busiest_hour):
        """Format the time analysis section."""
        if not hour_counts:
            return ""
        
        hour, count = busiest_hour
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 15px 0; color: #495057;">⏰ Busiest Hour</h3>
            <div style="display: flex; align-items: center; gap: 15px;">
                <div style="background: #fd7e14; color: white; width: 50px; height: 50px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 1.2em; margin-right: 12px;">{hour:02d}</div>
                <div>
                    <div style="font-weight: 500; color: #495057;">{hour:02d}:00 - {hour:02d}:59</div>
                    <div style="font-size: 0.9em; color: #6c757d;">{count} songs added</div>
                </div>
            </div>
        </div>
        """

    def _format_song_range(self, oldest_song, newest_song):
        """Format the song range section."""
        if not oldest_song or not newest_song:
            return ""
        
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 20px 0; color: #495057;">🎵 Song Range</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div style="text-align: center; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                    <div style="font-size: 2em; color: #6c757d;">📜</div>
                    <div style="font-weight: 500; color: #495057; margin: 5px 0;">Oldest</div>
                    <div style="font-size: 0.9em; color: #6c757d;">{oldest_song['spotify_title']}</div>
                    <div style="font-size: 0.8em; color: #6c757d;">{oldest_song['spotify_artist']}</div>
                    <div style="font-weight: bold; color: #495057; margin-top: 5px;">{oldest_song['release_date'][:4]}</div>
                </div>
                <div style="text-align: center; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                    <div style="font-size: 2em; color: #6c757d;">🆕</div>
                    <div style="font-weight: 500; color: #495057; margin: 5px 0;">Newest</div>
                    <div style="font-size: 0.9em; color: #6c757d;">{newest_song['spotify_title']}</div>
                    <div style="font-size: 0.8em; color: #6c757d;">{newest_song['spotify_artist']}</div>
                    <div style="font-weight: bold; color: #495057; margin-top: 5px;">{newest_song['release_date'][:4]}</div>
                </div>
            </div>
        </div>
        """

    def _format_failure_analysis(self, failure_reasons):
        """Format the failure analysis section."""
        if not failure_reasons:
            return ""
        
        total_failures = sum(failure_reasons.values())
        failures_html = ""
        
        for reason, count in failure_reasons.most_common():
            percentage = (count / total_failures) * 100
            failures_html += f"""
            <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
                <div style="flex: 1;">
                    <div style="font-weight: 500; color: #495057; font-size: 0.9em;">{reason}</div>
                    <div style="background: #e9ecef; border-radius: 5px; height: 6px; overflow: hidden; margin-top: 3px;">
                        <div style="background: linear-gradient(90deg, #dc3545, #c82333); height: 100%; width: {percentage}%; border-radius: 5px;"></div>
                    </div>
                </div>
                <div style="font-weight: bold; color: #dc3545; min-width: 40px; text-align: right;">{count}</div>
            </div>
            """
        
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 20px 0; color: #495057;">❌ Failure Analysis</h3>
            {failures_html}
        </div>
        """

    def _format_songs_added_section(self):
        """Format the songs added today section."""
        if not self.daily_added_songs:
            return ""
        
        # Sort songs by timestamp (newest first)
        sorted_songs = sorted(self.daily_added_songs, key=lambda x: x.get('timestamp', ''), reverse=True)
        
        songs_html = ""
        for song in sorted_songs:
            # Format timestamp
            try:
                timestamp = datetime.datetime.fromisoformat(song['timestamp'])
                time_str = timestamp.strftime('%H:%M')
            except:
                time_str = "Unknown"
            
            # Get song details
            title = song.get('radio_title', 'Unknown Title')
            artist = song.get('radio_artist', 'Unknown Artist')
            album = song.get('album_name', 'Unknown Album')
            year = song.get('release_date', 'Unknown Year')[:4] if song.get('release_date') else 'Unknown'
            
            songs_html += f"""
            <div style="display: flex; align-items: center; gap: 15px; padding: 15px; border-bottom: 1px solid #e9ecef; background: #f8f9fa; border-radius: 8px; margin-bottom: 10px;">
                <div style="background: #28a745; color: white; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 0.9em; margin-right: 12px;">✓</div>
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: #495057; font-size: 1.1em;">{title}</div>
                    <div style="color: #6c757d; font-size: 0.95em;">{artist}</div>
                    <div style="color: #adb5bd; font-size: 0.85em;">{album} • {year}</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-weight: 500; color: #007bff; font-size: 1.1em;">{time_str}</div>
                    <div style="color: #6c757d; font-size: 0.8em;">Added</div>
                </div>
            </div>
            """
        
        return f"""
        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h3 style="margin: 0 0 20px 0; color: #495057;">🎵 Songs Added Today ({len(sorted_songs)})</h3>
            <div style="max-height: 400px; overflow-y: auto;">
                {songs_html}
            </div>
        </div>
        """

    def log_and_send_daily_summary(self):
        if not self.daily_added_songs and not self.daily_search_failures:
            self.log_event("Daily summary skipped: No new songs added or failed.")
            self.daily_added_songs.clear()
            self.daily_search_failures.clear()
            self.save_state()
            return

        summary_date = self.last_summary_log_date.isoformat()
        html_body = self.get_daily_stats_html()
        
        # Create daily cache attachments
        attachments = self.create_daily_cache_attachments(summary_date)
        
        self.send_summary_email(html_body, subject=f"Radio X Spotify Adder Daily Summary: {summary_date}", attachments=attachments)
        self.daily_added_songs.clear(); self.daily_search_failures.clear(); self.save_state()

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
        
    def run_startup_diagnostics(self, send_email=False):
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

        artist_counts = Counter(item['radio_artist'] for item in self.daily_added_songs)
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

    def send_debug_log(self):
        """Sends debug log information via email."""
        try:
            # Get recent log entries (this is a simplified version)
            log_entries = [
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Debug log requested",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Service state: {self.service_state}",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Spotify client: {'Available' if self.sp else 'Not available'}",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Daily added songs: {len(self.daily_added_songs)}",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Failed queue size: {len(self.failed_search_queue)}"
            ]
            
            html_body = f"""
            <html>
            <body>
                <h2>Debug Log Report</h2>
                <p><strong>Generated:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Backend Version:</strong> {BACKEND_VERSION}</p>
                <h3>Recent Log Entries:</h3>
                <pre>{chr(10).join(log_entries)}</pre>
                <h3>Service State:</h3>
                <p><strong>State:</strong> {self.service_state}</p>
                <p><strong>Paused Reason:</strong> {self.paused_reason}</p>
                <p><strong>Spotify Client:</strong> {'Available' if self.sp else 'Not available'}</p>
            </body>
            </html>
            """
            
            self.send_summary_email(html_body, "RadioX Spotify Debug Log")
            self.log_event("Debug log sent successfully.")
            
        except Exception as e:
            self.log_event(f"Error sending debug log: {e}")

    def test_daily_summary_with_cached_data(self):
        """Sends a test daily summary using cached data from the previous day."""
        try:
            # Load cached data
            daily_added = []
            daily_failed = []
            
            try:
                with open(self.DAILY_ADDED_CACHE_FILE, 'r') as f:
                    daily_added = json.load(f)
                with open(self.DAILY_FAILED_CACHE_FILE, 'r') as f:
                    daily_failed = json.load(f)
            except FileNotFoundError:
                self.log_event("No cached data found for test summary.")
                return
            
            if not daily_added and not daily_failed:
                self.log_event("No cached data available for test summary.")
                return
            
            # Generate test summary HTML
            html_body = self.get_daily_stats_html()
            
            # Send the test summary
            self.send_summary_email(html_body, "RadioX Spotify - Daily Summary Test")
            self.log_event("Test daily summary sent successfully.")
            
        except Exception as e:
            self.log_event(f"Error sending test daily summary: {e}")

    # --- Main Application Loop ---
    def run(self):
        """Main monitoring loop."""
        self.is_running = True
        self.update_service_state('playing')
        logging.info("RadioX monitoring thread started")
        
        if not self.sp: 
            self.log_event("ERROR: Spotify client is None. Thread cannot perform Spotify actions.")
            logging.error("Spotify client is None - monitoring thread cannot continue")
            self.update_service_state('error', 'Spotify client not available')
            return
        
        if self.last_summary_log_date is None: 
            self.last_summary_log_date = datetime.date.today()
        
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
        
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
                
                if self.last_summary_log_date < now_local.date():
                    logging.info(f"New day detected: {now_local.date().isoformat()}")
                    self.startup_email_sent, self.shutdown_summary_sent = False, False
                    self.daily_added_songs.clear(); self.daily_search_failures.clear(); self.save_state()
                    self.last_summary_log_date = now_local.date()
                
                # Handle time window that spans midnight (7am to 6am)
                if START_TIME <= now_local.time() <= END_TIME:
                    self.update_service_state('playing')
                    self.paused_reason = ''
                    if not self.startup_email_sent:
                        self.send_startup_notification("<tr><td>Daily Operation</td><td style='color:green;'>SUCCESS</td><td>Entered active hours.</td></tr>"); self.startup_email_sent = True; self.shutdown_summary_sent = False
                        logging.info("Active hours started - sending startup notification")
                    logging.info("=== Starting monitoring cycle ===")
                    self.process_main_cycle()
                else:
                    self.update_service_state('paused', 'out_of_hours')
                    if not self.shutdown_summary_sent:
                        self.log_and_send_daily_summary(); self.shutdown_summary_sent = True; self.startup_email_sent = False
                        logging.info("End of active day - sending daily summary")
                    logging.info("Outside active hours - pausing monitoring")
                    time.sleep(CHECK_INTERVAL * 5); continue
            except Exception as e: 
                logging.error(f"CRITICAL UNHANDLED ERROR in main loop: {e}", exc_info=True); 
                time.sleep(CHECK_INTERVAL * 2) 
            
            time.sleep(CHECK_INTERVAL)

    def process_main_cycle(self):
        logging.info("=== Starting main cycle ===")
        
        # Check and update daily cache (handles date rollovers)
        self.check_and_update_daily_cache()
        
        if not self.current_station_herald_id: 
            self.current_station_herald_id = self.get_station_herald_id(RADIOX_STATION_SLUG)
            logging.info(f"Retrieved station herald ID: {self.current_station_herald_id}")
        if not self.current_station_herald_id: 
            logging.error("Failed to get station herald ID")
            return
        
        current_song_info = self.get_current_radiox_song(self.current_station_herald_id)
        song_added = False
        if current_song_info:
            title, artist, radiox_id = current_song_info["title"], current_song_info["artist"], current_song_info["id"]
            if not title or not artist: 
                logging.warning("Empty title or artist from Radio X.")
            elif radiox_id == self.last_added_radiox_track_id: 
                logging.info(f"Skipping duplicate song: {title} by {artist}")
            else:
                logging.info(f"Processing new song: {title} by {artist}")
                spotify_track_id = self.search_song_on_spotify(title, artist, radiox_id) 
                if spotify_track_id:
                    if self.add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID): 
                        song_added = True
                self.last_added_radiox_track_id = radiox_id 
        else: 
            logging.info("No new track information available from Radio X")
        
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
        
        logging.info("=== Main cycle completed ===")

    def search_song_on_spotify_smart(self, original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
        """Smart search using artist-specific strategy order and learning."""
        strategies = self.smart_search.get_optimal_search_order(artist, original_title)
        search_attempts_details = []
        for strategy in strategies:
            if strategy == 'original':
                title_to_search = original_title
            elif strategy == 'no_parentheses':
                title_to_search = re.sub(r'\s*\(.*?\)\s*', ' ', original_title).strip()
            elif strategy == 'no_features':
                title_to_search = re.sub(r'\s*\[.*?\]\s*|feat\..*', ' ', original_title, flags=re.IGNORECASE).strip()
            else:
                continue
            
            spotify_id = self.search_song_on_spotify(title_to_search, artist, radiox_id_for_queue, is_retry_from_queue)
            if spotify_id:
                self.smart_search.update_success_rate(artist, strategy, True)
                return spotify_id
            else:
                self.smart_search.update_success_rate(artist, strategy, False)
        # If all fail, log and return None
        self.log_event(f"SMART FAIL: Song '{original_title}' by '{artist}' not found after all smart attempts.")
        if not is_retry_from_queue:
            self.daily_search_failures.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "radio_title": original_title,
                "radio_artist": artist,
                "reason": "Not found on Spotify after all smart attempts."
            })
        return None

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
    # Read the filtered log file and email it
    try:
        with open(log_file, 'r') as f:
            log_content = f.read()
        
        # Check if log content is empty or only contains whitespace
        if not log_content.strip():
            subject = "RadioX Spotify Debug Log File (Filtered) - No Issues Detected"
            html_body = """
            <h2>🎉 No Issues Detected!</h2>
            <p>The debug log file is empty, which means no errors, warnings, or problematic events have been detected since the last log rotation.</p>
            <p>This is a good sign - your RadioX Spotify bot is running smoothly!</p>
            <hr>
            <p><em>Debug log requested on: {timestamp}</em></p>
            """.format(timestamp=datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S'))
        else:
            subject = "RadioX Spotify Debug Log File (Filtered)"
            html_body = f"<pre>{log_content}</pre>"
        
        bot_instance.send_summary_email(html_body, subject)
        bot_instance.log_event("Debug log file sent successfully.")
        return "Debug log has been emailed."
    except Exception as e:
        bot_instance.log_event(f"Error sending debug log file: {e}")
        return f"Error sending debug log: {e}"

@app.route('/admin/test_daily_summary', methods=['POST'])
def admin_test_daily_summary():
    bot_instance.log_event("Daily summary test manually triggered via web.")
    threading.Thread(target=bot_instance.test_daily_summary_with_cached_data).start()
    return "Daily summary test has been triggered. Check email for results."

@app.route('/admin/request_historical_data', methods=['POST'])
def admin_request_historical_data():
    """Request historical cache data for a specific date."""
    try:
        data = request.get_json()
        date_str = data.get('date') if data else None
        
        if not date_str:
            return jsonify({"error": "Date parameter required"}), 400
        
        # Validate date format
        try:
            datetime.datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        bot_instance.log_event(f"Historical data request for {date_str} manually triggered via web.")
        
        def send_historical_data():
            try:
                # Create attachments for the requested date
                attachments = bot_instance.create_daily_cache_attachments(date_str)
                
                if not attachments:
                    # Send email with no data message
                    html_body = f"""
                    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background: #f8f9fa; padding: 20px; border-radius: 10px;">
                        <div style="background: #dc3545; color: white; padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
                            <h1 style="margin: 0; font-size: 2.5em; font-weight: 300;">📊 Historical Data Request</h1>
                            <p style="margin: 10px 0 0 0; font-size: 1.2em; opacity: 0.9;">No Data Available</p>
                        </div>
                        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                            <h3 style="margin: 0 0 15px 0; color: #495057;">No Data Found</h3>
                            <p style="color: #6c757d;">No cache data was found for <strong>{date_str}</strong>.</p>
                            <p style="color: #6c757d;">This could mean:</p>
                            <ul style="color: #6c757d;">
                                <li>The date is in the future</li>
                                <li>No songs were processed on that date</li>
                                <li>The cache files have been cleaned up (older than 7 days)</li>
                            </ul>
                        </div>
                    </div>
                    """
                    bot_instance.send_summary_email(html_body, f"RadioX Historical Data Request: {date_str} - No Data Available")
                else:
                    # Send email with the data
                    html_body = f"""
                    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background: #f8f9fa; padding: 20px; border-radius: 10px;">
                        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
                            <h1 style="margin: 0; font-size: 2.5em; font-weight: 300;">📊 Historical Data</h1>
                            <p style="margin: 10px 0 0 0; font-size: 1.2em; opacity: 0.9;">{date_str}</p>
                        </div>
                        <div style="background: white; padding: 25px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                            <h3 style="margin: 0 0 15px 0; color: #495057;">Data Available</h3>
                            <p style="color: #6c757d;">Historical cache data for <strong>{date_str}</strong> has been attached to this email.</p>
                            <p style="color: #6c757d;">The following files are included:</p>
                            <ul style="color: #6c757d;">
                                {''.join(f'<li>{attachment["description"]}</li>' for attachment in attachments)}
                            </ul>
                        </div>
                    </div>
                    """
                    bot_instance.send_summary_email(html_body, f"RadioX Historical Data: {date_str}", attachments=attachments)
                
                bot_instance.log_event(f"Historical data for {date_str} sent successfully.")
                
            except Exception as e:
                bot_instance.log_event(f"Error sending historical data for {date_str}: {e}")
        
        threading.Thread(target=send_historical_data).start()
        return jsonify({"message": f"Historical data request for {date_str} has been triggered. Check email for results."})
        
    except Exception as e:
        return jsonify({"error": f"Error processing request: {e}"}), 500

@app.route('/status')
def status():
    # Non-blocking status endpoint that doesn't depend on initialization
    try:
        # Check and update daily cache to ensure we're reading the correct date's data
        bot_instance.check_and_update_daily_cache()
        
        # Read from the current daily cache files without blocking
        if os.path.exists(bot_instance.current_daily_cache_file):
            with open(bot_instance.current_daily_cache_file, 'r') as f:
                daily_added = json.load(f)
        else:
            daily_added = []
            
        if os.path.exists(bot_instance.current_daily_failed_cache_file):
            with open(bot_instance.current_daily_failed_cache_file, 'r') as f:
                daily_failed = json.load(f)
        else:
            daily_failed = []
            
        if os.path.exists(bot_instance.FAILED_QUEUE_CACHE_FILE):
            with open(bot_instance.FAILED_QUEUE_CACHE_FILE, 'r') as f: 
                failed_queue = json.load(f)
        else:
            failed_queue = []
            
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
        'service_state': getattr(bot_instance, 'service_state', 'initializing'),
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

@app.route('/health')
def health():
    """Simple health check endpoint that doesn't require initialization."""
    return jsonify({
        "status": "healthy",
        "backend_version": BACKEND_VERSION,
        "timestamp": datetime.datetime.now().isoformat()
    })

def initialize_bot():
    """Handles the slow startup tasks in the background."""
    logging.info("=== Background initialization started ===")
    
    # Set a timeout for the entire initialization process
    start_time = time.time()
    max_init_time = 300  # 5 minutes max for initialization
    
    try:
        logging.info("Attempting Spotify authentication...")
        auth_success = False
        
        # Add timeout to Spotify authentication
        def auth_with_timeout():
            return bot_instance.authenticate_spotify()
        
        # Run authentication with timeout
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(auth_with_timeout)
            try:
                auth_success = future.result(timeout=60)  # 60 second timeout for auth
                logging.info("Spotify authentication successful" if auth_success else "Spotify authentication failed")
            except concurrent.futures.TimeoutError:
                logging.error("Spotify authentication timed out after 60 seconds")
                auth_success = False
            except Exception as e:
                logging.error(f"Spotify authentication failed with error: {e}")
                auth_success = False
        
        if auth_success:
            # Load state with timeout and error handling
            try:
                logging.info("Loading state...")
                # Add timeout to state loading
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(bot_instance.load_state)
                    try:
                        future.result(timeout=30)  # 30 second timeout for state loading
                        logging.info("State loaded successfully")
                    except concurrent.futures.TimeoutError:
                        logging.error("State loading timed out after 30 seconds")
                        # Continue anyway - don't let this block startup
                    except Exception as e:
                        logging.error(f"Failed to load state: {e}")
                        # Continue anyway - don't let this block startup
            except Exception as e:
                logging.error(f"Failed to load state: {e}")
                # Continue anyway - don't let this block startup
            
            # Run diagnostics with timeout
            try:
                logging.info("Running startup diagnostics...")
                # Add timeout to diagnostics
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(bot_instance.run_startup_diagnostics, False)
                    try:
                        future.result(timeout=60)  # 60 second timeout for diagnostics
                        logging.info("Startup diagnostics completed")
                    except concurrent.futures.TimeoutError:
                        logging.error("Startup diagnostics timed out after 60 seconds")
                        # Continue anyway - don't let this block startup
                    except Exception as e:
                        logging.error(f"Failed to run startup diagnostics: {e}")
                        # Continue anyway - don't let this block startup
            except Exception as e:
                logging.error(f"Failed to run startup diagnostics: {e}")
                # Continue anyway - don't let this block startup
            
            # Start monitoring thread
            try:
                logging.info("Starting main monitoring thread...")
                monitor_thread = threading.Thread(target=bot_instance.run, daemon=True)
                monitor_thread.start()
                logging.info("Main monitoring thread started")
                
                # Get station herald ID for WebSocket listener
                try:
                    bot_instance.current_station_herald_id = bot_instance.get_station_herald_id(RADIOX_STATION_SLUG)
                    if bot_instance.current_station_herald_id:
                        logging.info(f"Station herald ID: {bot_instance.current_station_herald_id}")
                    else:
                        logging.warning("Failed to retrieve station herald ID - WebSocket listener may not work")
                except Exception as e:
                    logging.error(f"Failed to retrieve station herald ID: {e}")
                
                # Start real-time WebSocket listener after monitoring thread is ready
                try:
                    bot_instance.realtime_listener.start_listening()
                    logging.info("Real-time WebSocket listener started")
                except Exception as e:
                    logging.error(f"Failed to start WebSocket listener: {e}")
                    # Don't fail initialization for this - it's optional
                
                bot_instance.update_service_state('playing', 'Initialization complete')
            except Exception as e:
                logging.error(f"Failed to start monitoring thread: {e}")
                bot_instance.update_service_state('error', f'Failed to start monitoring thread: {e}')
        else:
            logging.warning("Spotify authentication failed. The Flask server will start but the bot will not function.")
            logging.warning("The application will be available for admin functions but won't monitor RadioX.")
            # Still load state and run diagnostics even without Spotify
            try:
                bot_instance.load_state()
                logging.info("State loaded successfully")
            except Exception as e:
                logging.warning(f"Could not load state: {e}")
            
            # Don't start the monitoring thread if authentication failed
            bot_instance.update_service_state('error', 'Spotify authentication failed')
    
    except Exception as e:
        logging.error(f"Critical error during initialization: {e}")
        bot_instance.update_service_state('error', f'Initialization failed: {e}')
    
    # Check if initialization took too long
    init_time = time.time() - start_time
    if init_time > max_init_time:
        logging.warning(f"Initialization took {init_time:.1f} seconds (longer than {max_init_time}s)")
    
    logging.info(f"=== Background initialization completed in {init_time:.1f} seconds ===")

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

    return Response(event_stream(), content_type='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Cache-Control'
    })

@app.route('/activity')
def activity():
    activities = bot_instance.activity_tracker.get_recent_activities()
    stats = bot_instance.activity_tracker.get_stats()
    return jsonify({
        'activities': activities,
        'stats': stats
    })

@app.route('/debug/threads')
def debug_threads():
    """Debug endpoint to check if monitoring thread is running."""
    import threading
    active_threads = threading.enumerate()
    thread_info = []
    
    for thread in active_threads:
        thread_info.append({
            'name': thread.name,
            'daemon': thread.daemon,
            'alive': thread.is_alive(),
            'ident': thread.ident
        })
    
    # Check if monitoring thread is running
    monitoring_running = any('run' in thread.name.lower() for thread in active_threads if thread.is_alive())
    
    return jsonify({
        'monitoring_thread_running': monitoring_running,
        'total_threads': len(active_threads),
        'threads': thread_info,
        'bot_is_running': getattr(bot_instance, 'is_running', False),
        'service_state': getattr(bot_instance, 'service_state', 'unknown')
    })

# --- Script Execution ---
if __name__ == "__main__":
    # This block runs for local development
    logging.info("=== Script being run directly for local testing ===")
    
    # Run initialization in background thread to avoid blocking Flask startup
    logging.info("Starting initialization in background...")
    init_thread = threading.Thread(target=initialize_bot, daemon=True)
    init_thread.start()
    logging.info("Initialization thread started.")
    
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        logging.warning("Email environment variables not set. Emails will not be sent.")
    port = int(os.environ.get("PORT", 8080)) 
    logging.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) 
else:
    # This block runs when deployed on Gunicorn (like on Render)
    logging.info("=== Starting initialization for production deployment ===")
    # Run initialization in background thread to avoid blocking Flask startup
    init_thread = threading.Thread(target=initialize_bot, daemon=True)
    init_thread.start()
    logging.info("=== Initialization thread started for production deployment ===")
    logging.info("=== Flask server will start immediately ===")
