# This is a temp initilization for comps later will be updated
from logger import logger 
from typing import Optional, Dict, Any
from datetime import datetime
import time
import requests
from constants import *
from redis_cache import RedisContactManager


COMP_NAME = "Show Me The Money"

# Initialize the contact manager (you can move this to a global scope if needed)
contact_manager = RedisContactManager()



last_artist = None
processing_alarm = False
waiting_for_api_check = False

def fetch_live_data(bearer_token: str, live_data_api_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetches live data from an API endpoint using a bearer token for authorization.

    Args:
        bearer_token (str): The bearer token for authorization to access the API.
        live_data_api_url (str): The URL of the API endpoint to fetch live data from.

    Returns:
        Optional[Dict[str, Any]]: Returns a dictionary containing the live data if the request is successful;
                                  otherwise, returns None.
    """
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }

    try:
        print("Fetching live artist data...")
        response = requests.get(live_data_api_url, headers=headers)
        if response.status_code == 200:
            live_data = response.json()
            print(f"Live data received: {live_data}")
            logger.info(f"Live data received: {live_data}")
            return live_data
        else:
            print(f"Failed to fetch live data. Status code: {response.status_code}")
            logger.error(f"Failed to fetch live data. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching live data: {str(e)}")
        logger.error(f"Error fetching live data: {str(e)}")
        return None
    

def extract_artist_name(live_data: Dict[str, Any]) -> Optional[str]:
    """
    Extracts the artist name from the live data dictionary.

    Args:
        live_data (Dict[str, Any]): The live data dictionary from which to extract the artist name.

    Returns:
        Optional[str]: The artist name if it exists; otherwise, returns None.
    """
    try:
        # Navigate to the most reliable path for the artist name
        artist_name = live_data['data']['metadata']['music'][0]['artists'][0]['name']
        print(artist_name)
        return artist_name
    except (KeyError, IndexError, TypeError):
        # If any error occurs while trying to access the artist name, return None
        return None


def process_callback(data):
    print("Processing callback...")
    global processing_alarm, waiting_for_api_check
    # Check if custom sound (alarm) is detected
    if data and "data" in data and "metadata" in data["data"] and "custom_files" in data["data"]["metadata"]:
        for file_info in data["data"]["metadata"]["custom_files"]:
            alarm_id = file_info.get("alarm_id")

            # Recognize specific alarms (add new alarms here if needed)
            if alarm_id in ["Alarm 1", "Alarm 3", "Alarm 4", "Alarm 5"]:
                print(f"Custom sound detected: {alarm_id}")
                logger.info(f"Custom sound detected: {alarm_id}")
                logger.info(not processing_alarm and not waiting_for_api_check)
                if not processing_alarm and not waiting_for_api_check:
                    logger.info("Process alarm")
                    
                    return True 
                else:
                    logger.info("Alarm already being processed or waiting period active. Ignoring this trigger.")
                    return False
            else:
                print(f"Unknown alarm detected: {alarm_id}")
                logger.warning(f"Unknown alarm detected: {alarm_id}")
                return False
    else:

        return False

def get_current_artist_name():
    # Check if artist name is already in Redis
    artist_name = contact_manager.redis_client.get('current_artist_name')
    if artist_name:
        artist_name = artist_name.decode('utf-8')
        logger.info(f"Using artist name from Redis: {artist_name}")
        return artist_name
    else:
        # Fetch and store artist name
        artist_name = fetch_and_store_artist_name()
        return artist_name

def fetch_and_store_artist_name():
    logger.info("Retrieving artist name...")
    check_count = 0
    max_checks = 6  # Will check for 2 minutes (6 * 20 seconds)

    artist_name = None  # Initialize artist_name

    while check_count < max_checks:
        logger.info("Started processing")
        # Simulate fetching live data
        live_data = fetch_live_data(ACR_API_KEY, ACR_API_URL)
        if live_data:
        # if True:
            artist_name = extract_artist_name(live_data)
            # artist_name = semulate_artists()

            logger.info(f"Artist name detected: {artist_name}")

            if artist_name:
                # Store the artist name in Redis for other workers
                contact_manager.redis_client.set('current_artist_name', artist_name)
                logger.info(f"Artist name '{artist_name}' stored in Redis.")

                return artist_name
            else:
                logger.info("No artist name detected. Will retry.")
        else:
            logger.info("No live data available. Will retry.")

        # Wait before checking again
        time.sleep(20)
        check_count += 1

    logger.info("Artist name could not be retrieved after maximum retries.")
    return None


def process_alarm():
    global last_artist    
    try:
        logger.info("Processing alarm.")
        # Retrieve current artist name
        artist_name = get_current_artist_name()
        if not artist_name:
            logger.info("Artist name could not be retrieved. Exiting process_alarm.")
            return
        # Check for duplicate processing
         # Cooldown logic applies only for different request IDs
        last_processed_artist = contact_manager.redis_client.get('last_processed_artist')
        last_processed_time = contact_manager.redis_client.get('last_processed_time')
        cooldown_period = 300  # Cooldown period in seconds (e.g., 5 minutes)
        current_time = int(time.time())

        if last_processed_artist:
            last_processed_artist = last_processed_artist.decode('utf-8')
            last_processed_time = int(last_processed_time.decode('utf-8'))
            time_since_last_processed = current_time - last_processed_time
            

            if artist_name == last_processed_artist and time_since_last_processed < cooldown_period:
                logger.info(f"Notifications for artist '{artist_name}' have already been sent within the cooldown period. Skipping.")
                return
            else:
                logger.info(f"Cooldown period expired or different artist detected. Proceeding with notifications.")
        else:
            logger.info("No previous artist processed. Proceeding with notifications.")

        # Send notifications
        logger.info(f"DATA TO SEND,artist: {artist_name}")

        # Update last_processed_artist and last_processed_time in Redis
        contact_manager.redis_client.set('last_processed_artist', artist_name)
        contact_manager.redis_client.set('last_processed_time', current_time)

        return [COMP_NAME, artist_name]
        
    except Exception as e:
        logger.error(f"Error {e}")



def get_current_datetime():
    date_time = datetime.now(TIME_ZONE)
    date_time = date_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return date_time

def comp_send_me_money_data():
    data = process_alarm()
    logger.info(f"Data to send: {data}")
    if data:
        comp_name = data[0]
        artist = data[1]
        logger.info(f"Sending data for comp: {comp_name, artist}")
        return comp_name, artist
    else:
        logger.info("No data to send.")
    




        
    
    




        
        


    
