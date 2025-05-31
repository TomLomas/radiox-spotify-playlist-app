# Radio X to Spotify Playlist Adder
# Version using WebSocket API for "Now Playing"
# SETTINGS ARE HARDCODED IN THIS VERSION
# Includes duplicate checking (remove all & re-add strategy), updated intervals, and Flask wrapper.

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import time
import os
import json 
import logging
import websocket # Requires: pip install websocket-client
import threading 
from flask import Flask 

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

BOLD = '\033[1m'
RESET = '\033[0m'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not all([SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, SPOTIFY_PLAYLIST_ID, RADIOX_STATION_SLUG]):
    logging.critical("CRITICAL ERROR: Hardcoded configuration values are missing.")
    print("CRITICAL ERROR: Hardcoded configuration values are missing in the script.") 
else:
    logging.info("Successfully using hardcoded configuration.")

last_added_radiox_track_id = None
RECENTLY_ADDED_SPOTIFY_TRACK_IDS = set()
MAX_RECENT_TRACKS = 50
sp = None
herald_id_cache = {} 
last_duplicate_check_time = 0

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
            print("ERROR: Could not get current Spotify user details from token.")
    else:
        sp = None 
        logging.error("Failed to obtain Spotify token (no valid cache and no interactive auth possible on server).")
        print("ERROR: Failed to obtain Spotify token. Ensure SPOTIPY_CACHE_BASE64 is correctly set with fresh cache data.")
except Exception as e:
    sp = None 
    logging.critical(f"CRITICAL Error during Spotify Authentication Setup: {e}", exc_info=True)
    print(f"CRITICAL Error during Spotify Authentication Setup: {e}")

def get_station_herald_id(station_slug_to_find):
    if station_slug_to_find in herald_id_cache:
        logging.debug(f"Found heraldId for '{station_slug_to_find}' in cache: {herald_id_cache[station_slug_to_find]}")
        return herald_id_cache[station_slug_to_find]
    global_player_brands_url = "https://bff-web-guacamole.musicradio.com/globalplayer/brands"
    headers = {
        'User-Agent': 'RadioXToSpotifyApp/1.0 (Python Script)',
        'Accept': 'application/vnd.global.8+json'
    }
    logging.info(f"Fetching heraldId for station slug: {station_slug_to_find} from {global_player_brands_url}")
    try:
        response = requests.get(global_player_brands_url, headers=headers, timeout=10)
        response.raise_for_status()
        brands_data = response.json()
        if not isinstance(brands_data, list):
            logging.error("Brands API did not return a list.")
            return None
        for brand in brands_data:
            if brand.get('brandSlug', '').lower() == station_slug_to_find:
                herald_id = brand.get('heraldId')
                if herald_id:
                    logging.info(f"Found heraldId for '{station_slug_to_find}': {herald_id}")
                    herald_id_cache[station_slug_to_find] = herald_id
                    return herald_id
        logging.warning(f"Could not find heraldId for station slug '{station_slug_to_find}'.")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching brands list: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"Error parsing brands list JSON: {e}")
        return None

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
            try: ws.close(); logging.debug("WebSocket closed.")
            except Exception: pass
    return None

def search_song_on_spotify(title, artist):
    if not sp: logging.error("Spotify not initialized for search."); return None
    query = f"track:{title} artist:{artist}"
    try:
        results = sp.search(q=query, type="track", limit=1)
        if results and results["tracks"]["items"]:
            track = results["tracks"]["items"][0]
            logging.info(f"Found on Spotify: '{track['name']}' by {', '.join(a['name'] for a in track['artists'])} (ID: {track['id']})")
            return track["id"]
        else:
            logging.info(f"Song '{title}' by '{artist}' not found on Spotify.")
    except Exception as e:
        logging.error(f"Error searching Spotify for '{title}' by '{artist}': {e}")
    return None

def add_song_to_playlist(track_id, playlist_id_to_use):
    global RECENTLY_ADDED_SPOTIFY_TRACK_IDS
    if not sp: logging.error("Spotify not initialized for adding to playlist."); return False
    if not track_id or not playlist_id_to_use: logging.error("Missing track/playlist ID for adding song."); return False
    if track_id in RECENTLY_ADDED_SPOTIFY_TRACK_IDS:
        logging.info(f"Track ID {track_id} recently added. Skipping.")
        return False
    try:
        sp.playlist_add_items(playlist_id_to_use, [track_id])
        RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(track_id)
        if len(RECENTLY_ADDED_SPOTIFY_TRACK_IDS) > MAX_RECENT_TRACKS:
            try: RECENTLY_ADDED_SPOTIFY_TRACK_IDS.pop()
            except KeyError: pass
        return True
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 403:
             logging.warning(f"Could not add track ID {track_id} (possible duplicate on Spotify): {e.msg}")
             RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(track_id) 
        else:
            logging.error(f"Error adding to Spotify playlist {playlist_id_to_use}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error adding to playlist {playlist_id_to_use}: {e}")
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
            results = sp.playlist_items(playlist_id, limit=limit, offset=offset, fields="items(track(id,uri,name)),next")
            if not results or not results['items']:
                break
            for item in results['items']: 
                if item['track'] and item['track']['id'] and item['track']['uri']:
                    all_playlist_tracks_info.append({
                        'uri': item['track']['uri'], 
                        'id': item['track']['id'],
                        'name': item['track'].get('name', 'Unknown Track')
                    })
            if results['next']:
                offset += len(results['items']) 
            else:
                break
        
        logging.info(f"DUPLICATE_CLEANUP: Fetched {len(all_playlist_tracks_info)} total tracks from playlist {playlist_id}.")
        if not all_playlist_tracks_info:
            logging.info("DUPLICATE_CLEANUP: Playlist is empty. No duplicates to check.")
            return

        track_counts = {} 
        for track_item in all_playlist_tracks_info:
            track_id = track_item['id']
            if track_id not in track_counts:
                track_counts[track_id] = {'uri': track_item['uri'], 'name': track_item['name'], 'count': 0}
            track_counts[track_id]['count'] += 1

        tracks_processed_for_dedup_count = 0
        for track_id, data in track_counts.items():
            if data['count'] > 1:
                tracks_processed_for_dedup_count +=1
                track_uri_to_process = data['uri']
                track_name_to_process = data['name']
                logging.info(f"DUPLICATE_CLEANUP: Track '{BOLD}{track_name_to_process}{RESET}' (ID: {track_id}) found {data['count']} times. Removing all and re-adding one.")
                
                try:
                    logging.info(f"  DUPLICATE_CLEANUP: Removing all occurrences of '{BOLD}{track_name_to_process}{RESET}' (URI: {track_uri_to_process}).")
                    sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_uri_to_process])
                    logging.info(f"  DUPLICATE_CLEANUP: Successfully removed all. Now re-adding one instance of '{BOLD}{track_name_to_process}{RESET}'.")
                    
                    sp.playlist_add_items(playlist_id, [track_uri_to_process])
                    logging.info(f"  DUPLICATE_CLEANUP: Successfully re-added '{BOLD}{track_name_to_process}{RESET}' to the end of the playlist.")
                    
                    # Add to RECENTLY_ADDED_SPOTIFY_TRACK_IDS to prevent immediate re-addition by main song loop
                    if track_id: # track_id is the Spotify ID here
                         RECENTLY_ADDED_SPOTIFY_TRACK_IDS.add(track_id)
                         if len(RECENTLY_ADDED_SPOTIFY_TRACK_IDS) > MAX_RECENT_TRACKS:
                            try: RECENTLY_ADDED_SPOTIFY_TRACK_IDS.pop()
                            except KeyError: pass
                    
                    time.sleep(1) # Small delay between processing each duplicated song URI
                except Exception as e_readd:
                    logging.error(f"DUPLICATE_CLEANUP: Error processing URI {track_uri_to_process} ('{track_name_to_process}'): {e_readd}")
        
        if tracks_processed_for_dedup_count > 0:
            logging.info(f"DUPLICATE_CLEANUP: Finished processing {tracks_processed_for_dedup_count} tracks that had duplicates using remove/re-add strategy.")
            logging.info("DUPLICATE_CLEANUP: Pausing for 5 seconds after processing all identified duplicated tracks...")
            time.sleep(5)
        else:
            logging.info("DUPLICATE_CLEANUP: No tracks found with multiple occurrences in this cycle.")

    except Exception as e:
        logging.error(f"Error during duplicate cleanup for playlist {playlist_id}: {e}", exc_info=True)

def run_radio_monitor():
    print("DEBUG: run_radio_monitor thread function initiated.") 
    logging.info("--- run_radio_monitor thread function initiated. ---") 
    global last_added_radiox_track_id, last_duplicate_check_time
    
    if not sp: 
        print("DEBUG: Spotify object 'sp' is None in run_radio_monitor. Thread cannot perform Spotify actions.") 
        logging.error("Spotify not authenticated or 'sp' object not available to thread. Radio monitor thread will not execute its main work effectively.")
    
    logging.info(f"Radio monitor thread started. Spotify object 'sp' is {'INITIALIZED' if sp else 'NONE'}.")
    logging.info(f"Target Spotify Playlist ID: {SPOTIFY_PLAYLIST_ID}") 
    logging.info(f"Monitoring Station Slug: {RADIOX_STATION_SLUG}")
    logging.info(f"Check interval for new songs: {CHECK_INTERVAL} seconds.")
    logging.info(f"Duplicate check interval: {DUPLICATE_CHECK_INTERVAL} seconds.")

    current_station_herald_id = None
    last_duplicate_check_time = time.time() - DUPLICATE_CHECK_INTERVAL -1 

    while True:
        logging.debug(f"Top of main radio_monitor loop. Last RadioX track ID: {last_added_radiox_track_id}")
        try:
            if not current_station_herald_id:
                current_station_herald_id = get_station_herald_id(RADIOX_STATION_SLUG)
                if not current_station_herald_id:
                    logging.error(f"Could not get Herald ID for {RADIOX_STATION_SLUG}. Retrying in {CHECK_INTERVAL}s.")
                    time.sleep(CHECK_INTERVAL)
                    continue
            
            if not sp: 
                logging.warning("Spotify object 'sp' is None. Skipping Radio X and Spotify operations in this cycle.")
                time.sleep(CHECK_INTERVAL) 
                continue

            current_song_info = get_current_radiox_song(current_station_herald_id)

            if current_song_info and current_song_info.get("title") and current_song_info.get("artist"):
                title = current_song_info["title"]
                artist = current_song_info["artist"]
                radiox_song_identifier = current_song_info.get("id")

                if not title or not artist: 
                    logging.warning("Title or artist is empty after extraction, skipping song processing.")
                elif radiox_song_identifier == last_added_radiox_track_id:
                    logging.info(f"Song '{title}' by '{artist}' (ID: {radiox_song_identifier}) is same as last. Skipping song processing.")
                else:
                    spotify_track_id = search_song_on_spotify(title, artist)
                    if spotify_track_id:
                        if spotify_track_id in RECENTLY_ADDED_SPOTIFY_TRACK_IDS and radiox_song_identifier != last_added_radiox_track_id:
                             logging.info(f"Song '{title}' by '{artist}' (Spotify ID: {spotify_track_id}) was recently processed (possibly by duplicate cleanup). Skipping add attempt by main loop.")
                        elif add_song_to_playlist(spotify_track_id, SPOTIFY_PLAYLIST_ID): 
                            logging.info(f"SUCCESS: Added '{BOLD}{title}{RESET}' by '{BOLD}{artist}{RESET}' to the playlist (ID: {spotify_track_id}).")
                    last_added_radiox_track_id = radiox_song_identifier 
            else:
                logging.info("No new track information from Radio X this cycle.")
            
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
            logging.error(f"Unexpected error in radio_monitor loop: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL * 2) 

        logging.info(f"Waiting for {CHECK_INTERVAL} seconds before next check...")
        time.sleep(CHECK_INTERVAL)

def start_monitoring_thread():
    if not hasattr(start_monitoring_thread, "thread_started") or not start_monitoring_thread.thread_started:
        logging.info("Preparing to start monitor_thread from start_monitoring_thread function.")
        print("DEBUG: Preparing to start monitor_thread from start_monitoring_thread function.")
        monitor_thread = threading.Thread(target=run_radio_monitor, daemon=True)
        monitor_thread.start()
        start_monitoring_thread.thread_started = True 
        logging.info("Monitor thread started via start_monitoring_thread function.")
        print("DEBUG: Monitor thread started via start_monitoring_thread function.")
    else:
        logging.info("Monitor thread already started or attempt was made.")
        print("DEBUG: Monitor thread already started or attempt was made.")

if sp: 
    start_monitoring_thread()
else:
    logging.error("Spotify authentication failed (sp is None) during initial script load. Background monitor thread will NOT be started automatically by Gunicorn import.")
    print("ERROR: Spotify authentication failed during initial script load. Background monitor thread will NOT be started.")

if __name__ == "__main__":
    logging.info("Script being run directly (e.g., local testing).")
    print("DEBUG: In __main__ block (local execution).")
    port = int(os.environ.get("PORT", 8080)) 
    logging.info(f"Starting Flask development server on port {port}.")
    print(f"DEBUG: Starting Flask app locally on 0.0.0.0:{port}") 
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
