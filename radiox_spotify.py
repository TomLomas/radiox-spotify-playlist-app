# Radio X to Spotify Playlist Adder
# v7.0 - Final Stable Version with All Features
# Includes: Startup diagnostics, stable functional structure, time-windowed operation, 
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

# --- Global State Variables ---
sp = None
last_added_radiox_track_id = None
last_detected_song = None
herald_id_cache = {}
last_duplicate_check_time = 0
last_summary_log_date = datetime.date.today() - datetime.timedelta(days=1)
startup_email_sent = False
shutdown_summary_sent = False
current_station_herald_id = None
paused = False
event_log = deque(maxlen=50)

# --- Persistent Data Structures ---
CACHE_DIR = ".cache"
if os.path.isfile(CACHE_DIR):
    logging.warning(f"A file named '{CACHE_DIR}' exists. Removing it to create cache directory.")
    try: os.remove(CACHE_DIR)
    except OSError as e: logging.error(f"Error removing file {CACHE_DIR}: {e}")
os.makedirs(CACHE_DIR, exist_ok=True)

RECENTLY_ADDED_CACHE_FILE = os.path.join(CACHE_DIR, "recent_tracks.json")
FAILED_QUEUE_CACHE_FILE = os.path.join(CACHE_DIR, "failed_queue.json")
DAILY_ADDED_CACHE_FILE = os.path.join(CACHE_DIR, "daily_added.json")
DAILY_FAILED_CACHE_FILE = os.path.join(CACHE_DIR, "daily_failed.json")

RECENTLY_ADDED_SPOTIFY_IDS = deque(maxlen=200) 
failed_search_queue = deque(maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
daily_added_songs = [] 
daily_search_failures = [] 

file_lock = threading.Lock()

def log_event(message):
    """Adds an event to the global log for the web UI and standard logging."""
    logging.info(message)
    clean_message = ANSI_ESCAPE.sub('', message)
    event_log.appendleft(f"[{datetime.datetime.now(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S')}] {clean_message}")

# --- Persistent State Management ---
def save_state():
    """Saves the queues and daily summaries to disk."""
    with file_lock:
        try:
            with open(RECENTLY_ADDED_CACHE_FILE, 'w') as f: json.dump(list(RECENTLY_ADDED_SPOTIFY_IDS), f)
            with open(FAILED_QUEUE_CACHE_FILE, 'w') as f: json.dump(list(failed_search_queue), f)
            with open(DAILY_ADDED_CACHE_FILE, 'w') as f: json.dump(daily_added_songs, f)
            with open(DAILY_FAILED_CACHE_FILE, 'w') as f: json.dump(daily_search_failures, f)
            logging.debug("Successfully saved application state to disk.")
        except Exception as e:
            logging.error(f"Failed to save state to disk: {e}")

def load_state():
    """Loads the queues and daily summaries from disk on startup."""
    global RECENTLY_ADDED_SPOTIFY_IDS, failed_search_queue, daily_added_songs, daily_search_failures
    with file_lock:
        try:
            if os.path.exists(RECENTLY_ADDED_CACHE_FILE):
                with open(RECENTLY_ADDED_CACHE_FILE, 'r') as f: RECENTLY_ADDED_SPOTIFY_IDS = deque(json.load(f), maxlen=200)
            if os.path.exists(FAILED_QUEUE_CACHE_FILE):
                with open(FAILED_QUEUE_CACHE_FILE, 'r') as f: failed_search_queue = deque(json.load(f), maxlen=MAX_FAILED_SEARCH_QUEUE_SIZE)
            if os.path.exists(DAILY_ADDED_CACHE_FILE):
                with open(DAILY_ADDED_CACHE_FILE, 'r') as f: daily_added_songs = json.load(f)
            if os.path.exists(DAILY_FAILED_CACHE_FILE):
                with open(DAILY_FAILED_CACHE_FILE, 'r') as f: daily_search_failures = json.load(f)
            logging.info("Loaded state from cache files.")
        except Exception as e:
            logging.error(f"Failed to load state from disk: {e}")

# --- Authentication ---
def authenticate_spotify():
    """Initializes and authenticates the Spotipy client."""
    global sp
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
            sp = spotipy.Spotify(auth_manager=auth_manager)
            user = sp.current_user()
            if user: log_event(f"Successfully authenticated with Spotify as {user['display_name']}."); return True
            else: sp = None; log_event("ERROR: Could not get Spotify user details with token.")
        else: sp = None; log_event("ERROR: Failed to obtain Spotify token.")
    except Exception as e:
        sp = None; logging.critical(f"CRITICAL Error during Spotify Authentication: {e}", exc_info=True)
    return False
    
# --- API Wrappers and Helpers ---
def spotify_api_call_with_retry(func, *args, **kwargs):
    # (This function remains unchanged)
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

def get_station_herald_id(station_slug_to_find):
    global herald_id_cache
    if station_slug_to_find in herald_id_cache: return herald_id_cache[station_slug_to_find]
    url = "https://bff-web-guacamole.musicradio.com/globalplayer/brands"; headers = {'User-Agent': 'RadioXToSpotifyApp/1.0','Accept': 'application/vnd.global.8+json'}
    log_event(f"Fetching heraldId for {station_slug_to_find}...")
    try:
        response = requests.get(url, headers=headers, timeout=10); response.raise_for_status(); brands_data = response.json()
        if not isinstance(brands_data, list): logging.error("Brands API did not return a list."); return None
        for brand in brands_data:
            if brand.get('brandSlug', '').lower() == station_slug_to_find:
                herald_id = brand.get('heraldId')
                if herald_id: herald_id_cache[station_slug_to_find] = herald_id; return herald_id
        logging.warning(f"Could not find heraldId for slug '{station_slug_to_find}'.")
        return None
    except Exception as e: log_event(f"ERROR: Error fetching brands: {e}"); return None

def get_current_radiox_song(station_herald_id):
    global last_detected_song
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
        if not message_received: logging.info("No track update from WebSocket."); last_detected_song = None; return None
        now_playing = message_received.get('now_playing', {})
        title, artist, track_id_api = now_playing.get('title'), now_playing.get('artist'), now_playing.get('id')
        if title and artist:
            title, artist = title.strip(), artist.strip()
            if title and artist: 
                unique_id = track_id_api or f"{station_herald_id}_{title}_{artist}".replace(" ", "_")
                last_detected_song = {"title": title, "artist": artist, "id": unique_id}
                return last_detected_song
        last_detected_song = None
        return None
    except websocket.WebSocketTimeoutException: logging.warning("WebSocket timeout."); last_detected_song = None
    except Exception as e: logging.error(f"WebSocket error: {e}", exc_info=True); last_detected_song = None
    finally:
        if ws:
            try: ws.close()
            except: pass
    return None

def search_song_on_spotify(original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
    global daily_search_failures, sp
    if not sp: logging.error("Spotify not initialized for search."); return None
    search_attempts_details = []
    def _attempt_search_spotify(title_to_search, attempt_description):
        nonlocal search_attempts_details
        query = f"track:{title_to_search} artist:{artist}"
        try:
            results = spotify_api_call_with_retry(sp.search, q=query, type="track", limit=1)
            if results and results["tracks"]["items"]:
                track = results["tracks"]["items"][0]
                log_event(f"Found on Spotify ({attempt_description}): '{track['name']}'")
                return track["id"]
            else: search_attempts_details.append(f"Attempt '{attempt_description}': Not found."); return None
        except Exception as e:
            log_event(f"ERROR: Persistent network/API error during search for '{title_to_search}'.")
            if radiox_id_for_queue and not is_retry_from_queue: add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
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
    log_event(f"FAIL: Song '{original_title}' by '{artist}' not found after all attempts.")
    if not is_retry_from_queue: daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify after all attempts."})
    return None

def manage_playlist_size(playlist_id):
    global sp
    if not sp: return False
    try:
        playlist_details = spotify_api_call_with_retry(sp.playlist, playlist_id, fields='tracks.total')
        if not playlist_details: return False
        total_tracks = playlist_details['tracks']['total']
        log_event(f"Playlist size: {total_tracks}/{MAX_PLAYLIST_SIZE}")
        if total_tracks >= MAX_PLAYLIST_SIZE:
            log_event(f"Playlist at/over limit. Removing oldest song.")
            oldest_track_response = spotify_api_call_with_retry(sp.playlist_items, playlist_id, limit=1, offset=0, fields='items.track.uri')
            if oldest_track_response and oldest_track_response['items']:
                oldest_track_uri = oldest_track_response['items'][0]['track']['uri']
                spotify_api_call_with_retry(sp.playlist_remove_specific_occurrences_of_items, playlist_id, items=[{'uri': oldest_track_uri, 'positions': [0]}])
                log_event(f"Removed oldest song.")
                time.sleep(1)
                return True
            return False
    except Exception as e: logging.error(f"Error managing playlist size: {e}"); return False
    return True

def add_song_to_playlist(radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
    global sp, RECENTLY_ADDED_SPOTIFY_IDS, daily_added_songs, daily_search_failures
    if not sp: return False
    if spotify_track_id in RECENTLY_ADDED_SPOTIFY_IDS:
        log_event(f"Track '{radio_x_title}' recently processed. Skipping add.")
        return True
    if not manage_playlist_size(playlist_id_to_use):
        log_event("WARNING: Could not manage playlist size. Adding anyway.")
    try:
        track_details = spotify_api_call_with_retry(sp.track, spotify_track_id)
        if not track_details: raise Exception(f"Could not fetch details for track ID {spotify_track_id}")
        spotify_api_call_with_retry(sp.playlist_add_items, playlist_id_to_use, [spotify_track_id])
        
        spotify_name = track_details.get('name', 'Unknown'); spotify_artists_str = ", ".join([a.get('name', '') for a in track_details.get('artists', [])]); release_date = track_details.get('album', {}).get('release_date', 'N/A')
        album_art_url = track_details['album']['images'][1]['url'] if track_details.get('album', {}).get('images') and len(track_details['album']['images']) > 1 else None

        daily_added_songs.append({"timestamp": datetime.datetime.now(pytz.timezone(TIMEZONE)).isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "spotify_title": spotify_name, "spotify_artist": spotify_artists_str, "spotify_id": spotify_track_id, "release_date": release_date, "album_art_url": album_art_url})
        log_event(f"SUCCESS: Added '{BOLD}{radio_x_title}{RESET}' by '{BOLD}{radio_x_artist}{RESET}' to playlist.")
        RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id)
        return True
    except spotipy.SpotifyException as e:
        reason = f"API Error: HTTP {e.http_status} - {e.msg}"
        if e.http_status == 403 and "duplicate" in e.msg.lower(): 
             RECENTLY_ADDED_SPOTIFY_IDS.append(spotify_track_id); reason = "Spotify blocked add as duplicate (already in playlist)"
        else: logging.error(f"Error adding track '{radio_x_title}': {e}")
        daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": reason})
        return False
    except Exception as e:
        logging.error(f"Unexpected error adding track '{radio_x_title}': {e}")
        daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title, "radio_artist": radio_x_artist, "reason": f"Unexpected error during add: {e}"})
        return False

# ... other functions (check_and_remove_duplicates, etc.) ...
def check_and_remove_duplicates(playlist_id):
    global sp, RECENTLY_ADDED_SPOTIFY_IDS
    if not sp: return
    log_event("Starting periodic duplicate check...")
    try:
        all_tracks, offset, limit = [], 0, 100
        while True:
            results = spotify_api_call_with_retry(sp.playlist_items, playlist_id, limit=limit, offset=offset, fields="items(track(id,uri,name)),next")
            if not results or not results['items']: break
            for item in results['items']:
                if item.get('track') and item['track'].get('id'): all_tracks.append(item['track'])
            if results['next']: offset += 100
            else: break
        log_event(f"DUPLICATE_CLEANUP: Fetched {len(all_tracks)} tracks.")
        if not all_tracks: return
        track_counts = Counter(t['id'] for t in all_tracks if t['id'])
        for track_id, count in track_counts.items():
            if count > 1:
                track_uri = next((t['uri'] for t in all_tracks if t['id'] == track_id), None)
                track_name = next((t['name'] for t in all_tracks if t['id'] == track_id), "Unknown")
                if track_uri:
                    log_event(f"DUPLICATE_CLEANUP: Track '{track_name}' found {count} times. Re-processing.")
                    spotify_api_call_with_retry(sp.playlist_remove_all_occurrences_of_items, playlist_id, [track_uri])
                    time.sleep(0.5); spotify_api_call_with_retry(sp.playlist_add_items, playlist_id, [track_uri])
                    RECENTLY_ADDED_SPOTIFY_IDS.append(track_id)
                    time.sleep(1)
    except Exception as e: log_event(f"ERROR during duplicate cleanup: {e}")

def process_failed_search_queue():
    global failed_search_queue, daily_search_failures
    if not failed_search_queue: return
    log_event(f"PFSQ: Processing 1 item from queue (size: {len(failed_search_queue)}).")
    item = failed_search_queue.popleft()
    item['attempts'] += 1
    spotify_id = search_song_on_spotify(item['title'], item['artist'], is_retry_from_queue=True)
    if spotify_id:
        add_song_to_playlist(item['title'], item['artist'], spotify_id, SPOTIFY_PLAYLIST_ID)
    elif item['attempts'] < MAX_FAILED_SEARCH_ATTEMPTS:
        failed_search_queue.append(item)
        log_event(f"PFSQ: Re-queued '{item['title']}' (Attempts: {item['attempts']}).")
    else:
        log_event(f"PFSQ: Max retries reached for '{item['title']}'. Discarding.")
        daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": item['title'], "radio_artist": item['artist'], "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."})

def send_summary_email(html_body, subject):
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        log_event("Email settings not configured. Skipping email.")
        return False
    log_event(f"Attempting to send email to {EMAIL_RECIPIENT}...")
    try:
        port = int(EMAIL_PORT); msg = MIMEMultipart('alternative'); msg['Subject'] = subject; msg['From'] = EMAIL_HOST_USER; msg['To'] = EMAIL_RECIPIENT; msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP(EMAIL_HOST, port) as server:
            server.starttls(); server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD); server.send_message(msg)
        logging.info("Email sent successfully.")
        return True
    except Exception as e: logging.error(f"Failed to send email: {e}"); return False

def get_daily_stats_html():
    # ... same logic as before ...
    global daily_added_songs, daily_search_failures, failed_search_queue
    if not daily_added_songs and not daily_search_failures: return ""
    try:
        artist_counts = Counter(item['radio_artist'] for item in daily_added_songs)
        most_common = artist_counts.most_common(3)
        top_artists_str = ", ".join([f"{artist} ({count})" for artist, count in most_common]) if most_common else "N/A"
        unique_artist_count = len(artist_counts)
        failure_reasons = Counter(item['reason'] for item in daily_search_failures)
        failure_breakdown_str = "; ".join([f"{reason}: {count}" for reason, count in failure_reasons.items()]) or "None"
        total_processed = len(daily_added_songs) + len(daily_search_failures)
        success_rate = (len(daily_added_songs) / total_processed * 100) if total_processed > 0 else 100
        busiest_hour_str, newest_song_str, oldest_song_str, decade_breakdown_str = "N/A", "N/A", "N/A", ""
        if daily_added_songs:
            hour_counts = Counter(datetime.datetime.fromisoformat(item['timestamp']).hour for item in daily_added_songs)
            busiest_hour, song_count = hour_counts.most_common(1)[0]
            busiest_hour_str = f"{busiest_hour:02d}:00 - {busiest_hour:02d}:59 ({song_count} songs)"
            songs_with_dates = [s for s in daily_added_songs if s.get('release_date') and '-' in s['release_date']]
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
        <p><b>Success Rate:</b> {success_rate:.1f}%% ({len(daily_added_songs)} added / {total_processed} processed)<br>
        <b>Unique Artists Added:</b> {unique_artist_count}<br>
        <b>Top Artists:</b> {top_artists_str}<br>
        <b>Busiest Hour:</b> {busiest_hour_str}<br>
        <b>Oldest Song Added:</b> {oldest_song_str}<br>
        <b>Newest Song Added:</b> {newest_song_str}<br>
        <b>Decade Breakdown:</b> {decade_breakdown_str}<br>
        <b>Failure Breakdown:</b> {failure_breakdown_str}<br>
        <b>Items in Retry Queue at EOD:</b> {len(failed_search_queue)}</p>
        """
        return stats_html
    except Exception as e: logging.error(f"Could not generate daily stats: {e}"); return ""

def log_and_send_daily_summary():
    global last_summary_log_date
    summary_date = last_summary_log_date.isoformat()
    stats_html = get_daily_stats_html()
    html = f"""
    <html><head><style>body{{font-family:sans-serif;}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ddd;padding:8px}} th{{background-color:#f2f2f2}} h2{{border-bottom:2px solid #ccc;padding-bottom:5px}} h3{{margin-top:20px}}</style></head><body>
        <h2>Radio X Spotify Adder Daily Summary: {summary_date}</h2>{stats_html}<h2><b>ADDED (Total: {len(daily_added_songs)})</b></h2>
    """
    if daily_added_songs: html += "<table><tr><th>Title</th><th>Artist</th></tr>" + "".join([f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td></tr>" for item in daily_added_songs]) + "</table>"
    else: html += "<p>No songs were added today.</p>"
    html += f"<br><h2><b>FAILED (Total: {len(daily_search_failures)})</b></h2>"
    if daily_search_failures: html += "<table><tr><th>Title</th><th>Artist</th><th>Reason</th></tr>" + "".join([f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td><td>{item['reason']}</td></tr>" for item in daily_search_failures]) + "</table>"
    else: html += "<p>No unresolved failures today.</p>"
    html += "</body></html>"
    send_summary_email(html, subject=f"Radio X Spotify Adder Daily Summary - {summary_date}")
    daily_added_songs.clear(); daily_search_failures.clear(); save_state()

def run_startup_diagnostics(send_email=False):
    # ... same logic as before ...
    log_event("--- Running Startup Diagnostics ---")
    results = []
    try:
        if sp: results.append("<tr><td>Spotify Authentication</td><td style='color:green;'>SUCCESS</td><td>Authenticated successfully.</td></tr>")
        else: raise Exception("Spotify client not initialized.")
        playlist = spotify_api_call_with_retry(sp.playlist, SPOTIFY_PLAYLIST_ID, fields='name,id'); results.append(f"<tr><td>Playlist Access</td><td style='color:green;'>SUCCESS</td><td>Accessed playlist '{playlist['name']}'.</td></tr>")
        if search_song_on_spotify("Wonderwall", "Oasis"): results.append("<tr><td>Test Search</td><td style='color:green;'>SUCCESS</td><td>Test search for 'Wonderwall' was successful.</td></tr>")
        else: results.append("<tr><td>Test Search</td><td style='color:red;'>FAIL</td><td>Test search for 'Wonderwall' returned no results.</td></tr>")
        tz = pytz.timezone(TIMEZONE); now = datetime.datetime.now(tz).strftime('%Z'); results.append(f"<tr><td>Timezone Check</td><td style='color:green;'>SUCCESS</td><td>Timezone '{TIMEZONE}' loaded (Current: {now}).</td></tr>")
        if all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]): results.append("<tr><td>Email Configuration</td><td style='color:green;'>SUCCESS</td><td>All email environment variables are set.</td></tr>")
        else: results.append("<tr><td>Email Configuration</td><td style='color:orange;'>WARNING</td><td>One or more email environment variables are missing.</td></tr>")
    except Exception as e:
        results.append(f"<tr><td colspan='3' style='color:red;'>A diagnostic check failed critically: {e}</td></tr>")
    if send_email:
        send_summary_email("".join(results), subject="On-Demand Diagnostic Report")

# --- Main Application Loop ---
def run_radio_monitor():
    # ... main loop logic ...
    global last_added_radiox_track_id, last_duplicate_check_time, last_summary_log_date, startup_email_sent, shutdown_summary_sent, current_station_herald_id
    log_event("--- run_radio_monitor thread initiated. ---")
    if not sp: log_event("ERROR: Spotify client is None. Thread cannot perform Spotify actions."); return
    if last_summary_log_date is None: last_summary_log_date = datetime.date.today()
    while True:
        try:
            now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
            if last_summary_log_date < now_local.date():
                log_event(f"New day detected ({now_local.date().isoformat()}). Resetting daily flags.")
                startup_email_sent, shutdown_summary_sent = False, False
                daily_added_songs.clear(); daily_search_failures.clear(); save_state()
                last_summary_log_date = now_local.date()
            if START_TIME <= now_local.time() <= END_TIME:
                if not startup_email_sent:
                    log_event("Active hours started."); startup_email_sent = True; shutdown_summary_sent = False
                process_main_cycle()
            else:
                log_event(f"Outside of active hours. Pausing...")
                if not shutdown_summary_sent:
                    log_event("End of active day. Generating and sending daily summary."); log_and_send_daily_summary(); shutdown_summary_sent = True; startup_email_sent = False
                time.sleep(CHECK_INTERVAL * 5); continue
        except Exception as e: logging.error(f"CRITICAL UNHANDLED ERROR in main loop: {e}", exc_info=True); time.sleep(CHECK_INTERVAL * 2) 
        log_event(f"Cycle complete. Waiting {CHECK_INTERVAL}s..."); time.sleep(CHECK_INTERVAL)

def process_main_cycle():
    global current_station_herald_id, last_added_radiox_track_id, last_duplicate_check_time
    if not current_station_herald_id: current_station_herald_id = get_station_herald_id(RADIOX_STATION_SLUG)
    if not current_station_herald_id: return
    current_song_info = get_current_radiox_song(current_station_herald_id)
    song_added = False
    if current_song_info:
        title, artist, radiox_id = current_song_info["title"], current_song_info["artist"], current_song_info["id"]
        if not title or not artist: logging.warning("Empty title or artist from Radio X.")
        elif radiox_id == last_added_radiox_track_id: logging.info(f"Song '{title}' by '{artist}' (ID: {radiox_id}) same as last. Skipping.")
        else:
            log_event(f"New song: '{title}' by '{artist}'")
            spotify_track_id = search_song_on_spotify(title, artist, radiox_id) 
            if spotify_track_id:
                if add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID): song_added = True 
            last_added_radiox_track_id = radiox_id 
    else: log_event("No new track info from Radio X.")
    if failed_search_queue and (song_added or (time.time() % (CHECK_INTERVAL * 4) < CHECK_INTERVAL)): process_failed_search_queue()
    current_time = time.time()
    if current_time - last_duplicate_check_time >= DUPLICATE_CHECK_INTERVAL:
        check_and_remove_duplicates(SPOTIFY_PLAYLIST_ID); last_duplicate_check_time = current_time
    save_state()

# --- Flask Routes & Script Execution ---
@app.route('/force_duplicates')
def force_duplicates():
    log_event("Duplicate check manually triggered via web.")
    threading.Thread(target=check_and_remove_duplicates, args=(SPOTIFY_PLAYLIST_ID,)).start()
    return "Duplicate check has been triggered. Check logs for progress."

# ... (other routes) ...

@app.route('/')
def index_page():
    return render_template('index.html', active_hours=f"{START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}")

def initialize_bot():
    """Handles the slow startup tasks in the background."""
    if authenticate_spotify():
        load_state() 
        run_startup_diagnostics() # No email on auto-start
        monitor_thread = threading.Thread(target=run_radio_monitor, daemon=True)
        monitor_thread.start()
    else:
        logging.critical("Spotify authentication failed. The main monitoring thread will not start.")

# --- Script Execution ---
if __name__ == "__main__":
    initialize_bot()
    port = int(os.environ.get("PORT", 8080)) 
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) 
else:
    threading.Thread(target=initialize_bot, daemon=True).start()
