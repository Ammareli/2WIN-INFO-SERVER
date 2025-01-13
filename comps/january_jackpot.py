from datetime import datetime, timedelta
import requests
import json
import time
import os
import pytz
from logger import logger
from base64 import b64encode
from constants import TIME_ZONE, SPOTIFY_API_URL, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_TOKEN_URL, ARTIST_FILE



# ACRCloud Configuration
BEARER_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI3IiwianRpIjoiNTJhZDUzNTIzMmExMTRmYmI3YTdjZTRmOGRmNDA1NTA3YzRiMzUxZGU0MTNkMmZkMmQzMTczMzRkYWM1MDJmYmYyOTgzYjg0MGQzZGY5MDYiLCJpYXQiOjE3MjM1NDY3NTYuMzU1MDAyLCJuYmYiOjE3MjM1NDY3NTYuMzU1MDA0LCJleHAiOjIwMzkwNzk1NTYuMzIxNjExLCJzdWIiOiIxODQ4MDQiLCJzY29wZXMiOlsiKiIsIndyaXRlLWFsbCIsInJlYWQtYWxsIl19.JH4UjF2XVKlXVwTxWcW6Ia6vUDI6TtgUhKpCLutgrPZ1cxWZZ2Ta-japzaMFC1cVKVXTn36FyQNaok9yAEqOhAwVlfkSFnByW5A6VD2H-rtc70u7oI2EK6LYyY6jpwtk_bjp68RtRLwY6u4B4oLuXwjOP-VQp7qm5oIksmSd4ZnPRzEubb1IiYXPtpaSY2aWr4h10r1S6ibYNmgS0FbrD5ahwMqzjzQvPq2LUext3Vyi0E_D1wrzbpl0ZaYi_sMpVP052K2S1WbPvw7Jzgkzl0RogaifrqQ-Zyy0sV7AuGGo-syrcWgRpz2oscBkJZu6fcPLe5D1s8daMFiUslODrfA16rUgYUxPXcrSHYwwwgYAtRpV5VCwdMN-yFau0DG9wl2ZEm0x089x7iZ_QTSHVQGlCTqV50yASrXtazQfM2a1WRd5P446O1k7faaOE_Yqs9yc8RXOS-Z1_AfV2cXKHnckWtdUjSii2iCKPrk85i_oI278Bj-HacPe_LNsTPZQihq2GyaeQCSN3GW3LRAIEthbHGlq7woFQ1jPzFEr2w4tWTyF6a8PtkXpnsMW_WIOSqH-4RQeMnsNK5MIpOlVo3pp3ZPimWe5miAEb-2zbxBjo4AXUZ4LPtxtHbH3EFmyW7xFv-lRIT9zjjg4Cpsy8vBuUpKqILeMkZkHmmSRiic"
API_URL = "https://api-v2.acrcloud.com/api/bm-bd-projects/3165/channels/293484/realtime_results"



# Valid alarm IDs
VALID_ALARMS = ["Alarm1", "Alarm2", "Alarm3", "Alarm4", "Alarm5"]

# Processing lock
PROCESSING_UNTIL = None

# comp name
COMP_NAME = "January Jackpot"

# Configure logger with UK timezone
uk_tz = TIME_ZONE

def print_with_timestamp(message):
    """Print message with timestamp"""
    timestamp = datetime.now(uk_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
    print(f"[{timestamp}] {message}")


def is_processing():
    """Check if we're in processing/cooldown period"""
    if PROCESSING_UNTIL is None:
        return False
    return datetime.now() < PROCESSING_UNTIL

def get_spotify_token():
    """Get Spotify access token"""
    auth = b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}
    response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
    return response.json()["access_token"]

def search_spotify(query, token, search_type="track"):
    """Search Spotify API"""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": query,
        "type": search_type,
        "limit": 1
    }
    response = requests.get(f"{SPOTIFY_API_URL}/search", headers=headers, params=params)
    return response.json()

def verify_with_spotify(track_data):
    """Verify track data with Spotify"""
    try:
        spotify_token = get_spotify_token()
        title = track_data.get('title', '')
        artist = track_data.get('artists', [{}])[0].get('name', '')
        
        result = search_spotify(f"track:{title} artist:{artist}", spotify_token)
        if result and result.get('tracks', {}).get('items'):
            spotify_track = result['tracks']['items'][0]
            return {
                'artists': format_artists({'artists': spotify_track['artists']}),
                'title': spotify_track['name']
            }
        return None
    except Exception as e:
        return None

def format_artists(track_data):
    """Format artist names with features"""
    artists = track_data.get('artists', [])
    if not artists:
        return ""
    
    main_artist = artists[0]['name']
    featured_artists = [artist['name'] for artist in artists[1:]]
    
    if featured_artists:
        return f"{main_artist} feat. {', '.join(featured_artists)}"
    return main_artist

def fetch_live_data():
    """Fetch live data from ACRCloud API"""
    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(API_URL, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.info(f"Error fetching live data: {str(e)}")
        return None

def get_artist_name(max_retries=5, retry_delay=5):
    """Get artist name with retries"""
    for attempt in range(max_retries):
        api_data = fetch_live_data()
        if not api_data:
            logger.info(f"Retry {attempt + 1}/{max_retries}: No data received")
            time.sleep(retry_delay)
            continue

        music_data = api_data.get('data', {}).get('metadata', {}).get('music', [])
        if music_data:
            track = music_data[0]
            verified_data = verify_with_spotify(track)
            if verified_data:
                return verified_data['artists']
        
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    
    return None


def process_alarm(alarm_id):
    """Process alarm trigger and get artist"""
    logger.info(f"🚨 ALARM TRIGGERED: {alarm_id} 🚨")
    logger.info("Starting 30-second wait for next song")
    time.sleep(30)
    
    logger.info("Attempting to get artist name")
    artist_name = get_artist_name()
    
    if artist_name:
        logger.info(f"Artist name found: {artist_name}")
        return [artist_name, True]
    return False

def check_for_alarm(data):
    """Check for any alarm ID in the data recursively"""
    if isinstance(data, dict):
        # First check for ALARM_ID in custom_files structure
        if 'data' in data and 'metadata' in data['data'] and 'custom_files' in data['data']['metadata']:
            for file in data['data']['metadata']['custom_files']:
                if 'ALARM_ID' in file and file['ALARM_ID'] in VALID_ALARMS:
                    return file['ALARM_ID']
        
        # Then check all other fields
        for key, value in data.items():
            if isinstance(value, str) and value in VALID_ALARMS:
                return value
            result = check_for_alarm(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = check_for_alarm(item)
            if result:
                return result
    return None


def run_jan_jackpot(alarm_id):
    """Run January Jackpot process"""
    result =  process_alarm(alarm_id)
    if result[1]:
        return [COMP_NAME,result[0]]
    return False





