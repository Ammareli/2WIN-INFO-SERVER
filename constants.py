# CONSTANTS AS REQURED BY THE SERVER AND NEW WILL BE ADDED AS THE NEW COMPS COME IN.

from dotenv import load_dotenv 
import os 
import pytz

# Load environment variables
load_dotenv(".env-info")


# MESSAGEING SERVER
AUTH = os.getenv("AUTH")
URL = os.getenv("URL")


# ACR API
ACR_API_URL = os.getenv("ACR_API_URL")
ACR_API_KEY = os.getenv("ARC_API_BEARER_TOKEN")


# time zone
TIME_ZONE = pytz.timezone("Europe/London")

# Path to your log file and notes file
LOG_FILE_PATH = 'logs/info_server.log'
NOTES_FILE_PATH = 'notes.txt'

# Comp Names And CODES.
COMPS = [
    "Cash Register",
    "Pick Up In 5 Rings",
    "Pick Up To Win",
    "Make Me A Winner",
    "Show Me The Money",
    "Phrase That Pays", 
    "Xmas Cracker",
    "January Jackpot",
    "Make me a millionaire",
    "35k Payday",
]

# january jackpot
# Spotify Configuration
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_TOKEN_URL = os.getenv("SPOTIFY_TOKEN_URL")
SPOTIFY_API_URL = os.getenv("SPOTIFY_API_URL")

# make me a millionaire
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BEARER_TOKEN = os.getenv('ARC_API_BEARER_TOKEN')
ACRCLOUD_API_URL = os.getenv('ACRCLOUD_API_URL')
LIVE_STREAM_URL = os.getenv('LIVE_STREAM_URL')

