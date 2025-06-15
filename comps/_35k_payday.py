
import json
import time
import requests
from constants import ACR_API_URL, ACR_API_KEY
from logger import logger
from redis_cache import RedisContactManager
import logging

manager = RedisContactManager()

INITIAL_WAIT_AFTER_ALARM_SECONDS = 40
POLLING_INTERVAL_SECONDS = 10
MAX_POLLING_ATTEMPTS = 12

COOLDOWN_SECONDS = 5

ARC_API_BEARER_TOKEN = ACR_API_KEY
ACRCLOUD_LIVE_RESULTS_API_URL = ACR_API_URL
if not ARC_API_BEARER_TOKEN or not ACRCLOUD_LIVE_RESULTS_API_URL:
    logger.warning("CRITICAL: ARC_API_BEARER_TOKEN or ACRCLOUD_LIVE_RESULTS_API_URL are not set in .env3. Song polling after alarm will NOT work.")
else:
    logger.info("ARC_API_BEARER_TOKEN and ACRCLOUD_LIVE_RESULTS_API_URL are loaded.")
logger.info(f"Initial wait after alarm: {INITIAL_WAIT_AFTER_ALARM_SECONDS}s")
logger.info(f"Polling interval: {POLLING_INTERVAL_SECONDS}s for {MAX_POLLING_ATTEMPTS} attempts")
logger.info(f"Final inter-alarm cooldown: {COOLDOWN_SECONDS}s")


def fetch_live_song_data():
    if not ARC_API_BEARER_TOKEN or not ACRCLOUD_LIVE_RESULTS_API_URL:
        logger.error("Cannot poll: ARC_API_BEARER_TOKEN or ACRCLOUD_LIVE_RESULTS_API_URL not configured.")
        return None
    headers = {
        "Authorization": f"Bearer {ARC_API_BEARER_TOKEN}",
        "Accept": "application/json"
    }
    try:
        logger.info(f"Polling for live song data from: {ACRCLOUD_LIVE_RESULTS_API_URL}")
        response = requests.get(ACRCLOUD_LIVE_RESULTS_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        live_data = response.json()
        # Log the full data if DEBUG level is enabled, otherwise a snippet
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Live song data received: {json.dumps(live_data)}")
        else:
            logger.info(f"Live song data received (snippet): {json.dumps(live_data)[:250]}...")
        return live_data
    except requests.exceptions.Timeout:
        logger.warning("Timeout while polling live song data API.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching live song data: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"Response status: {e.response.status_code}, Response text (snippet): {e.response.text[:200]}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from live song data API: {e}. Response text (snippet): {response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'N/A'}")
        return None

def extract_artist_name_from_live_data(live_data):
    if not isinstance(live_data, dict):
        logger.debug("extract_artist_name: live_data is not a dictionary.")
        return None

    artist_name = None
    title = "N/A"
    acr_status = "unknown" # ACRCloud sync status (e.g., "playing", "silence", "no_result")

    # Try path based on your successful examples: response_json['data']['metadata']['music']
    # where 'data' itself is a dictionary.
    data_section = live_data.get('data')
    if isinstance(data_section, dict):
        metadata_section = data_section.get('metadata')
        if isinstance(metadata_section, dict):
            music_list = metadata_section.get('music')
            if isinstance(music_list, list) and music_list: # If music is a non-empty list
                first_song = music_list[0]
                if isinstance(first_song, dict):
                    acr_status = first_song.get("acr_sync_level_status", first_song.get("status", acr_status)) # Check common status keys
                    artists_list = first_song.get('artists')
                    if isinstance(artists_list, list) and artists_list:
                        first_artist = artists_list[0]
                        if isinstance(first_artist, dict):
                            artist_name = first_artist.get('name')
                            title = first_song.get('title', title)
                            logger.debug(f"Artist found via data.metadata.music: '{artist_name}', Title: '{title}', ACR Status: '{acr_status}'")

    # Fallback: If 'data' key doesn't exist or isn't a dict, try if 'metadata' is top-level
    # (less common for live results but seen in some general ACRCloud responses)
    if not artist_name:
        metadata_section = live_data.get('metadata')
        if isinstance(metadata_section, dict):
            music_list = metadata_section.get('music')
            if isinstance(music_list, list) and music_list:
                first_song = music_list[0]
                if isinstance(first_song, dict):
                    acr_status = first_song.get("acr_sync_level_status", first_song.get("status", acr_status))
                    artists_list = first_song.get('artists')
                    if isinstance(artists_list, list) and artists_list:
                        first_artist = artists_list[0]
                        if isinstance(first_artist, dict):
                            artist_name = first_artist.get('name')
                            title = first_song.get('title', title)
                            logger.debug(f"Artist found via metadata.music: '{artist_name}', Title: '{title}', ACR Status: '{acr_status}'")
    
    # Fallback: Check for 'result' key if others fail
    if not artist_name:
        result_section = live_data.get('result')
        if isinstance(result_section, dict):
            metadata_section = result_section.get('metadata')
            if isinstance(metadata_section, dict):
                music_list = metadata_section.get('music')
                if isinstance(music_list, list) and music_list:
                    first_song = music_list[0]
                    if isinstance(first_song, dict):
                        acr_status = first_song.get("acr_sync_level_status", first_song.get("status", acr_status))
                        artists_list = first_song.get('artists')
                        if isinstance(artists_list, list) and artists_list:
                            first_artist = artists_list[0]
                            if isinstance(first_artist, dict):
                                artist_name = first_artist.get('name')
                                title = first_song.get('title', title)
                                logger.debug(f"Artist found via result.metadata.music: '{artist_name}', Title: '{title}', ACR Status: '{acr_status}'")

    if artist_name:
        non_music_statuses = ["silence", "noise", "no_signal", "speech", "no_result", "error"] # Add other non-music statuses if known
        if acr_status.lower() not in non_music_statuses:
            logger.info(f"VALID ARTIST extracted: '{artist_name}', Title: '{title}', ACR Status: '{acr_status}'")
            return artist_name
        else:
            logger.info(f"Artist '{artist_name}' found, but content is non-music (Title: '{title}', ACR Status: '{acr_status}'). Ignoring.")
            return None
    else:
        logger.info(f"No valid artist name found in live data structure. ACR Status (if available): '{acr_status}'.")
        if logger.getLogger().isEnabledFor(logger.DEBUG):
             logger.debug(f"Full live_data for debugging artist path: {json.dumps(live_data)}")
    return None




def process_song_after_alarm_sequence():
    try:
        logger.info(f"BACKGROUND THREAD: Waiting {INITIAL_WAIT_AFTER_ALARM_SECONDS}s before starting to poll for song.")
        time.sleep(INITIAL_WAIT_AFTER_ALARM_SECONDS)

        artist_name_found_and_logged = False
        for attempt in range(1, MAX_POLLING_ATTEMPTS + 1):
            logger.info(f"BACKGROUND THREAD: Polling for song: Attempt {attempt}/{MAX_POLLING_ATTEMPTS}")
            live_data = fetch_live_song_data()
            if live_data:
                artist_name = extract_artist_name_from_live_data(live_data)
                if artist_name:
                    logger.info(f"BACKGROUND THREAD: SONG DETECTED after alarm! Artist: '{artist_name}'")
                    artist_name_found_and_logged = True
                    return artist_name
                    
                else:
                    logger.info("BACKGROUND THREAD: Polling attempt: No valid song/artist found in current live data, or data indicated non-music.")
            else:
                logger.warning("BACKGROUND THREAD: Polling attempt: Failed to fetch or parse live data.")

            if not artist_name_found_and_logged and attempt < MAX_POLLING_ATTEMPTS:
                logger.info(f"BACKGROUND THREAD: Waiting {POLLING_INTERVAL_SECONDS}s for next poll.")
                time.sleep(POLLING_INTERVAL_SECONDS)
            elif attempt == MAX_POLLING_ATTEMPTS and not artist_name_found_and_logged:
                 logger.warning(f"BACKGROUND THREAD: Max polling attempts ({MAX_POLLING_ATTEMPTS}) reached. No song/artist identified and logged after alarm.")

    except Exception as e:
        logger.exception("BACKGROUND THREAD: Exception occurred during song polling sequence.")
    finally:
        logger.info("BACKGROUND THREAD: Song polling sequence finished or terminated.")
        


def run_35k_payday(data):
    logger.info("Received ACRCloud webhook callback.")
    logger.info(f"Callback data: {data}")

    logger.info("ALARM NOTIFICATION CONFIRMED from callback.")
    logger.info("Starting background task to wait and poll for subsequent song.")

    artist_name = process_song_after_alarm_sequence()
    if artist_name:
        logger.info(f"Artist name found and logged: '{artist_name}'")
        # Here you can add any additional processing or actions with the artist name
        return artist_name
    else:
        logger.info("No valid artist name found after polling.")
        return None

        
        



    