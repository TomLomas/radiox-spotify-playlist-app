# Radio X to Spotify Playlist Adder
# Version using WebSocket API for "Now Playing" - Cleaned Output & Bolded Additions
# SETTINGS ARE HARDCODED IN THIS VERSION

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import time
import os
import json 
import logging
import websocket # Requires: pip install websocket-client

# --- Configuration (HARDCODED) ---
SPOTIPY_CLIENT_ID = "89c7e2957a7e465a8eeb9d2476a82a2d"
SPOTIPY_CLIENT_SECRET = "f8dc109892b9464ab44fba3b2502a7eb"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_PLAYLIST_ID = "5i13fDRDoW0gu60f74cysp" # Cleaned ID
RADIOX_STATION_SLUG = "radiox" # Or your desired station slug e.g., "radioxclassic-rock"

CHECK_INTERVAL = 120  # Check every 60 seconds

# ANSI escape codes for formatting
BOLD = '\033[1m'
RESET = '\033[0m'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not all([SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI, SPOTIFY_PLAYLIST_ID, RADIOX_STATION_SLUG]):
    logging.critical("CRITICAL ERROR: One or more hardcoded configuration values are empty. Please check the script.")
    print("CRITICAL ERROR: One or more hardcoded configuration values are empty. Please check the script.")
    exit()
else:
    logging.info("Successfully using hardcoded configuration.")

# --- Global Variables & Spotify Auth ---
last_added_radiox_track_id = None
RECENTLY_ADDED_SPOTIFY_TRACK_IDS = set()
MAX_RECENT_TRACKS = 50
sp = None
herald_id_cache = {} 

scope = "playlist-modify-public playlist-modify-private user-library-read"
try:
    auth_manager = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET,
                                redirect_uri=SPOTIPY_REDIRECT_URI, scope=scope, cache_path=".spotipy_cache")
    
    token_info = auth_manager.get_cached_token()
    if not token_info:
        logging.info("No cached Spotify token, attempting to get new token (browser may open or require URL paste).")
        token_info = auth_manager.get_access_token(as_dict=False)

    if token_info:
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user = sp.current_user()
        if user:
            logging.info(f"Successfully authenticated with Spotify as {user['display_name']} ({user['id']})")
        else:
            logging.error("Could not get current Spotify user details. Token might be invalid.")
            exit()
    else:
        logging.error("Failed to obtain Spotify token.")
        exit()
except Exception as e:
    logging.critical(f"CRITICAL Spotify Authentication Error: {e}", exc_info=True)
    exit()

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
        logging.debug(f"Available brandSlugs: {[b.get('brandSlug') for b in brands_data]}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching brands list: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"Error parsing brands list JSON: {e}")
        return None

def get_current_radiox_song(station_herald_id):
    if not station_herald_id:
        logging.error("No station_herald_id provided to get_current_radiox_song.")
        return None

    websocket_url = "wss://metadata.musicradio.com/v2/now-playing"
    logging.info(f"Connecting to WebSocket: {websocket_url} for heraldId: {station_herald_id}")
    
    ws = None
    raw_message = "No message received"
    try:
        ws = websocket.create_connection(websocket_url, timeout=10)
        subscribe_message = {"actions": [{"type": "subscribe", "service": str(station_herald_id)}]}
        ws.send(json.dumps(subscribe_message))
        logging.debug(f"Sent subscribe message: {json.dumps(subscribe_message)}")
        
        message_received = None
        ws.settimeout(10) 
        
        for i in range(3): 
            raw_message = ws.recv()
            logging.debug(f"Received raw WebSocket message ({i+1}/3): {raw_message[:300]}...") 
            if raw_message:
                message_data = json.loads(raw_message)
                if message_data.get('now_playing') and message_data['now_playing'].get('type') == 'track':
                    message_received = message_data
                    break 
                elif message_data.get('type') == 'heartbeat':
                    logging.debug("Received heartbeat from WebSocket.")
                    continue 
                else:
                    logging.debug(f"Received non-track/non-heartbeat message: {message_data.get('type')}")
            time.sleep(0.2) 

        if not message_received:
            logging.info(f"No track update message received from WebSocket for heraldId {station_herald_id} in this attempt.")
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
        
        logging.info(f"Could not extract title/artist from WebSocket message for heraldId {station_herald_id}. Message type: {message_received.get('now_playing', {}).get('type')}")
        return None

    except websocket.WebSocketTimeoutException:
        logging.warning(f"WebSocket timeout for heraldId {station_herald_id} from {websocket_url}")
    except websocket.WebSocketException as e:
        logging.error(f"WebSocket error for heraldId {station_herald_id} with {websocket_url}: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from WebSocket for heraldId {station_herald_id}: {e}. Message: {raw_message[:300]}...")
    except Exception as e:
        logging.error(f"Unexpected error in WebSocket for heraldId {station_herald_id}: {e}", exc_info=True)
    finally:
        if ws:
            try:
                ws.close()
                logging.debug("WebSocket connection closed.")
            except Exception as e_close:
                logging.error(f"Error closing WebSocket: {e_close}")
    return None

def search_song_on_spotify(title, artist):
    if not sp: logging.error("Spotify not initialized."); return None
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
    if not sp: logging.error("Spotify not initialized."); return False
    if not track_id or not playlist_id_to_use: logging.error("Missing track/playlist ID."); return False

    if track_id in RECENTLY_ADDED_SPOTIFY_TRACK_IDS:
        logging.info(f"Track ID {track_id} recently added. Skipping.")
        return False
    
    try:
        sp.playlist_add_items(playlist_id_to_use, [track_id])
        # The existing log below is fine, we will add a new bolded one in main()
        # logging.info(f"Successfully added track ID {track_id} to playlist {playlist_id_to_use}")
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

def main():
    global last_added_radiox_track_id
    logging.info("Starting Radio X to Spotify Playlist Adder (WebSocket API - Hardcoded Settings).")
    
    logging.info(f"Target Spotify Playlist ID: {SPOTIFY_PLAYLIST_ID}") 
    logging.info(f"Monitoring Station Slug: {RADIOX_STATION_SLUG}")
    logging.info(f"Check interval: {CHECK_INTERVAL} seconds.")

    current_station_herald_id = None

    while True:
        logging.debug(f"Top of main loop. Last RadioX track ID: {last_added_radiox_track_id}")
        try:
            if not current_station_herald_id:
                current_station_herald_id = get_station_herald_id(RADIOX_STATION_SLUG)
                if not current_station_herald_id:
                    logging.error(f"Could not get Herald ID for {RADIOX_STATION_SLUG}. Retrying in {CHECK_INTERVAL}s.")
                    time.sleep(CHECK_INTERVAL)
                    continue
            
            current_song_info = get_current_radiox_song(current_station_herald_id)

            if current_song_info and current_song_info.get("title") and current_song_info.get("artist"):
                title = current_song_info["title"]
                artist = current_song_info["artist"]
                radiox_song_identifier = current_song_info.get("id")

                if not title or not artist: 
                    logging.warning("Title or artist is empty after extraction, skipping.")
                elif radiox_song_identifier == last_added_radiox_track_id:
                    logging.info(f"Song '{title}' by '{artist}' (ID: {radiox_song_identifier}) is same as last. Skipping.")
                else:
                    # This log already exists and is good:
                    # logging.info(f"Radio X Now Playing: {title} by {artist}") 
                    # (This is actually inside get_current_radiox_song now)

                    spotify_track_id = search_song_on_spotify(title, artist)
                    if spotify_track_id:
                        if add_song_to_playlist(spotify_track_id, SPOTIFY_PLAYLIST_ID): 
                            logging.info(f"SUCCESS: Added '{BOLD}{title}{RESET}' by '{BOLD}{artist}{RESET}' to the playlist.")
                            last_added_radiox_track_id = radiox_song_identifier
                        # If add_song_to_playlist returns False, it already logged the reason (e.g. duplicate or error)
                    
                    # Update last_added_radiox_track_id regardless of Spotify success to avoid reprocessing same Radio X song immediately
                    last_added_radiox_track_id = radiox_song_identifier 
            else:
                logging.info("No new track information from Radio X this cycle.")
        
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL * 2) 

        logging.info(f"Waiting for {CHECK_INTERVAL} seconds before next check...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.info("Script execution point: __main__")
    main()