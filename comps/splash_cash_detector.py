import os
import time
import logging
import requests
from datetime import datetime, timedelta
from logger import logger
from constants import LIVE_STREAM_URL, OPENAI_API_KEY, WHISPER_API_URL, GPT_API_URL


# ============= TIMING SETTINGS =============
RECORD_DELAY_SECONDS = 60              # Wait time after alarm trigger
RECORD_DURATION_SECONDS = 120          # How long to record
FALLBACK_NEXT_ROUND_MINUTES = 40

# ============= SMS MESSAGES =============
WIN_SMS_WITH_TIME = "Winner - prize has been won! Enter next round after {time} - Text **CASH** to **82122** or call 03308809118"
WIN_SMS_FALLBACK = "Winner - prize has been won! Enter next round in 40mins - Text **CASH** to **82122** or call 03308809118"
LOSE_SMS_WITH_TIME = "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"
LOSE_SMS_FALLBACK = "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"

# ============= FUNCTION TO RECORD AUDIO =============
def record_audio_from_stream(duration=RECORD_DURATION_SECONDS):
    try:
        logger.info("Recording stream...")
        response = requests.get(LIVE_STREAM_URL, stream=True, timeout=15)
        response.raise_for_status()

        audio_data = b""
        start_time = time.time()

        for chunk in response.iter_content(chunk_size=1024):
            audio_data += chunk
            if time.time() - start_time > duration:
                break

        logger.info("Recording complete.")
        return audio_data
    except Exception as e:
        logger.error(f"Stream recording failed: {e}")
        return None

# ============= FUNCTION TO TRANSCRIBE =============
def transcribe_audio(audio_data):
    try:
        logger.info("Sending audio to Whisper...")
        response = requests.post(
            WHISPER_API_URL,
            files={"file": ("audio.mp3", audio_data, "audio/mpeg")},
            timeout=60
        )
        response.raise_for_status()
        transcript = response.json().get("text", "")
        logger.info(f"Transcript received: {transcript}")
        return transcript
    except Exception as e:
        logger.exception("Transcription failed")
        return ""

# ============= FUNCTION TO INTERPRET RESULT =============
def analyze_outcome(transcript):
    try:
        logger.info("Sending transcript to GPT for outcome detection...")
        prompt = f"""Determine the competition result based on this radio conversation:
---
{transcript}
---
Respond with exactly one of the following:
- WIN WITH TIME: if a winner is announced and time is mentioned
- WIN FALLBACK: if a winner is announced but no time is mentioned
- LOSE WITH TIME: if no winner and next round time is mentioned
- LOSE FALLBACK: if no winner and no time is mentioned
Also extract the time if mentioned."""

        response = requests.post(
            GPT_API_URL,
            json={"prompt": prompt},
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"GPT Result: {result}")
        return result.get("outcome", ""), result.get("time", "")
    except Exception as e:
        logger.exception("GPT outcome analysis failed")
        return "LOSE FALLBACK", ""

# ============= FUNCTION TO SEND MESSAGE =============
def send_sms(outcome, time_str=None):
    try:
        logger.info(f"Preparing to send message for outcome: {outcome}")
        if outcome == "WIN WITH TIME":
            message = WIN_SMS_WITH_TIME.format(time=time_str)
        elif outcome == "WIN FALLBACK":
            message = WIN_SMS_FALLBACK
        elif outcome == "LOSE WITH TIME":
            message = LOSE_SMS_WITH_TIME.format(time=time_str)
        else:
            message = LOSE_SMS_FALLBACK

        payload = {
            "competition": "Splash the Cash",
            "message": message
        }
        # Replace with your messaging server endpoint
        messaging_url = "http://localhost:5000/api/send_competition_update"
        response = requests.post(messaging_url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Message sent successfully: {message}")
    except Exception as e:
        logger.exception("Failed to send SMS update")

# ============= MAIN LOGIC =============
def main():
    logger.info("=== Splash the Cash script started ===")
    time.sleep(RECORD_DELAY_SECONDS)

    audio = record_audio_from_stream()
    if not audio:
        logger.error("No audio captured. Exiting.")
        return

    transcript = transcribe_audio(audio)
    if not transcript:
        logger.error("Transcript empty. Exiting.")
        return

    outcome, time_str = analyze_outcome(transcript)
    send_sms(outcome, time_str)
    logger.info("=== Script complete ===")

if __name__ == "__main__":
    main()
