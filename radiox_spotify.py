# Radio X to Spotify Playlist Adder
# Includes: WebSocket for Radio X, duplicate checking (remove-all & re-add),
# title cleaning for Spotify search, network robustness with retries,
# failed search queue, and daily summary logging.

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
import datetime # For daily summary

# --- Flask App Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return "RadioX to Spotify script is running in the background. Status: OK"

# --- Configuration (HARDCODED) ---
SPOTIPY_CLIENT_ID = "89c7e2957a7e465a8eeb9d2476a82a2d"
SPOTIPY_CLIENT_SECRET = "f8dc109892b9464ab44fba3b2502a7eb"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback" 
SPOTIFY_PLAYLIST_ID = "5i13fDRDoW0gu60f74cysp" 
RADIOX_STATION_SLUG = "radiox" 

CHECK_INTERVAL = 120  
DUPLICATE_CHECK_INTERVAL = 30 * 60 
MAX_FAILED_SEARCH_QUEUE_SIZE = 20 
MAX_FAILED_SEARCH_ATTEMPTS = 3    

BOLD = '\033[1m'
RESET = '\033[0m'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not all([SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, SPOTIFY_PLAYLIST_ID, RADIOX_STATION_SLUG]):
    logging.critical("CRITICAL ERROR: Hardcoded configuration values are missing.")
else:
    logging.info("Successfully using hardcoded configuration.")

# --- Global Variables ---
last_added_radiox_track_id = None
RECENTLY_ADDED_SPOTIFY_TRACK_IDS = set()
MAX_RECENT_TRACKS = 50
sp = None 
herald_id_cache = {} 
last_duplicate_check_time = 0
failed_search_queue = [] 

daily_added_songs = [] 
daily_search_failures = [] 
last_summary_log_date = None 

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
        logging.info(f"{SPOTIPY_CACHE_CONTENTS_ENV_VAR} not set. Local auth flow would be needed if no cache file exists.")
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
    # This line should not be reached if exceptions are properly re-raised.
    # Adding a fallback raise to ensure the function doesn't silently return None on unhandled retry exhaustion.
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
    if not station_herald_id:
        logging.error("No station_herald_id provided.")
        return None
    websocket_url = "wss://metadata.musicradio.com/v2/now-playing"
    logging.info(f"Connecting to WebSocket: {websocket_url} for heraldId: {station_herald_id}")
    ws = None
    raw_message = "No message received"
    try:
        ws = websocket.create_connection(websocket_url, timeout=10)
        subscribe_message = {"actions": [{"type": "subscribe", "service": str(station_herald_id)}]}
        ws.send(json.dumps(subscribe_message))
        logging.debug(f"Sent subscribe: {json.dumps(subscribe_message)}")
        message_received = None
        ws.settimeout(10) 
        for i in range(3): 
            raw_message = ws.recv()
            logging.debug(f"Raw WebSocket ({i+1}/3): {raw_message[:300]}...") 
            if raw_message:
                message_data = json.loads(raw_message)
                if message_data.get('now_playing') and message_data['now_playing'].get('type') == 'track':
                    message_received = message_data
                    break 
                elif message_data.get('type') == 'heartbeat':
                    logging.debug("WebSocket heartbeat.")
                    continue 
            time.sleep(0.2) 
        if not message_received:
            logging.info(f"No track update via WebSocket for heraldId {station_herald_id} this attempt.")
            return None
        now_playing = message_received.get('now_playing', {})
        title = now_playing.get('title')
        artist = now_playing.get('artist') 
        track_id_api = now_playing.get('id') 
        if title and artist:
            title = title.strip()
            artist = artist.strip()
            if title and artist: 
                unique_broadcast_id = track_id_api or f"{station_herald_id}_{title}_{artist}".replace(" ", "_")
                logging.info(f"Radio X Now Playing: {title} by {artist}")
                return {"title": title, "artist": artist, "id": unique_broadcast_id}
        logging.info(f"Could not extract title/artist from WebSocket for heraldId {station_herald_id}. Type: {message_received.get('now_playing', {}).get('type')}")
        return None
    except websocket.WebSocketTimeoutException:
        logging.warning(f"WebSocket timeout for heraldId {station_herald_id}")
    except websocket.WebSocketException as e: 
        logging.error(f"WebSocket error for heraldId {station_herald_id}: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from WebSocket for heraldId {station_herald_id}: {e}. Message: {raw_message[:300]}...")
    except Exception as e: 
        logging.error(f"Unexpected WebSocket error for heraldId {station_herald_id}: {e}", exc_info=True)
    finally:
        if ws:
            try:
                ws.close()
                logging.debug("WebSocket closed.")
            except Exception as e_close:
                logging.error(f"Error closing WebSocket for heraldId {station_herald_id}: {e_close}")
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
                search_attempts_details.append(f"Attempt '{attempt_description}' with title '{title_to_search}': Not found via API (empty result).")
                return None 
        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
            logging.error(f"Persistent network error during {attempt_description} for '{title_to_search}' by '{artist}' after all retries: {e}")
            if radiox_id_for_queue and not is_retry_from_queue: 
                add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
            return "NETWORK_ERROR_FLAG" 
        except spotipy.SpotifyException as e:
             if e.http_status in [429, 500, 502, 503, 504]: 
                logging.error(f"Persistent Spotify server error ({e.http_status}) during {attempt_description} for '{title_to_search}' by '{artist}' after retries: {e.msg}")
                if radiox_id_for_queue and not is_retry_from_queue:
                    add_to_failed_search_queue(original_title, artist, radiox_id_for_queue)
                return "NETWORK_ERROR_FLAG"
             else: 
                search_attempts_details.append(f"Attempt '{attempt_description}' with title '{title_to_search}': Spotify API error {e.http_status} - {e.msg}.")
                return None
        except Exception as e: 
            logging.error(f"Unexpected error during {attempt_description} for '{title_to_search}' by '{artist}': {e}")
            return "NETWORK_ERROR_FLAG" 

    spotify_id = _attempt_search_spotify(original_title, "original title")
    if spotify_id == "NETWORK_ERROR_FLAG": 
        if not is_retry_from_queue: 
             daily_search_failures.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "radio_title": original_title, "radio_artist": artist,
                "reason": "Search failed due to persistent network/API error (queued for later retry)"
            })
        return None 
    if spotify_id: 
        return spotify_id

    cleaned_title = re.sub(r'\s*\(.*?\)\s*', ' ', original_title) 
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()

    if cleaned_title and cleaned_title.lower() != original_title.lower():
        logging.info(f"Original title search failed. Retrying with cleaned title: '{cleaned_title}'")
        spotify_id = _attempt_search_spotify(cleaned_title, "cleaned title")
        if spotify_id == "NETWORK_ERROR_FLAG": 
            if not is_retry_from_queue:
                 daily_search_failures.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "radio_title": original_title, "radio_artist": artist,
                    "reason": f"Search with cleaned title ('{cleaned_title}') failed (queued for later retry if applicable)"
                })
            return None
        if spotify_id: 
            return spotify_id
    else:
        if not cleaned_title: search_attempts_details.append("Title became empty after cleaning.")
        else: search_attempts_details.append("No significant change to title after cleaning.")
    
    logging.info(f"Song '{original_title}' by '{artist}' definitively not found on Spotify. Details: [{'; '.join(search_attempts_details)}]")
    if not is_retry_from_queue: 
        daily_search_failures.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "radio_title": original_title, "radio_artist": artist,
            "reason": "Not found on Spotify after original and cleaned title attempts."
        })
    return None

def add_song_to_playlist(radio_x_title, radio_x_artist, spotify_track_id, playlist_id_to_use):
    global RECENTLY_ADDED_SPOTIFY_TRACK_IDS, daily_added_songs, daily_search_failures
    if not sp: logging.error("Spotify not initialized for adding to playlist."); return False
    if not spotify_track_id or not playlist_id_to_use: logging.error("Missing track/playlist ID."); return False
    
    if spotify_track_id in RECENTLY_ADDED_SPOTIFY_TRACK_IDS:
        logging.info(f"Track ID {spotify_track_id} ('{radio_x_title}') was recently processed. Skipping add_song_to_playlist.")
        return True 

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
            oldest_track = RECENTLY_ADDED_SPOTIFY_TRACK_IDS.pop() if RECENTLY_ADDED_SPOTIFY_TRACK_IDS else None # .pop() on empty set raises KeyError
            if oldest_track : logging.debug(f"Removed {oldest_track} from RECENTLY_ADDED_SPOTIFY_TRACK_IDS (limit: {MAX_RECENT_TRACKS})")
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
    if not sp:
        logging.error("Spotify not initialized. Cannot check for duplicates.")
        return
    logging.info(f"Starting duplicate cleanup (remove-all & re-add strategy) for playlist: {playlist_id}")
    all_playlist_tracks_info = [] 
    offset = 0
    limit = 50 
    try:
        logging.debug("DUPLICATE_CLEANUP: Fetching all tracks from playlist...")
        while True:
            results = spotify_api_call_with_retry(sp.playlist_items, playlist_id, limit=limit, offset=offset, fields="items(track(id,uri,name)),next")
            if not results: 
                logging.error("DUPLICATE_CLEANUP: Failed to fetch playlist items. Aborting duplicate check."); return
            if not results['items']: break
            for item in results['items']: 
                if item['track'] and item['track']['id'] and item['track']['uri']:
                    all_playlist_tracks_info.append({'uri': item['track']['uri'], 'id': item['track']['id'], 'name': item['track'].get('name', 'Unknown Track')})
            if results['next']: offset += len(results['items']) 
            else: break
        
        logging.info(f"DUPLICATE_CLEANUP: Fetched {len(all_playlist_tracks_info)} total tracks from playlist {playlist_id}.")
        if not all_playlist_tracks_info: logging.info("DUPLICATE_CLEANUP: Playlist empty."); return

        track_counts = {} 
        for track_item in all_playlist_tracks_info:
            track_id = track_item['id']
            if track_id:
                if track_id not in track_counts: track_counts[track_id] = {'uri': track_item['uri'], 'name': track_item['name'], 'count': 0}
                track_counts[track_id]['count'] += 1
        
        tracks_processed_for_dedup_count = 0
        for track_id, data in track_counts.items():
            if data['count'] > 1:
                tracks_processed_for_dedup_count +=1
                track_uri_to_process, track_name_to_process = data['uri'], data['name']
                logging.info(f"DUPLICATE_CLEANUP: Track '{BOLD}{track_name_to_process}{RESET}' (ID: {track_id}) found {data['count']} times. Removing all and re-adding one.")
                try:
                    logging.info(f"  DUPLICATE_CLEANUP: Removing all of '{BOLD}{track_name_to_process}{RESET}'.")
                    spotify_api_call_with_retry(sp.playlist_remove_all_occurrences_of_items, playlist_id, [track_uri_to_process])
                    logging.info(f"  DUPLICATE_CLEANUP: Re-adding '{BOLD}{track_name_to_process}{RESET}'.")
                    spotify_api_call_with_retry(sp.playlist_add_items, playlist_id, [track_uri_to_process])
                    logging.info(f"  DUPLICATE_CLEANUP: Re-added '{BOLD}{track_name_to_process}{RESET}'.")
                    if track_id: RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(track_id) 
                    time.sleep(1.5) 
                except Exception as e_readd: logging.error(f"DUPLICATE_CLEANUP: Error for URI {track_uri_to_process}: {e_readd}")
        
        if tracks_processed_for_dedup_count > 0:
            logging.info(f"DUPLICATE_CLEANUP: Finished processing {tracks_processed_for_dedup_count} duplicated tracks.")
            time.sleep(5)
        else: logging.info("DUPLICATE_CLEANUP: No tracks found with multiple occurrences.")
    except Exception as e: logging.error(f"Error during duplicate cleanup: {e}", exc_info=True)


def process_failed_search_queue():
    global failed_search_queue, daily_added_songs, daily_search_failures
    if not sp: logging.debug("PFSQ: Spotify not available."); return
    if not failed_search_queue: logging.debug("PFSQ: Queue empty."); return

    # Process only one item from the queue per call to this function
    # to avoid hammering the API if it's still recovering or if many items are queued.
    item_to_retry = failed_search_queue[0] # Peek at the oldest item
    
    title = item_to_retry['title']
    artist = item_to_retry['artist']
    radiox_id = item_to_retry['radiox_id']
    attempts = item_to_retry['attempts']

    logging.info(f"PFSQ: Retrying search for '{title}' by '{artist}' (RadioX ID: {radiox_id}, Attempt: {attempts + 1} of {MAX_FAILED_SEARCH_ATTEMPTS})")
    
    # Call search_song_on_spotify with is_retry_from_queue=True
    # This prevents it from adding itself back to the failed_search_queue if it fails this retry.
    # It also prevents it from logging to daily_search_failures if it's "Not Found" (we do that below if max attempts are hit).
    spotify_track_id = search_song_on_spotify(title, artist, radiox_id_for_queue=None, is_retry_from_queue=True) 
    
    item_processed_from_queue = False
    if spotify_track_id:
        logging.info(f"PFSQ: Successfully found '{title}' on retry from queue. Spotify ID: {spotify_track_id}")
        # Pass original Radio X title and artist for consistency in daily log
        if add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID):
            logging.info(f"PFSQ: SUCCESS: Added '{BOLD}{title}{RESET}' by '{BOLD}{artist}{RESET}' from queue to playlist.")
            # Song is now added, remove from queue
            failed_search_queue.pop(0)
            item_processed_from_queue = True
        else: 
            logging.warning(f"PFSQ: Found '{title}' on retry, but failed to add to playlist (may already exist or other add error). Will not retry this item further from queue.")
            failed_search_queue.pop(0) # Remove, as adding failed for a reason other than search
            item_processed_from_queue = True 
            # Failure to add (if not duplicate) would be logged by add_song_to_playlist to daily_search_failures
    else: 
        # search_song_on_spotify returned None (either not found, or network error still persisted through its retries)
        logging.warning(f"PFSQ: Still could not find or error searching for '{title}' by '{artist}' on retry from queue.")
        item_to_retry['attempts'] += 1
        if item_to_retry['attempts'] >= MAX_FAILED_SEARCH_ATTEMPTS:
            logging.error(f"PFSQ: Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) reached for '{title}' by '{artist}'. Discarding from queue.")
            failed_search_queue.pop(0) # Remove from queue
            item_processed_from_queue = True
            daily_search_failures.append({ # Log to daily summary as a final failure
                "timestamp": datetime.datetime.now().isoformat(),
                "radio_title": title, "radio_artist": artist,
                "reason": f"Max retries ({MAX_FAILED_SEARCH_ATTEMPTS}) from failed search queue exhausted."
            })
        else:
            # Item remains in queue for next time if pop(0) was not done, or re-add if it was.
            # Current logic: we popped it, so if not max_attempts, re-add to end.
            # To keep it simple, if pop(0) is done at start, just update attempts if not removing.
            # Re-evaluating: pop at start, if not successful & not max attempts, re-insert at end or update if still at head.
            # For now, if it's not max_attempts, it just means failed_search_queue[0] now has updated attempts.
            # Let's re-add to the end of the queue if not max attempts.
            logging.info(f"PFSQ: Updating attempt count for '{title}' to {item_to_retry['attempts']}. Will try again later.")
            # No item_processed_from_queue = True here, as it's still in the queue effectively
            # Actually, we popped it. So if not max, add it back to the *end*
            if item_to_retry['attempts'] < MAX_FAILED_SEARCH_ATTEMPTS:
                 failed_search_queue.append(item_to_retry) # Add to the end for later retry
            # if we don't pop initially, we'd do: failed_search_queue[0]['attempts'] +=1


def log_daily_summary():
    global daily_added_songs, daily_search_failures, last_summary_log_date
    
    logging.info("--- DAILY SONG SUMMARY ---")
    current_log_time = datetime.datetime.now().isoformat()
    logging.info(f"Summary for date ending: {last_summary_log_date.isoformat()} (Logged at: {current_log_time})")

    if not daily_added_songs and not daily_search_failures:
        logging.info("No new songs processed or failed today.")
    
    if daily_added_songs:
        logging.info(f"Successfully ADDED {len(daily_added_songs)} song(s) today:")
        for song_info in daily_added_songs:
            logging.info(f"  - ADDED @ {song_info['timestamp']}: '{song_info['radio_title']}' by '{song_info['radio_artist']}' as '{song_info['spotify_title']}' by '{song_info['spotify_artist']}' (ID: {song_info['spotify_id']})")
    else:
        logging.info("No songs were successfully added to Spotify today.")

    if daily_search_failures:
        logging.info(f"FAILED to find/add {len(daily_search_failures)} song(s) today:")
        for song_info in daily_search_failures:
            logging.info(f"  - FAILED @ {song_info['timestamp']}: '{song_info['radio_title']}' by '{song_info['radio_artist']}' (Reason: {song_info['reason']})")
    else:
        logging.info("No song search/add failures (that were not resolved by queue or other means) recorded for today.")
    
    logging.info("--- END OF DAILY SONG SUMMARY ---")
    
    daily_added_songs.clear()
    daily_search_failures.clear()
    # last_summary_log_date is updated in the main loop after this call

def run_radio_monitor():
    print("DEBUG: run_radio_monitor thread function initiated.") 
    logging.info("--- run_radio_monitor thread function initiated. ---") 
    global last_added_radiox_track_id, last_duplicate_check_time, failed_search_queue
    global daily_added_songs, daily_search_failures, last_summary_log_date
    
    if not sp: 
        print("DEBUG: Spotify object 'sp' is None. Thread cannot perform Spotify actions.") 
        logging.error("Spotify not authenticated. Radio monitor thread will not execute its main work.")
    
    logging.info(f"Radio monitor thread started. Spotify object 'sp' is {'INITIALIZED' if sp else 'NONE'}.")
    logging.info(f"Target Spotify Playlist ID: {SPOTIFY_PLAYLIST_ID}") 
    logging.info(f"Monitoring Station Slug: {RADIOX_STATION_SLUG}")
    logging.info(f"Check interval: {CHECK_INTERVAL}s. Duplicate check: {DUPLICATE_CHECK_INTERVAL // 60}min.")

    current_station_herald_id = None
    if last_summary_log_date is None: 
        last_summary_log_date = datetime.date.today() - datetime.timedelta(days=1) 

    while True:
        current_date_obj = datetime.date.today() 
        if last_summary_log_date < current_date_obj : 
            log_daily_summary() 
            last_summary_log_date = current_date_obj # Update after logging

        logging.debug(f"Loop start. Last RadioX ID: {last_added_radiox_track_id}. Failed queue: {len(failed_search_queue)}")
        try:
            if not current_station_herald_id:
                current_station_herald_id = get_station_herald_id(RADIOX_STATION_SLUG)
                if not current_station_herald_id:
                    time.sleep(CHECK_INTERVAL); continue
            
            if not sp: 
                logging.warning("Spotify 'sp' object is None. Skipping cycle."); time.sleep(CHECK_INTERVAL); continue

            current_song_info = get_current_radiox_song(current_station_herald_id)
            song_processed_from_radio_this_cycle = False

            if current_song_info and current_song_info.get("title") and current_song_info.get("artist"):
                title = current_song_info["title"]
                artist = current_song_info["artist"]
                radiox_song_identifier = current_song_info.get("id")
                song_processed_from_radio_this_cycle = True

                if not title or not artist: 
                    logging.warning("Empty title or artist from Radio X.")
                elif radiox_song_identifier == last_added_radiox_track_id:
                    logging.info(f"Song '{title}' by '{artist}' (RadioX ID: {radiox_song_identifier}) same as last. Skipping.")
                else:
                    logging.info(f"New song from Radio X: '{title}' by '{artist}' (RadioX ID: {radiox_song_identifier})")
                    # Pass radiox_id to search so it can be queued if network error on search
                    spotify_track_id = search_song_on_spotify(title, artist, radiox_id_for_queue=radiox_song_identifier) 
                    
                    if spotify_track_id:
                        # add_song_to_playlist now handles adding to daily_added_songs
                        add_song_to_playlist(title, artist, spotify_track_id, SPOTIFY_PLAYLIST_ID)
                    # else: search_song_on_spotify handles adding to daily_failed_searches if definitively not found,
                    # or adds to failed_search_queue if network error.
                    last_added_radiox_track_id = radiox_song_identifier 
            else:
                logging.info("No new track information from Radio X this cycle.")
            
            # Process one item from the failed search queue if a song was successfully processed from radio OR periodically
            if failed_search_queue:
                # Try to process queue item if a radio song was processed (network might be good)
                # or periodically try anyway every few main cycles
                # (time.time() % (CHECK_INTERVAL * 5) < CHECK_INTERVAL) means roughly every 5 main loops (10 mins if CHECK_INTERVAL is 2 mins)
                if song_processed_from_radio_this_cycle or (time.time() % (CHECK_INTERVAL * 5) < CHECK_INTERVAL):
                     process_failed_search_queue()

            current_time = time.time()
            if current_time - last_duplicate_check_time >= DUPLICATE_CHECK_INTERVAL:
                logging.info("--- Starting periodic duplicate check ---")
                if sp: 
                    check_and_remove_duplicates(SPOTIFY_PLAYLIST_ID)
                else:
                    logging.warning("Spotify not initialized. Skipping duplicate check.")
                last_duplicate_check_time = current_time
                logging.info("--- Finished periodic duplicate check ---")

        except Exception as e:
            logging.error(f"Unexpected error in run_radio_monitor loop: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL * 2) 

        logging.info(f"Waiting for {CHECK_INTERVAL} seconds before next check...")
        time.sleep(CHECK_INTERVAL)

def start_monitoring_thread():
    if not hasattr(start_monitoring_thread, "thread_started") or not start_monitoring_thread.thread_started:
        logging.info("Preparing to start monitor_thread.")
        print("DEBUG: Preparing to start monitor_thread.")
        monitor_thread = threading.Thread(target=run_radio_monitor, daemon=True)
        monitor_thread.start()
        start_monitoring_thread.thread_started = True 
        logging.info("Monitor thread started.")
        print("DEBUG: Monitor thread started.")
    else:
        logging.info("Monitor thread already started.")
        print("DEBUG: Monitor thread already started.")

if sp: 
    start_monitoring_thread()
else:
    logging.error("Spotify auth failed. Background monitor thread NOT started.")
    print("ERROR: Spotify auth failed. Background monitor thread NOT started.")

if __name__ == "__main__":
    logging.info("Script being run directly (e.g., local testing).")
    port = int(os.environ.get("PORT", 8080)) 
    logging.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
