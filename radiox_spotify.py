# Radio X to Spotify Playlist Adder
# v4.6 - Full Featured with Scope Fix for Daily Notifications
# Includes: Time-windowed operation, playlist size limit, daily HTML email summaries,
#           robust networking, failed search queue, and improved title cleaning.

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
from flask import Flask 
import datetime
import pytz # For timezone-aware time checks
import smtplib # For sending email summaries
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart # For HTML emails

# --- Flask App Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return "RadioX to Spotify script is running in the background. Status: OK"

# --- Configuration ---
# Spotify settings are hardcoded. Email settings MUST be set via environment variables.
SPOTIPY_CLIENT_ID = "89c7e2957a7e465a8eeb9d2476a82a2d"
SPOTIPY_CLIENT_SECRET = "f8dc109892b9464ab44fba3b2502a7eb"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback" 
SPOTIFY_PLAYLIST_ID = "5i13fDRDoW0gu60f74cysp" 
RADIOX_STATION_SLUG = "radiox" 

# Script Operation Settings
CHECK_INTERVAL = 120  
DUPLICATE_CHECK_INTERVAL = 30 * 60 
MAX_PLAYLIST_SIZE = 500
MAX_FAILED_SEARCH_QUEUE_SIZE = 20 
MAX_FAILED_SEARCH_ATTEMPTS = 3    

# Active Time Window (BST/GMT Aware)
TIMEZONE = 'Europe/London'
START_TIME = datetime.time(7, 30)
END_TIME = datetime.time(22, 0)

# Email Summary Settings (read from environment)
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = os.getenv("EMAIL_PORT") 
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

BOLD = '\033[1m'
RESET = '\033[0m'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not all([SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, SPOTIFY_PLAYLIST_ID]):
    logging.critical("CRITICAL ERROR: Spotify configuration values are missing.")
else:
    logging.info("Spotify configuration loaded.")

# --- Global Variables ---
last_added_radiox_track_id = None
RECENTLY_ADDED_SPOTIFY_TRACK_IDS = set()
MAX_RECENT_TRACKS = 50
sp = None 
herald_id_cache = {} 
last_duplicate_check_time = 0
failed_search_queue = [] 

# For Daily Summary and Notifications
daily_added_songs = [] 
daily_search_failures = [] 
last_summary_log_date = None # Tracks the current day to know when to reset flags
startup_email_sent = False
shutdown_summary_sent = False

# --- Spotify Authentication & Cache ---
SPOTIPY_CACHE_CONTENTS_ENV_VAR = "SPOTIPY_CACHE_BASE64"
SPOTIPY_CACHE_FILENAME = ".spotipy_cache"

def write_spotipy_cache():
    cache_content_b64 = os.getenv(SPOTIPY_CACHE_CONTENTS_ENV_VAR)
    if cache_content_b64:
        try:
            import base64
            cache_content_json = base64.b64decode(cache_content_b64).decode('utf-8')
            with open(SPOTIPY_CACHE_FILENAME, 'w') as f:
                f.write(cache_content_json)
            logging.info(f"Successfully wrote decoded Spotify cache to {SPOTIPY_CACHE_FILENAME}")
            return True
        except Exception as e:
            logging.error(f"Error decoding/writing Spotify cache from environment variable: {e}")
            return False
    else:
        logging.info(f"{SPOTIPY_CACHE_CONTENTS_ENV_VAR} not set. Local auth flow may be needed.")
        return False

scope = "playlist-modify-public playlist-modify-private user-library-read"
try:
    cache_written = write_spotipy_cache()
    auth_manager = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET,
                                redirect_uri=SPOTIPY_REDIRECT_URI, scope=scope, 
                                cache_path=SPOTIPY_CACHE_FILENAME) 
    token_info = auth_manager.get_cached_token()
    if not token_info and not cache_written:
        logging.warning("No cached Spotify token and no cache from ENV. On a server, this will likely prevent Spotify features from working as interactive auth is not possible.")
    if token_info:
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user = sp.current_user() 
        if user:
            logging.info(f"Successfully authenticated with Spotify as {user['display_name']} ({user['id']})")
        else:
            sp = None 
            logging.error("Could not get current Spotify user details even with a token. Token might be invalid/expired or cache is stale.")
    else:
        sp = None 
        logging.error("Failed to obtain Spotify token (no valid cache and no interactive auth possible on server).")
except Exception as e:
    sp = None 
    logging.critical(f"CRITICAL Error during Spotify Authentication Setup: {e}", exc_info=True)

# --- Utility Functions ---

def spotify_api_call_with_retry(func, *args, **kwargs):
    max_retries = 3
    base_delay = 5  
    retryable_spotify_exceptions = (500, 502, 503, 504) 

    last_exception = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
            last_exception = e
            logging.warning(f"Network error on {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = base_delay * (2 ** attempt) 
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"Network error on {func.__name__} failed after {max_retries} attempts.")
                raise  
        except spotipy.SpotifyException as e:
            last_exception = e
            logging.warning(f"Spotify API Exception on {func.__name__} (attempt {attempt + 1}/{max_retries}): HTTP {e.http_status} - {e.msg}")
            if e.http_status == 429: 
                retry_after_header = e.headers.get('Retry-After')
                retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else (base_delay * (2**attempt))
                logging.info(f"Rate limited. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            elif e.http_status in retryable_spotify_exceptions: 
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    logging.info(f"Spotify server error ({e.http_status}). Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logging.error(f"Spotify server error on {func.__name__} ({e.http_status}) failed after {max_retries} attempts.")
                    raise 
            else: 
                raise e 
    if last_exception:
        raise last_exception
    raise Exception(f"{func.__name__} failed after all retries for network/server issues without specific re-raise.")


def add_to_failed_search_queue(title, artist, radiox_id):
    global failed_search_queue
    if len(failed_search_queue) < MAX_FAILED_SEARCH_QUEUE_SIZE:
        for item in failed_search_queue:
            if item['radiox_id'] == radiox_id:
                logging.debug(f"Item with RadioX ID {radiox_id} already in failed search queue.")
                return
        logging.info(f"Adding to failed search queue: '{title}' by '{artist}' (RadioX ID: {radiox_id})")
        failed_search_queue.append({'title': title, 'artist': artist, 'radiox_id': radiox_id, 'attempts': 0})
    else:
        logging.warning(f"Failed search queue is full ({MAX_FAILED_SEARCH_QUEUE_SIZE}). Cannot add '{title}'.")

def get_spotify_track_details_for_log(track_id):
    if not sp or not track_id:
        return "Unknown Spotify Title", "Unknown Spotify Artist"
    try:
        track_info = spotify_api_call_with_retry(sp.track, track_id)
        if track_info:
            name = track_info.get('name', "Unknown Spotify Title")
            artists = ", ".join([a.get('name', "Unknown Artist") for a in track_info.get('artists', [])])
            return name, artists
    except Exception as e:
        logging.warning(f"Could not fetch details for Spotify track ID {track_id} for summary log: {e}")
    return "Unknown Spotify Title", "Unknown Spotify Artist"


def get_station_herald_id(station_slug_to_find):
    if station_slug_to_find in herald_id_cache:
        return herald_id_cache[station_slug_to_find]
    global_player_brands_url = "https://bff-web-guacamole.musicradio.com/globalplayer/brands"
    headers = {'User-Agent': 'RadioXToSpotifyApp/1.0','Accept': 'application/vnd.global.8+json'}
    logging.info(f"Fetching heraldId for {station_slug_to_find} from {global_player_brands_url}")
    try:
        response = requests.get(global_player_brands_url, headers=headers, timeout=10)
        response.raise_for_status()
        brands_data = response.json()
        if not isinstance(brands_data, list): logging.error("Brands API did not return a list."); return None
        for brand in brands_data:
            if brand.get('brandSlug', '').lower() == station_slug_to_find:
                herald_id = brand.get('heraldId')
                if herald_id: 
                    herald_id_cache[station_slug_to_find] = herald_id
                    return herald_id
        logging.warning(f"Could not find heraldId for slug '{station_slug_to_find}'.")
        return None
    except requests.exceptions.RequestException as e: logging.error(f"Error fetching brands: {e}"); return None
    except Exception as e: logging.error(f"Error parsing brands JSON: {e}"); return None


def get_current_radiox_song(station_herald_id):
    if not station_herald_id: logging.error("No station_herald_id provided."); return None
    websocket_url = "wss://metadata.musicradio.com/v2/now-playing"
    logging.info(f"Connecting to WebSocket: {websocket_url} for heraldId: {station_herald_id}")
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
        if not message_received: logging.info(f"No track update for heraldId {station_herald_id}."); return None
        now_playing = message_received.get('now_playing', {})
        title, artist, track_id_api = now_playing.get('title'), now_playing.get('artist'), now_playing.get('id')
        if title and artist:
            title, artist = title.strip(), artist.strip()
            if title and artist: 
                unique_id = track_id_api or f"{station_herald_id}_{title}_{artist}".replace(" ", "_")
                logging.info(f"Radio X Now Playing: {title} by {artist}")
                return {"title": title, "artist": artist, "id": unique_id}
        logging.info(f"Could not extract info from WebSocket for {station_herald_id}.")
        return None
    except websocket.WebSocketTimeoutException: logging.warning(f"WebSocket timeout for heraldId {station_herald_id}")
    except Exception as e: logging.error(f"WebSocket error for heraldId {station_herald_id}: {e}", exc_info=True)
    finally:
        if ws:
            try:
                ws.close()
                logging.debug("WebSocket closed.")
            except Exception as e_ws_close:
                logging.error(f"Error closing WebSocket: {e_ws_close}")
    return None

def search_song_on_spotify(original_title, artist, radiox_id_for_queue=None, is_retry_from_queue=False):
    global daily_search_failures
    if not sp: 
        logging.error("Spotify not initialized for search.")
        return None
    
    search_attempts_details = []
    
    def _attempt_search_spotify(title_to_search, attempt_description):
        nonlocal search_attempts_details
        logging.debug(f"Spotify search ({attempt_description}): Title='{title_to_search}', Artist='{artist}'")
        query = f"track:{title_to_search} artist:{artist}"
        try:
            results = spotify_api_call_with_retry(sp.search, q=query, type="track", limit=1)
            if results and results["tracks"]["items"]:
                track = results["tracks"]["items"][0]
                logging.info(f"Found on Spotify ({attempt_description}): '{track['name']}' by {', '.join(a['name'] for a in track['artists'])} (ID: {track['id']})")
                return track["id"]
            else:
                search_attempts_details.append(f"Attempt '{attempt_description}': Not found via API (empty result).")
                return None
        except Exception as e:
            logging.error(f"Persistent network/Spotify error during {attempt_description} for '{title_to_search}' after all retries: {e}")
            if radiox_id_for_queue and not is_retry_from_queue:
                add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
            return "NETWORK_ERROR_FLAG"

    spotify_id = _attempt_search_spotify(original_title, "original title")
    if spotify_id == "NETWORK_ERROR_FLAG":
        if not is_retry_from_queue:
             daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Search failed due to persistent network/API error (queued)."})
        return None 
    if spotify_id: return spotify_id

    cleaned_title = re.sub(r'\s*\(.*?\)\s*', ' ', original_title) 
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()

    if cleaned_title and cleaned_title.lower() != original_title.lower():
        logging.info(f"Original title search failed. Retrying with cleaned title: '{cleaned_title}'")
        spotify_id = _attempt_search_spotify(cleaned_title, "cleaned title")
        if spotify_id == "NETWORK_ERROR_FLAG":
            if not is_retry_from_queue:
                 daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": f"Search with cleaned title ('{cleaned_title}') failed (queued)."})
            return None
        if spotify_id: return spotify_id
    else:
        if not cleaned_title: search_attempts_details.append("Title became empty after cleaning.")
        else: search_attempts_details.append("No significant change to title after cleaning.")
    
    logging.info(f"Song '{original_title}' by '{artist}' definitively not found on Spotify. Details: [{'; '.join(search_attempts_details)}]")
    if not is_retry_from_queue:
        daily_search_failures.append({"timestamp": datetime.datetime.now().isoformat(), "radio_title": original_title, "radio_artist": artist, "reason": "Not found on Spotify after all attempts."})
    return None

def manage_playlist_size(playlist_id):
    if not sp: return False
    try:
        playlist_details = spotify_api_call_with_retry(sp.playlist, playlist_id, fields='tracks.total')
        if not playlist_details: return False

        total_tracks = playlist_details['tracks']['total']
        logging.info(f"Current playlist size: {total_tracks} tracks.")

        if total_tracks >= MAX_PLAYLIST_SIZE:
            logging.warning(f"Playlist size ({total_tracks}) is at/over the limit of {MAX_PLAYLIST_SIZE}. Removing oldest song.")
            oldest_track_response = spotify_api_call_with_retry(sp.playlist_items, playlist_id, limit=1, offset=0, fields='items.track.uri')
            if oldest_track_response and oldest_track_response['items']:
                oldest_track_uri = oldest_track_response['items'][0]['track']['uri']
                spotify_api_call_with_retry(sp.playlist_remove_specific_occurrences_of_items, playlist_id, items=[{'uri': oldest_track_uri, 'positions': [0]}])
                logging.info(f"Removed oldest song from playlist (URI: {oldest_track_uri}).")
                time.sleep(1) 
                return True
            else:
                logging.error("Could not fetch the oldest track to remove it.")
                return False
    except Exception as e:
        logging.error(f"Error managing playlist size: {e}")
        return False
    return True


def add_song_to_playlist(radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
    global RECENTLY_ADDED_SPOTIFY_TRACK_IDS, daily_added_songs, daily_search_failures
    if not sp: logging.error("Spotify not initialized for adding to playlist."); return False
    if not spotify_track_id or not playlist_id_to_use: logging.error("Missing track/playlist ID."); return False
    
    if spotify_track_id in RECENTLY_ADDED_SPOTIFY_TRACK_IDS:
        logging.info(f"Track ID {spotify_track_id} ('{radio_x_title}') was recently processed. Skipping add_song_to_playlist.")
        return True 

    if not manage_playlist_size(playlist_id_to_use):
        logging.warning("Could not manage playlist size. Will attempt to add song anyway.")

    try:
        spotify_api_call_with_retry(sp.playlist_add_items, playlist_id_to_use, [spotify_track_id])
        
        spotify_name, spotify_artists_str = get_spotify_track_details_for_log(spotify_track_id)
        
        daily_added_songs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "radio_title": radio_x_title, "radio_artist": radio_x_artist, 
            "spotify_title": spotify_name, "spotify_artist": spotify_artists_str,
            "spotify_id": spotify_track_id
        })
        logging.info(f"SUCCESS: Added '{BOLD}{radio_x_title}{RESET}' by '{BOLD}{radio_x_artist}{RESET}' (as '{spotify_name}' by '{spotify_artists_str}') to playlist (ID: {spotify_track_id}).")

        RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(spotify_track_id)
        if len(RECENTLY_ADDED_SPOTIFY_TRACK_IDS) > MAX_RECENT_TRACKS:
            try:
                oldest_track = next(iter(RECENTLY_ADDED_SPOTIFY_TRACK_IDS))
                RECENTLY_ADDED_SPOTIFY_TRACK_IDS.remove(oldest_track)
                logging.debug(f"Removed {oldest_track} from recent tracks cache.")
            except (StopIteration, KeyError): pass
        return True
    except spotipy.SpotifyException as e:
        reason_for_fail_log = f"Spotify API Error when adding: HTTP {e.http_status} - {e.msg}"
        if e.http_status == 403 and "duplicate" in e.msg.lower(): 
             logging.warning(f"Could not add track ID {spotify_track_id} ('{radio_x_title}') (Spotify API indicated duplicate): {e.msg}")
             RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(spotify_track_id)
             reason_for_fail_log = "Spotify blocked add as duplicate (already in playlist)"
        else: 
            logging.error(f"Error adding track {spotify_track_id} ('{radio_x_title}') to playlist: {e}")
        daily_search_failures.append({
            "timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title,
            "radio_artist": radio_x_artist, "reason": reason_for_fail_log
        })
        return False
    except Exception as e: 
        logging.error(f"Unexpected error adding track {spotify_track_id} ('{radio_x_title}') after retries: {e}")
        daily_search_failures.append({
            "timestamp": datetime.datetime.now().isoformat(), "radio_title": radio_x_title,
            "radio_artist": radio_x_artist, "reason": f"Unexpected error during add: {e}"
        })
        return False

def check_and_remove_duplicates(playlist_id):
    if not sp: logging.error("Spotify not initialized for duplicates check."); return
    logging.info(f"Starting duplicate cleanup (remove-all & re-add strategy) for playlist: {playlist_id}")
    all_playlist_tracks_info = [] 
    offset, limit = 0, 50 
    try:
        while True:
            results = spotify_api_call_with_retry(sp.playlist_items, playlist_id, limit=limit, offset=offset, fields="items(track(id,uri,name)),next")
            if not results: 
                logging.error("DUPLICATE_CLEANUP: Failed to fetch playlist items. Aborting duplicate check."); return
            if not results['items']: break
            for item in results['items']: 
                if item.get('track') and item['track'].get('id') and item['track'].get('uri'):
                    all_playlist_tracks_info.append({'uri': item['track']['uri'], 'id': item['track']['id'], 'name': item['track'].get('name', 'Unknown Track')})
            if results['next']: offset += len(results['items']) 
            else: break
        
        logging.info(f"DUPLICATE_CLEANUP: Fetched {len(all_playlist_tracks_info)} tracks.")
        if not all_playlist_tracks_info: return

        track_counts = {} 
        for item in all_playlist_tracks_info:
            if item['id']:
                if item['id'] not in track_counts: track_counts[item['id']] = {'uri': item['uri'], 'name': item['name'], 'count': 0}
                track_counts[item['id']]['count'] += 1
        
        processed_count = 0
        for track_id, data in track_counts.items():
            if data['count'] > 1:
                processed_count +=1
                name, uri = data['name'], data['uri']
                logging.info(f"DUPLICATE_CLEANUP: Track '{BOLD}{name}{RESET}' found {data['count']} times. Removing all and re-adding one.")
                try:
                    spotify_api_call_with_retry(sp.playlist_remove_all_occurrences_of_items, playlist_id, [uri])
                    time.sleep(0.5) 
                    spotify_api_call_with_retry(sp.playlist_add_items, playlist_id, [uri])
                    logging.info(f"  DUPLICATE_CLEANUP: Successfully re-processed '{BOLD}{name}{RESET}'.")
                    RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(track_id) 
                    time.sleep(1) 
                except Exception as e: logging.error(f"DUPLICATE_CLEANUP: Error for URI {uri}: {e}")
        
        if processed_count > 0: logging.info(f"DUPLICATE_CLEANUP: Finished processing {processed_count} duplicated tracks.")
        else: logging.info("DUPLICATE_CLEANUP: No tracks found with multiple occurrences.")
    except Exception as e: logging.error(f"Error during duplicate cleanup: {e}", exc_info=True)


def process_failed_search_queue():
    global failed_search_queue, daily_search_failures
    if not sp or not failed_search_queue: return

    logging.info(f"PFSQ: Processing up to 1 item from failed search queue (size: {len(failed_search_queue)}).")
    
    item_to_retry = failed_search_queue[0] 
    title, artist, radiox_id, attempts = item_to_retry['title'], item_to_retry['artist'], item_to_retry['radiox_id'], item_to_retry['attempts']

    logging.info(f"PFSQ: Retrying search for '{title}' by '{artist}' (RadioX ID: {radiox_id}, Attempt: {attempts + 1})")
    
    spotify_track_id = search_song_on_spotify(title, artist, is_retry_from_queue=True) 
    
    if spotify_track_id:
        if add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID):
            failed_search_queue.pop(0) 
    else: 
        failed_search_queue[0]['attempts'] += 1
        if failed_search_queue[0]['attempts'] >= MAX_FAILED_SEARCH_ATTEMPTS:
            logging.error(f"PFSQ: Max retries reached for '{title}'. Discarding from queue.")
            item_discarded = failed_search_queue.pop(0) 
            daily_search_failures.append({
                "timestamp": datetime.datetime.now().isoformat(), "radio_title": item_discarded['title'], "radio_artist": item_discarded['artist'],
                "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."
            })
        else:
            updated_item = failed_search_queue.pop(0)
            failed_search_queue.append(updated_item)
            logging.info(f"PFSQ: Re-queued '{title}' for another attempt later (Attempts made: {item_to_retry['attempts']}).")

def send_summary_email(html_body, subject):
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        logging.info("Email settings not configured in environment variables. Skipping email summary.")
        return

    logging.info(f"Attempting to send summary email to {EMAIL_RECIPIENT}...")
    
    try:
        port = int(EMAIL_PORT)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_HOST_USER
        msg['To'] = EMAIL_RECIPIENT
        
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(EMAIL_HOST, port) as server:
            server.starttls()
            server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
            server.send_message(msg)
            logging.info("Summary email sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send summary email: {e}")

def log_daily_summary():
    global daily_added_songs, daily_search_failures, last_summary_log_date
    
    summary_date = last_summary_log_date.isoformat() if last_summary_log_date else (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    
    # CORRECTED: Escaped curly braces for CSS in f-string
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: sans-serif; line-height: 1.5; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            h2 {{ border-bottom: 2px solid #ccc; padding-bottom: 5px; }}
        </style>
    </head>
    <body>
        <h2>Radio X Spotify Adder Daily Summary: {summary_date}</h2>
        <h2><b>ADDED (Total: {len(daily_added_songs)})</b></h2>
    """

    if daily_added_songs:
        html += "<table><tr><th>Title</th><th>Artist</th></tr>"
        for item in daily_added_songs:
            html += f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td></tr>"
        html += "</table>"
    else:
        html += "<p>No songs were successfully added to Spotify today.</p>"
        
    html += f"<br><h2><b>FAILED (Total: {len(daily_search_failures)})</b></h2>"
    if daily_search_failures:
        html += "<table><tr><th>Title</th><th>Artist</th><th>Reason for Failure</th></tr>"
        for item in daily_search_failures:
            html += f"<tr><td>{item['radio_title']}</td><td>{item['radio_artist']}</td><td>{item['reason']}</td></tr>"
        html += "</table>"
    else:
        html += "<p>No un-resolved search/add failures were recorded today.</p>"
        
    html += "</body></html>"

    console_summary_lines = [f"--- DAILY SONG SUMMARY ({summary_date}) ---"]
    if daily_added_songs:
        console_summary_lines.append(f"\nADDED ({len(daily_added_songs)}):")
        for item in daily_added_songs: console_summary_lines.append(f"  - {item['radio_title']} | {item['radio_artist']}")
    if daily_search_failures:
        console_summary_lines.append(f"\nFAILED ({len(daily_search_failures)}):")
        for item in daily_search_failures: console_summary_lines.append(f"  - {item['radio_title']} | {item['radio_artist']} | {item['reason']}")
    logging.info("\n".join(console_summary_lines))
    
    email_subject = f"Radio X Spotify Adder Daily Summary - {summary_date}"
    send_summary_email(html, subject=email_subject)
    
    daily_added_songs.clear()
    daily_search_failures.clear()

def send_startup_notification():
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        logging.info("Email settings not configured. Skipping startup notification.")
        return

    logging.info("Sending startup notification email...")
    
    now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
    subject = f"Radio X Spotify Adder Service Started"
    
    # CORRECTED: Escaped curly braces for CSS in f-string
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: sans-serif; }}
        </style>
    </head>
    <body>
        <h2>Radio X Spotify Adder: Service Active</h2>
        <p>The script has entered its active monitoring window and has started running.</p>
        <p><b>Time:</b> {now_local.strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    </body>
    </html>
    """
    send_summary_email(html_body, subject=subject)

def run_radio_monitor():
    global last_added_radiox_track_id, last_duplicate_check_time, last_summary_log_date
    global startup_email_sent, shutdown_summary_sent
    
    print("DEBUG: run_radio_monitor thread function initiated.") 
    logging.info("--- run_radio_monitor thread initiated. ---") 
    
    if not sp: logging.error("Spotify client 'sp' is None. Thread cannot perform Spotify actions."); return
    
    logging.info(f"Monitoring Radio X. Active hours: {START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')} ({TIMEZONE})")

    if last_summary_log_date is None: 
        last_summary_log_date = datetime.date.today()

    current_station_herald_id = None
    
    while True:
        try:
            now_local = datetime.datetime.now(pytz.timezone(TIMEZONE))
            
            # --- Daily Flag Reset ---
            if last_summary_log_date < now_local.date():
                logging.info(f"New day detected ({now_local.date().isoformat()}). Resetting daily flags and summary data.")
                startup_email_sent = False
                shutdown_summary_sent = False
                # If shutdown summary was missed (e.g. script was down at 22:00), log previous day's summary now.
                if daily_added_songs or daily_search_failures:
                    logging.warning(f"Logging summary for previous day ({last_summary_log_date.isoformat()}) which was missed.")
                    log_daily_summary()
                last_summary_log_date = now_local.date()

            # --- Active/Inactive Logic ---
            if START_TIME <= now_local.time() <= END_TIME:
                if not startup_email_sent:
                    logging.info("Active hours started. Sending startup notification.")
                    send_startup_notification()
                    startup_email_sent = True
                    shutdown_summary_sent = False # Reset for the end of the day

                logging.debug(f"Loop start. Last RadioX ID: {last_added_radiox_track_id}. Failed queue: {len(failed_search_queue)}")
                if not current_station_herald_id:
                    current_station_herald_id = get_station_herald_id(RADIOX_STATION_SLUG)
                    if not current_station_herald_id: time.sleep(CHECK_INTERVAL); continue
                
                if not sp: logging.warning("Spotify client 'sp' is None. Skipping operations."); time.sleep(CHECK_INTERVAL); continue

                current_song_info = get_current_radiox_song(current_station_herald_id)
                song_added_from_radio = False

                if current_song_info and current_song_info.get("title") and current_song_info.get("artist"):
                    title, artist, radiox_id = current_song_info["title"], current_song_info["artist"], current_song_info["id"]

                    if not title or not artist: logging.warning("Empty title or artist from Radio X.")
                    elif radiox_id == last_added_radiox_track_id: logging.info(f"Song '{title}' by '{artist}' (RadioX ID: {radiox_id}) same as last. Skipping.")
                    else:
                        logging.info(f"New song from Radio X: '{title}' by '{artist}' (RadioX ID: {radiox_id})")
                        spotify_track_id = search_song_on_spotify(title, artist, radiox_id) 
                        if spotify_track_id:
                            if add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID):
                                song_added_from_radio = True 
                        last_added_radiox_track_id = radiox_id 
                else:
                    logging.info("No new track information from Radio X this cycle.")
                
                if failed_search_queue and (song_added_from_radio or (time.time() % (CHECK_INTERVAL * 4) < CHECK_INTERVAL)): 
                     process_failed_search_queue()

                current_time = time.time()
                if current_time - last_duplicate_check_time >= DUPLICATE_CHECK_INTERVAL:
                    logging.info("--- Starting periodic duplicate check ---")
                    if sp: check_and_remove_duplicates(SPOTIFY_PLAYLIST_ID)
                    else: logging.warning("Spotify not initialized. Skipping duplicate check.")
                    last_duplicate_check_time = current_time
                    logging.info("--- Finished periodic duplicate check ---")
            
            else: # Outside of active hours
                logging.info(f"Outside of active hours ({START_TIME.strftime('%H:%M')} - {END_TIME.strftime('%H:%M')}). Pausing...")
                if not shutdown_summary_sent:
                    logging.info("End of active day. Generating and sending daily summary.")
                    log_daily_summary() 
                    shutdown_summary_sent = True
                    startup_email_sent = False # Reset for the next morning
                
                time.sleep(CHECK_INTERVAL * 2)
                continue # Skip the normal sleep at the end of the loop

        except Exception as e:
            logging.error(f"CRITICAL UNHANDLED ERROR in run_radio_monitor loop: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL * 2) 

        logging.info(f"Cycle complete. Waiting for {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)

def start_monitoring_thread():
    if not hasattr(start_monitoring_thread, "thread_started") or not start_monitoring_thread.thread_started:
        if not sp: 
            logging.error("Spotify client not initialized. Background thread will NOT be started.")
            return

        logging.info("Preparing to start monitor_thread.")
        monitor_thread = threading.Thread(target=run_radio_monitor, daemon=True)
        monitor_thread.start()
        start_monitoring_thread.thread_started = True 
        logging.info("Monitor thread started.")
    else:
        logging.info("Monitor thread already started.")

if sp: 
    start_monitoring_thread()
else:
    logging.error("Spotify auth failed. Background monitor thread NOT started.")

if __name__ == "__main__":
    logging.info("Script being run directly (e.g., local testing).")
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_RECIPIENT]):
        print("\\nWARNING: Email environment variables not set. The daily summary will be logged to console only.\\n")
    port = int(os.environ.get("PORT", 8080)) 
    logging.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) 
