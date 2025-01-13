# comps/comp_Xcraker.py

import json
from datetime import datetime, timedelta
import pytz
from logger import logger
from redis_cache import RedisContactManager
import os
import requests
import subprocess
from datetime import datetime
from constants import *
import time

# Constants (make sure they match your original values or import them)
COOLDOWN_DURATION = 300  
ALARM_DEBOUNCE_TIME = 5  
ANSWER_MEMORY_DURATION = 3300
RECORDING_DURATION = 140
in_progress_key = "xcraker:answer_store_in_progress"
last_answer_ready_key = "xcraker:last_answer_ready"


contact_manager = RedisContactManager()

last_alarm_time_key = "xcraker:last_alarm_time"
last_processed_alarm_time_key = "xcraker:last_processed_alarm_time"
recent_answers_key = "xcraker:recent_answers"  # Redis hash

def store_timestamp(redis_key):
    """Store current timestamp in Redis as ISO8601 string."""
    now = datetime.now(TIME_ZONE).isoformat()
    contact_manager.redis_client.set(redis_key, now)

def get_timestamp(redis_key):
    """Get timestamp from Redis and return as datetime object or None."""
    ts = contact_manager.redis_client.get(redis_key)
    if ts:
        return datetime.fromisoformat(ts.decode('utf-8'))
    return None

def is_in_cooldown():
    last_alarm_time = get_timestamp(last_alarm_time_key)
    if last_alarm_time is None:
        return False
    time_since_last_alarm = datetime.now(TIME_ZONE) - last_alarm_time
    in_cooldown = time_since_last_alarm.total_seconds() < COOLDOWN_DURATION
    if in_cooldown:
        remaining = COOLDOWN_DURATION - time_since_last_alarm.total_seconds()
        logger.info(f"In cooldown period. {int(remaining)} seconds remaining.")
    return in_cooldown

def is_in_debounce_period():
    last_proc_time = get_timestamp(last_processed_alarm_time_key)
    if last_proc_time is None:
        return False
    time_since_last_alarm = datetime.now(TIME_ZONE) - last_proc_time
    in_debounce = time_since_last_alarm.total_seconds() < ALARM_DEBOUNCE_TIME
    if in_debounce:
        logger.info("Alarm debounce period active. Skipping additional alarms.")
    return in_debounce

def is_duplicate_answer(answer):
    # Clean old answers first
    current_time = datetime.now(TIME_ZONE)
    all_answers = contact_manager.redis_client.hgetall(recent_answers_key)
    # all_answers is a dict { b'timestamp': b'answer', ... }

    for ans_time_b, ans_val_b in list(all_answers.items()):
        ans_time_str = ans_time_b.decode('utf-8')
        ans_val = ans_val_b.decode('utf-8')
        ans_time = datetime.fromisoformat(ans_time_str)
        if (current_time - ans_time).total_seconds() > ANSWER_MEMORY_DURATION:
            contact_manager.redis_client.hdel(recent_answers_key, ans_time_str)
            logger.info(f"Removed old answer from memory: {ans_val}")

    # Check if this answer is duplicate
    all_answers = contact_manager.redis_client.hgetall(recent_answers_key)
    for ans_val_b in all_answers.values():
        ans_stored = ans_val_b.decode('utf-8')
        if ans_stored.lower() == answer.lower():
            logger.info(f"Duplicate answer detected: {answer}")
            logger.info("Skipping further processing due to duplicate answer")
            return True

    # Store new answer with current timestamp
    ts_str = current_time.isoformat()
    contact_manager.redis_client.hset(recent_answers_key, ts_str, answer)
    logger.info(f"New unique answer stored in memory: {answer}")
    return False

class AudioProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        logger.info(f"Created/verified output directories: {OUTPUT_DIR} and {PROCESSED_DIR}")
        

    def validate_master_response(self, response):
        """Strictly validate the master's response format."""
        if not response:
            logger.info("Empty master response")
            return False
        
        # Must be exactly in format 'A) Answer' or 'B) Answer'
        if not (response.startswith('A)') or response.startswith('B)')):
            logger.info("Master response doesn't start with A) or B)")
            return False
        
        # Should be one line only
        if '\n' in response:
            logger.info("Master response contains multiple lines")
            return False
        
        # Maximum 4 words
        if len(response.split()) > 4:
            logger.info("Master response too long")
            return False
            
        return True

    def process_trigger(self, alarm_id,auio_path = None):
        timestamp = datetime.now(TIME_ZONE).strftime("%Y%m%d_%H%M%S")
        logger.info(f"\n=== Processing trigger for {alarm_id} at {timestamp} ===\n")
        
        file_paths = {
            'wav': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.wav"),
            'mp3': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.mp3")
        }

        try:
            if not auio_path:
                logger.info(f"Starting {RECORDING_DURATION} seconds recording...")
                command = [
                    "/usr/bin/ffmpeg", "-y",
                    "-i", LIVE_STREAM_URL,
                    "-t", str(RECORDING_DURATION),
                    "-acodec", "pcm_s16le",
                    "-ar", "44100",
                    "-ac", "2",
                    file_paths['wav']
                ]
                subprocess.run(command, check=True, capture_output=True)
                logger.info("Recording completed successfully")

                logger.info("Converting WAV to MP3...")
                command = [
                    "/usr/bin/ffmpeg", "-y",
                    "-i", file_paths['wav'],
                    "-codec:a", "libmp3lame",
                    "-qscale:a", "2",
                    file_paths['mp3']
                ]
                subprocess.run(command, check=True, capture_output=True)
                logger.info(f"MP3 conversion completed: {file_paths['mp3']}")

            logger.info("Starting Whisper transcription...")
            if auio_path:
                file_path = auio_path
            else:

                file_path = file_paths['mp3']

            transcription = self.transcribe_audio(file_path)
            if transcription:
                logger.info(f"Transcription completed: {transcription}")
                
                student_answer = self.generate_gpt_response(transcription, "student")
                if student_answer and student_answer != 'NO_QUESTION_FOUND':
                    logger.info(f"Student Analysis completed: {student_answer}")
                    
                    # Extract student's final answer
                    student_final = None
                    for line in student_answer.split('\n'):
                        if "5. The answer is:" in line:
                            student_final = line.split("is: ")[-1].strip("'")
                            break

                    if student_final:
                        master_context = (
                            f"Student's final answer: {student_final}\n"
                            f"Full analysis:\n{student_answer}"
                        )
                        master_answer = self.generate_gpt_response(master_context, "master")
                        if master_answer and self.validate_master_response(master_answer):
                            logger.info(f"Master Verification completed: {master_answer}")
                            if is_duplicate_answer(master_answer):
                                return
                            else:
                                # Store the last correct answer in Redis
                                contact_manager.redis_client.set("xcraker:last_correct_answer", master_answer)
                                logger.info(f"Stored master answer in Redis: {master_answer}")
                    
                    else:
                        contact_manager.redis_client.set("xcraker:last_correct_answer","NONE")
                        logger.info(f"Stored master answer in Redis: {'NONE'}")   
                
                            

            if os.path.exists(file_paths['wav']):
                os.remove(file_paths['wav'])
                logger.info(f"Cleaned up WAV file: {file_paths['wav']}")
                
            if os.path.exists(file_paths['mp3']):
                processed_path = os.path.join(PROCESSED_DIR, os.path.basename(file_paths['mp3']))
                os.rename(file_paths['mp3'], processed_path)
                logger.info(f"Moved processed MP3 to: {processed_path}")

        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            logger.exception("Full error traceback:")

    def transcribe_audio(self, file_path):
        try:
            logger.info(f"Starting Whisper transcription for: {file_path}")
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"}
            
            with open(file_path, "rb") as audio_file:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files={"file": audio_file},
                    data={"model": "whisper-1"},
                    timeout=30
                )
                if response.status_code != 200:
                    logger.error(f"OpenAI API Error: {response.status_code}")
                    logger.error(f"Response content: {response.text}")
                response.raise_for_status()
                return response.json().get("text")
        except Exception as e:
            logger.error(f"Transcription failed: {str(e)}")
            logger.exception("Full transcription error traceback:")
            return None

    def generate_gpt_response(self, text, role="student"):
        try:
            if role == "student":
                system_message = (
                    "You are analyzing a Heart Radio competition transcript.\n"
                    "Process:\n"
                    "1. Read the entire transcript twice carefully\n"
                    "2. Look for any A/B format question within the conversation\n"
                    "3. Provide analysis in exactly this format:\n"
                    "   1. The exact question heard is: '[question]'\n"
                    "   2. The options given are:\n      A) [option1]\n      B) [option2]\n"
                    "   3. The correct answer is [A/B]) [answer] with a confidence level of [0-100]%.\n"
                    "   4. The reasoning is [your reasoning].\n"
                    "   5. The answer is: '[A/B]) [answer]'.\n\n"
                    "Important: Questions are often embedded in conversation - analyze the full transcript twice before responding."
                )
                max_tokens = 250
            else:  # master role
                system_message = (
                    "You are validating a student's answer for a Heart Radio competition.\n"
                    "The student's analysis will be provided.\n\n"
                    "IF YOU AGREE with the student's answer:\n"
                    "- Simply output their exact final answer line, e.g., 'A) Answer'\n\n"
                    "IF YOU DISAGREE:\n"
                    "- Output only the correct answer in the same format\n\n"
                    "NO OTHER TEXT OR EXPLANATION ALLOWED.\n"
                    "RESPOND WITH ONLY THE ANSWER LINE."
                )
                max_tokens = 25

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": f"The question is: {text}"}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "top_p": 0.1,
                    "presence_penalty": -0.1,
                    "frequency_penalty": -0.1
                },
                timeout=30
            )
            response.raise_for_status()
            gpt_response = response.json()["choices"][0]["message"]["content"].strip()
            
            logger.info(f"Full GPT response for {role}: {gpt_response}")
            return gpt_response
            
        except Exception as e:
            logger.error(f"GPT response failed for {role}: {str(e)}")
            logger.exception("Full GPT error traceback:")
            return None

def process_callback_xCraker(data):
    # This function determines if there's a valid alarm in data
    # Extract alarm_id from data if any
    # If found, return (True, alarm_id)
    # Else return (False, None)

    # Adjust the logic according to your incoming data format
    if 'data' in data and 'metadata' in data['data'] and 'custom_files' in data['data']['metadata']:
        custom_files = data['data']['metadata']['custom_files']
        for file in custom_files:
            if 'alarm_id' in file and file['alarm_id'] in VALID_ALARMS:
                return True, file['alarm_id']
    return False, None

def wait_for_answer_store_completion():
    """Wait until no answer is being stored. If timeout is reached, proceed anyway."""
    
    while True:
        logger.info("sleeping till the recoad is saved.")
        if not contact_manager.redis_client.exists(in_progress_key):
            logger.info("No answer will proceed to save.")
            # No storage in progress, ready to proceed
            return
        time.sleep(0.5)  # Sleep a bit before checking again

def mark_answer_store_start():
    """Mark that this process is now storing the answer."""
    logger.info("Maked inprogress key.")
    contact_manager.redis_client.set(in_progress_key, "1")

def mark_answer_store_complete():
    """Mark that answer storing is complete and set a flag that the last answer is ready."""
    logger.info("marking the last answer key and deleteing the in progress key")
    contact_manager.redis_client.delete(in_progress_key)
    contact_manager.redis_client.set(last_answer_ready_key, "1")  # optional, to indicate readine