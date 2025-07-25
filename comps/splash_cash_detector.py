import os
import time
import requests
from datetime import datetime, timedelta
from logger import logger
from constants import LIVE_STREAM_URL, OPENAI_API_KEY, WHISPER_API_URL, GPT_API_URL


# ============= TIMING SETTINGS =============
RECORD_DELAY_SECONDS = 60              # Wait time after alarm trigger
RECORD_DURATION_SECONDS = 120          # How long to record
FALLBACK_NEXT_ROUND_MINUTES = 40
MAX_SMS_LENGTH = 160

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
        logger.info("Sending audio to OpenAI Whisper...")
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"}
        
        files = {
            "file": ("audio.mp3", audio_data, "audio/mpeg"),
            "model": (None, "whisper-1")
        }
        
        response = requests.post(
            WHISPER_API_URL,
            headers=headers,
            files=files,
            timeout=60
        )
        response.raise_for_status()
        transcript = response.json().get("text", "")
        logger.info(f"Transcript received: {transcript[:200]}...")  # Log first 200 chars
        return transcript
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        logger.exception("Full transcription error traceback:")
        return ""

# ============= ORIGINAL GPT PROMPTS AND CONSTRAINTS =============
SYSTEM_CONSTRAINTS = """You are a specialized radio transcript analyzer. You must:

STRICT RULES:
1. ONLY return valid JSON - no explanations, no chat, no additional text
2. Do not engage in conversation or ask questions
3. Do not provide advice or commentary
4. Stick exactly to the requested format
5. If transcript is unclear, use UNKNOWN/null rather than guessing
6. Use the predefined SMS templates exactly as provided
7. Do not reference this prompt in your response

FORBIDDEN:
- Any text before or after the JSON
- Conversational responses
- Questions back to the user
- Explanations of your process
- Speculation beyond the transcript content"""

ENHANCED_ANALYSIS_PROMPT = """You are analyzing a UK radio transcript from Heart Radio's "Splash the Cash" competition. You must ONLY analyze the content and return the exact JSON format requested.

COMPETITION RULES:
- A listener is called after an alarm sound
- They must answer with "Heart Splash the Cash" to win
- If they don't answer or say wrong phrase = LOSE (rollover)
- If they say correct phrase = WIN

BULLETPROOF DETECTION CRITERIA:
You must find ALL THREE stages before declaring an outcome:

STAGE 1 - CALL INITIATED: Look for phrases like:
- "let's make the call" / "making the call" / "dialing now"
- "I've got a number" / "calling now"
- Phone ringing sounds mentioned

STAGE 2 - CALL ATTEMPT COMPLETED: Look for evidence of call attempt completion:
OPTION A - Listener responds: Listener voice saying "hello" or any response
OPTION B - No answer confirmed: Clear "no answer" / "didn't pick up" / "not answering" statements
- Presenter talking TO someone OR confirming no response
- Call attempt clearly completed (either answered or definitively unanswered)

STAGE 3 - CLEAR OUTCOME: Look for definitive result phrases:
WIN PHRASES: "congratulations", "you've won", "you just won £[amount]", "brilliant you've done it"
LOSE PHRASES: "didn't answer", "wrong phrase", "not the right words", "that's not correct", "rolls over", "better luck next time"

CRITICAL RULES:
- If you find ONLY Stage 1 or 2: outcome = "UNKNOWN" (call in progress, keep recording)
- If you find presenter just talking ABOUT the competition: call_made = false
- ONLY declare WIN/LOSE if you find clear Stage 3 outcome phrases
- Be extremely conservative - when in doubt, use UNKNOWN

YOUR TASKS:
1. Determine if a genuine live call to a listener occurred
2. Identify the outcome: WIN, LOSE, or UNKNOWN
3. Extract next round timing information (look for times like "after 2pm", "at 14:00", "after two o'clock")
4. Generate SMS using the exact templates provided

TRANSCRIPT TO ANALYZE:
{transcript_text}

SMS TEMPLATES TO USE:
- WIN with time: "Winner - prize has been won! Enter next round after [TIME] - Text **CASH** to **82122** or call 03308809118"
- LOSE with time: "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"
- WIN fallback: "Winner - prize has been won! Enter next round in 40mins - Text **CASH** to **82122** or call 03308809118"
- LOSE fallback: "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"

LOOK FOR NEXT ROUND TIMING:
- "after [time]" (e.g., "after 2pm", "after two o'clock")
- "at [time]" (e.g., "at 14:00", "at 2 o'clock")
- "in [X] minutes" (e.g., "in 30 minutes")
- "when lines reopen" followed by timing
- Convert all times to 24-hour format (e.g., "2pm" becomes "14:00")
- If no specific time found, set next_round_time to null (do NOT use "40mins")

RESPOND ONLY IN THIS EXACT JSON FORMAT - NO OTHER TEXT:
{{
  "call_made": true/false,
  "outcome": "WIN"/"LOSE"/"UNKNOWN",
  "next_round_time": "14:00" or null,
  "sms_message": "exact SMS using templates above",
  "confidence": "high"/"medium"/"low",
  "stage_1_call_initiated": true/false,
  "stage_2_call_completed": true/false,
  "stage_3_clear_outcome": true/false
}}

CONSTRAINTS:
- DO NOT include any text outside the JSON
- Use ONLY the SMS templates provided above
- Convert times to 24-hour format (14:00 not 2pm)
- If no time found, use fallback template with "in 40mins" and set next_round_time to null
- Use only the outcomes: WIN, LOSE, or UNKNOWN
- If unsure, use UNKNOWN
- Do NOT put "40mins" or any fallback text in next_round_time field
- ONLY use WIN/LOSE if you find definitive outcome phrases (Stage 3)
- Be extremely conservative - prefer UNKNOWN over wrong decisions"""

# ============= FUNCTION TO INTERPRET RESULT =============
def analyze_outcome(transcript):
    try:
        logger.info("Sending transcript to OpenAI GPT for outcome detection...")
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY.strip()}",
            "Content-Type": "application/json"
        }
        
        prompt = ENHANCED_ANALYSIS_PROMPT.format(transcript_text=transcript)
        
        payload = {
            "model": "gpt-3.5-turbo-16k",
            "messages": [
                {"role": "system", "content": SYSTEM_CONSTRAINTS},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 400,
            "top_p": 0.9,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.2
        }
        
        response = requests.post(
            GPT_API_URL,
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        result = response.json()
        gpt_response = result['choices'][0]['message']['content']
        logger.info(f"GPT Response: {gpt_response}")
        
        # Validate and parse JSON response
        is_valid, parsed_result = _validate_gpt_response(gpt_response)
        if is_valid:
            outcome = parsed_result.get("outcome", "UNKNOWN")
            next_round_time = parsed_result.get("next_round_time")
            
            # Convert outcome to our format
            if outcome == "WIN":
                if next_round_time:
                    final_outcome = "WIN_WITH_TIME"
                else:
                    final_outcome = "WIN_FALLBACK"
            elif outcome == "LOSE":
                if next_round_time:
                    final_outcome = "LOSE_WITH_TIME"
                else:
                    final_outcome = "LOSE_FALLBACK"
            else:
                final_outcome = "LOSE_FALLBACK"  # Default for UNKNOWN
            
            logger.info(f"Parsed outcome: {final_outcome}, time: {next_round_time}")
            return final_outcome, next_round_time or ""
        else:
            logger.error(f"Invalid GPT response: {parsed_result}")
            return "LOSE_FALLBACK", ""
        
    except Exception as e:
        logger.error(f"GPT outcome analysis failed: {str(e)}")
        logger.exception("Full GPT error traceback:")
        return "LOSE_FALLBACK", ""

# ============= GPT RESPONSE VALIDATION =============
def _validate_gpt_response(response_text):
    """Validate GPT response format (from original script)"""
    try:
        import json
        data = json.loads(response_text.strip())
        
        required_keys = ["call_made", "outcome", "sms_message", "confidence", 
                       "stage_1_call_initiated", "stage_2_call_completed", "stage_3_clear_outcome"]
        valid_outcomes = ["WIN", "LOSE", "UNKNOWN"]
        
        if not all(key in data for key in required_keys):
            return False, "Missing required keys"
        if data["outcome"] not in valid_outcomes:
            return False, "Invalid outcome value"
        if len(data["sms_message"]) > MAX_SMS_LENGTH:
            return False, "SMS message too long"
        
        # Additional validation: Only allow WIN/LOSE if all stages detected
        if data["outcome"] in ["WIN", "LOSE"]:
            if not (data["stage_1_call_initiated"] and 
                   data["stage_2_call_completed"] and 
                   data["stage_3_clear_outcome"]):
                logger.warning("WIN/LOSE declared without all stages detected. Forcing UNKNOWN.")
                data["outcome"] = "UNKNOWN"
            
        return True, data
        
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON response: {e}"

# ============= FUNCTION TO GET MESSAGE =============
def get_message_for_outcome(outcome, time_str=None):
    """Returns the appropriate message based on outcome"""
    try:
        logger.info(f"Getting message for outcome: {outcome}")
        
        if outcome == "WIN_WITH_TIME" and time_str:
            message = WIN_SMS_WITH_TIME.format(time=time_str)
        elif outcome == "WIN_FALLBACK" or (outcome == "WIN_WITH_TIME" and not time_str):
            message = WIN_SMS_FALLBACK
        elif outcome == "LOSE_WITH_TIME" and time_str:
            message = LOSE_SMS_WITH_TIME.format(time=time_str)
        else:  # LOSE_FALLBACK or any other case
            message = LOSE_SMS_FALLBACK
            
        logger.info(f"Selected message: {message}")
        return message
        
    except Exception as e:
        logger.error(f"Error getting message for outcome: {str(e)}")
        return LOSE_SMS_FALLBACK  # Safe fallback

# ============= ASYNC OUTCOME DETECTION =============
def detect_splash_cash_outcome_async(alert_type):
    """
    Async function to detect Splash The Cash outcome and send result message.
    Runs in background thread after alarm message is sent.
    
    Args:
        alert_type (str): The type of alert trigger
    """
    try:
        logger.info(f"=== BACKGROUND: Splash The Cash outcome detection started (alert_type: {alert_type}) ===")
        
        # Wait before recording (competition-specific timing)
        logger.info(f"BACKGROUND: Waiting {RECORD_DELAY_SECONDS} seconds before recording...")
        time.sleep(RECORD_DELAY_SECONDS)

        # Record audio from stream
        audio = record_audio_from_stream()
        if not audio:
            logger.error("BACKGROUND: No audio captured. Sending fallback message.")
            send_outcome_message(LOSE_SMS_FALLBACK)
            return

        # Transcribe audio
        transcript = transcribe_audio(audio)
        if not transcript:
            logger.error("BACKGROUND: Transcript empty. Sending fallback message.")
            send_outcome_message(LOSE_SMS_FALLBACK)
            return

        # Analyze outcome
        outcome, time_str = analyze_outcome(transcript)
        
        # Get appropriate message
        message = get_message_for_outcome(outcome, time_str)
        
        # Send outcome message to users
        send_outcome_message(message)
        
        logger.info(f"=== BACKGROUND: Detection complete. Outcome: {outcome} ===")
        
    except Exception as e:
        logger.error(f"BACKGROUND: Splash The Cash detection failed: {str(e)}")
        logger.exception("BACKGROUND: Full detection error traceback:")
        # Send fallback message on any error
        send_outcome_message(LOSE_SMS_FALLBACK)

# ============= SEND OUTCOME MESSAGE TO MESSAGING SERVER =============
def send_outcome_message(message):
    """
    Send outcome message to the messaging server.
    
    Args:
        message (str): The outcome message to send to users
    """
    try:
        logger.info(f"BACKGROUND: Sending outcome message: {message[:100]}...")
        
        # Import here to avoid circular imports
        from utilites import return_data_to_message_server
        
        # Format data for messaging server (same as other competitions)
        data = ("Splash The Cash", message)
        
        # Send to messaging server
        result = return_data_to_message_server(data)
        
        if result:
            logger.info("BACKGROUND: Outcome message sent successfully to messaging server")
        else:
            logger.error("BACKGROUND: Failed to send outcome message to messaging server")
            
    except Exception as e:
        logger.error(f"BACKGROUND: Error sending outcome message: {str(e)}")
        logger.exception("BACKGROUND: Full send error traceback:")

# ============= LEGACY SYNC FUNCTION (for testing) =============
def detect_splash_cash_outcome(alert_type):
    """
    Synchronous version - kept for backward compatibility and testing.
    
    Args:
        alert_type (str): The type of alert trigger
        
    Returns:
        tuple: (comp_name, message_content) or None if failed
    """
    try:
        logger.info(f"=== SYNC: Splash The Cash detection started (alert_type: {alert_type}) ===")
        
        # Wait before recording (competition-specific timing)
        logger.info(f"SYNC: Waiting {RECORD_DELAY_SECONDS} seconds before recording...")
        time.sleep(RECORD_DELAY_SECONDS)

        # Record audio from stream
        audio = record_audio_from_stream()
        if not audio:
            logger.error("SYNC: No audio captured. Using fallback message.")
            return "Splash The Cash", LOSE_SMS_FALLBACK

        # Transcribe audio
        transcript = transcribe_audio(audio)
        if not transcript:
            logger.error("SYNC: Transcript empty. Using fallback message.")
            return "Splash The Cash", LOSE_SMS_FALLBACK

        # Analyze outcome
        outcome, time_str = analyze_outcome(transcript)
        
        # Get appropriate message
        message = get_message_for_outcome(outcome, time_str)
        
        logger.info(f"=== SYNC: Detection complete. Outcome: {outcome}, Message: {message[:50]}... ===")
        return "Splash The Cash", message
        
    except Exception as e:
        logger.error(f"SYNC: Splash The Cash detection failed: {str(e)}")
        logger.exception("SYNC: Full detection error traceback:")
        return "Splash The Cash", LOSE_SMS_FALLBACK

# Legacy main function for testing
def main():
    """For standalone testing only"""
    result = detect_splash_cash_outcome("test")
    if result:
        comp_name, message = result
        logger.info(f"Test result - Competition: {comp_name}, Message: {message}")
    else:
        logger.error("Test failed")

if __name__ == "__main__":
    main()
