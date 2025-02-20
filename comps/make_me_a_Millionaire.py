import os
import requests
import subprocess
import pytz
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import time
import logger
from constants import OPENAI_API_KEY, BEARER_TOKEN, LIVE_STREAM_URL
from redis_cache import RedisContactManager

# Load environment variables
load_dotenv('.env2')

# Environment variables and constants

redis_manager = RedisContactManager()

if not OPENAI_API_KEY or not BEARER_TOKEN:
    raise ValueError("Missing required environment variables. Check .env2 file.")

TIMEZONE = pytz.timezone("Europe/London")
OUTPUT_DIR = "output_segments"
PROCESSED_DIR = os.path.join(OUTPUT_DIR, "processed_segments")
LOG_FILE = "make_me_millionaire_log.txt"
MASTER_FILE = "millionaire_master.txt"
RECORDING_DURATION = 200
COOLDOWN_DURATION = 300
VALID_ALARMS = ["Alarm1", "Alarm2", "Alarm3", "Alarm4", "Alarm5"]

audio_processor = None
last_processed_alarm_time = None



def is_in_cooldown():
    cooldown_p = redis_manager.redis_client.get("COOLDOWN_DURATION")    
    if not cooldown_p:
        return False
    return cooldown_p



def detect_alarm(data):
    def search_dict(d):
        if not isinstance(d, (dict, list)):
            return None

        if isinstance(d, dict):
            alarm_keys = ['alarm_id', 'ALARM_ID', ' ALARM_ID']
            for key in alarm_keys:
                if key in d and d[key] in VALID_ALARMS:
                    return d[key]

            for value in d.values():
                result = search_dict(value)
                if result:
                    return result

        if isinstance(d, list):
            for item in d:
                result = search_dict(item)
                if result:
                    return result
        return None

    return search_dict(data)


class AudioProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        logger.info(f"Created/verified output directories: {OUTPUT_DIR} and {PROCESSED_DIR}")
        self.executor = ThreadPoolExecutor(max_workers=1)  # Initialize executor

    def transcribe_audio(self, file_path):
        """Transcribes audio using OpenAI Whisper API."""
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
                response.raise_for_status()
                transcription = response.json().get("text", None)
                if transcription:
                    logger.info(f"Transcription result: {transcription}")
                else:
                    logger.error("No transcription text returned by the Whisper API.")
                return transcription
        except Exception as e:
            logger.error(f"❌ Transcription failed: {str(e)}")
            logger.exception("Full transcription error traceback:")
        return None

    def analyze_conversation(self, text):
        """Analyzes transcript to detect if it contains a winning conversation."""
        try:
            logger.info("Beginning conversation analysis...")
            system_message = (
                "You are analyzing a Heart Radio competition transcript to detect if this is a winning conversation.\n\n"
                "Look for these SPECIFIC patterns that indicate a winner:\n"
                "1. Two-way conversation between presenter and contestant\n"
                "2. Direct interaction patterns:\n"
                "   - Contestant being addressed by name\n"
                "   - Contestant responding directly to presenter\n"
                "   - Discussion about prize amounts/decisions\n"
                "   - Winner emotions (e.g., 'oh my god', 'thank you')\n"
                "3. Critical winner indicators:\n"
                "   - Making a choice between immediate prize or million pound draw\n"
                "   - Final decision being stated\n"
                "   - Personal discussion about what they'll do with money\n\n"
                "Format your response EXACTLY like this:\n"
                "1. Winner conversation found: [YES/NO]\n"
                "2. Evidence found:\n"
                "   - Interaction type: [One-way announcement/Two-way conversation]\n"
                "   - Name found: [Contestant name if mentioned]\n"
                "   - Key phrases: [List any winner-indicating dialogue]\n"
                "   - Decision made: [Prize choice if mentioned]\n"
                "3. Classification: [Question announcement/Winner interaction]\n"
                "4. Continue with question: [YES/NO]\n\n"
                "IMPORTANT: Only classify as winner if there's clear evidence of two-way conversation with a contestant.\n"
                "Question announcements should be marked as 'Continue with question: YES'"
            )

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": 300,
                    "temperature": 0,
                    "top_p": 0.1
                },
                timeout=30
            )
            response.raise_for_status()
            analysis = response.json()["choices"][0]["message"]["content"].strip()

            logger.info(f"📝 Conversation Analysis Results:\n{analysis}")
            
            # Check both conditions explicitly
            is_winner = "Winner conversation found: YES" in analysis
            continue_question = "Continue with question: YES" in analysis
            
            logger.info(f"Winner detected: {is_winner}, Continue with question: {continue_question}")
            
            return is_winner, continue_question
            
        except Exception as e:
            logger.error(f"❌ Conversation analysis failed: {str(e)}")
            logger.exception("Full error traceback:")
            return False, True  # Default to continuing with question on error

    def save_master_response(self, response):
        """Saves the master's response to a file with timestamp."""
        try:
            # Skip saving if response indicates no A/B question was found
            if "does not contain an A/B format question" in response:
                logger.info("Skipping saving non-answer response to master file")
                return
                
            # Clean up the response if needed
            clean_response = response.strip()
            if clean_response.startswith("'") and clean_response.endswith("'"):
                clean_response = clean_response[1:-1]
                
            timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            with open(MASTER_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp}: {clean_response}\n")
            logger.info(f"Saved master response to {MASTER_FILE}: {clean_response}")
        except Exception as e:
            logger.error(f"Failed to save master response: {str(e)}")

    def generate_gpt_response(self, text, role="student"):
        """Generates a GPT-based response based on the given role (student/master)."""
        try:
            if role == "student":
                system_message = (
                    "You are analyzing a competition transcript. "
                    "Your task is to extract a specific A/B question and provide a confident answer."
                )
                max_tokens = 300
            else:  # master role
                system_message = (
                    "You are validating a student's analysis of a competition transcript. "
                    "Copy their A/B answer or provide a corrected version."
                )
                max_tokens = 60

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0,
                    "top_p": 0.1
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

    def process_trigger(self, alarm_id):
        """Processes an alarm trigger, recording, transcribing, and analyzing the audio."""
        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
        logger.info(f"\n=== Processing trigger for {alarm_id} at {timestamp} ===\n")

        file_paths = {
            'wav': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.wav"),
            'mp3': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.mp3")
        }

        try:
            logger.info(f"Starting {RECORDING_DURATION} seconds recording...")
            command = [
                "ffmpeg", "-y",
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
                "ffmpeg", "-y",
                "-i", file_paths['wav'],
                "-codec:a", "libmp3lame",
                "-qscale:a", "2",
                file_paths['mp3']
            ]
            subprocess.run(command, check=True, capture_output=True)
            logger.info(f"MP3 conversion completed: {file_paths['mp3']}")

            logger.info("Starting Whisper transcription...")
            transcription = self.transcribe_audio(file_paths['mp3'])
            
            if transcription:
                logger.info(f"Transcription completed: {transcription}")
                logger.info("\n🔍 Starting conversation analysis...")
                
                # Add explicit logging before and after analysis call
                logger.info("Calling analyze_conversation method...")
                is_winner, continue_question = self.analyze_conversation(transcription)
                logger.info(f"Analysis complete - Winner: {is_winner}, Continue: {continue_question}")

                if is_winner:
                    logger.info("🏆 Winner conversation detected - skipping question processing")
                    return

                if continue_question:
                    logger.info("📢 Question announcement detected - proceeding with processing")
                    student_analysis = self.generate_gpt_response(transcription, "student")
                    if student_analysis:
                        logger.info(f"Student Analysis completed: {student_analysis}")
                        master_response = self.generate_gpt_response(student_analysis, "master")
                        logger.info(f"Master Validation Result: {master_response}")
                        
                        # Save master response to file
                        if master_response:
                            self.save_master_response(master_response)
                else:
                    logger.info("No winner and no question detected - skipping processing")
                
                # Clean up after processing
                try:
                    if os.path.exists(file_paths['wav']):
                        os.remove(file_paths['wav'])
                        logger.info(f"Cleaned up WAV file: {file_paths['wav']}")
                    
                    # Move processed MP3 to processed directory
                    processed_mp3 = os.path.join(PROCESSED_DIR, os.path.basename(file_paths['mp3']))
                    if os.path.exists(file_paths['mp3']):
                        os.rename(file_paths['mp3'], processed_mp3)
                        logger.info(f"Moved processed MP3 to: {processed_mp3}")
                except Exception as cleanup_error:
                    logger.warning(f"Cleanup error: {str(cleanup_error)}")

        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            logger.exception("Full error traceback:")



def handle_comp(data):
    try:
        global last_alarm_time, audio_processor, last_processed_alarm_time


        if is_in_cooldown():
            logger.info("❄️ Ignoring callback due to cooldown period")
            return 

        alarm_id = detect_alarm(data)
        if alarm_id:
            logger.info(f"✅ Alarm detected: {alarm_id}")
            if not audio_processor:
                audio_processor = AudioProcessor()

            audio_processor.executor.submit(audio_processor.process_trigger, alarm_id)
            return jsonify({"status": "success", "message": f"Alarm {alarm_id} processed"}), 200
        else:
            return jsonify({"status": "success", "message": "No alarm detected"}), 200

    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        logger.exception("Full error traceback:")
        return jsonify({"status": "error", "message": "Callback error"}), 500


def comp_make_me_a_millionaire(data):
    try:
        
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        
        timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
        startup_message = f"Starting Make Me a Millionaire Monitor System at {timestamp}"
        logger.info("\n" + "="*50)
        logger.info(startup_message)
        logger.info("="*50 + "\n")
        
                
        logger.info("Audio processor initialized globally")
        logger.info("Monitoring Status: Active")
        logger.info(f"Monitoring for Alarms: {', '.join(VALID_ALARMS)}")
        logger.info(f"Cooldown Period: {COOLDOWN_DURATION} seconds")
        

        redis_manager.redis_client.set("COOLDOWN_DURATION", COOLDOWN_DURATION,ex=COOLDOWN_DURATION)

        
        handle_comp(data)
        
        
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
        logger.exception("Full startup error traceback:")
