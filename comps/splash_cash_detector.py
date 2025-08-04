#!/usr/bin/env python3
"""
Heart Radio Splash Cash Competition Outcome Detection Script
Detects win/lose outcomes from live radio stream after alarm trigger
"""


import time

import requests
from datetime import datetime
from constants import LIVE_STREAM_URL, OPENAI_API_KEY, WHISPER_API_URL, GPT_API_URL
from logger import logger
from redis_cache import RedisContactManager

# ============= TIMING CONTROLS =============
INITIAL_DELAY_MINUTES = 2         # Wait time after alarm before recording starts
CHUNK_DURATION_MINUTES = 2         # Length of each recording chunk
CHUNK_OVERLAP_SECONDS = 30         # Overlap between chunks to avoid lost conversation
MAX_RECORDING_MINUTES = 46         # Maximum total recording time
OUTCOME_CHECK_MINUTES = 4          # Start checking for outcomes after this time
NEXT_ROUND_WAIT_MINUTES = 3        # Additional recording time after outcome to get next round timing
TARGET_NOTIFICATION_MINUTES = 2    # Goal: notify within this time of outcome
MAX_SMS_LENGTH = 160

# ============= SMS TEMPLATES =============
WIN_SMS_TEMPLATE = "Winner - prize has been won! Enter next round in 40mins - Text **CASH** to **82122** or call 03308809118"
LOSE_SMS_TEMPLATE = "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"
FALLBACK_MESSAGE = "The call has been made. Are you the lucky winner? If not, next round starts again soon. Get ready, another chance to win is just around the corner!"

# ============= FILE PATHS =============
CHUNK_DIR = "./audio_chunks/"
TRANSCRIPT_FILE = "session_transcript.txt"
GPT_RESPONSE_FILE = "splash_gptmessage.txt"
LOG_FILE = "splash_processing.log"



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

BULLETPROOF_ANALYSIS_PROMPT = """You are analyzing a UK radio transcript from Heart Radio's "Splash the Cash" competition. You must ONLY analyze the content and return the exact JSON format requested.

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
WIN PHRASES: "congratulations", "you've won", "you just won £[amount]", "brilliant you've done it", "heart splash the cash" (correct phrase said)
LOSE PHRASES: "didn't answer", "wrong phrase", "not the right words", "that's not correct", "rolls over", "better luck next time", "didn't say the phrase"

CRITICAL RULES:
- If you find ONLY Stage 1 or 2: outcome = "UNKNOWN" (call in progress, keep recording)
- If you find presenter just talking ABOUT the competition: call_made = false
- ONLY declare WIN/LOSE if you find clear Stage 3 outcome phrases
- Be extremely conservative - when in doubt, use UNKNOWN

YOUR TASKS:
1. Determine if a genuine live call to a listener occurred
2. Identify the outcome: WIN, LOSE, or UNKNOWN
3. Generate SMS using the exact templates provided

TRANSCRIPT TO ANALYZE:
{transcript_text}

SMS TEMPLATES TO USE:
- WIN: "Winner - prize has been won! Enter next round in 40mins - Text **CASH** to **82122** or call 03308809118"
- LOSE: "No winner. Jackpot rollover! You can now enter next round - Text **CASH** to **82122** or call 03308809118"

RESPOND ONLY IN THIS EXACT JSON FORMAT - NO OTHER TEXT:
{{
"call_made": true/false,
"outcome": "WIN"/"LOSE"/"UNKNOWN",
"sms_message": "exact SMS using templates above",
"confidence": "high"/"medium"/"low",
"stage_1_call_initiated": true/false,
"stage_2_call_completed": true/false,
"stage_3_clear_outcome": true/false
}}

CONSTRAINTS:
- DO NOT include any text outside the JSON
- Use ONLY the SMS templates provided above
- Use only the outcomes: WIN, LOSE, or UNKNOWN
- If unsure, use UNKNOWN
- ONLY use WIN/LOSE if you find definitive outcome phrases (Stage 3)
- Be extremely conservative - prefer UNKNOWN over wrong decisions
- DO NOT extract or mention any timing information"""


# ============= GLOBAL STATE =============
class SplashCashDetector:
    def __init__(self):
        self.logger = logger
        self.session_id = None
        self.is_recording = False
        self.chunks_recorded = 0
        self.outcome_detected = False
        self.call_detected = False
        self.session_start_time = None
        self.transcript_content = ""
        
        # Create directories
        from pathlib import Path
        Path(CHUNK_DIR).mkdir(exist_ok=True)
        
        self.logger.info("=== Splash Cash Detector Initialized ===")

    
    def start_detection_session(self):
        """Start a new detection session after alarm trigger"""
        # Prevent multiple sessions
        if self.is_recording:
            self.logger.warning("Session already in progress. Ignoring new trigger.")
            return
            
        from datetime import datetime
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start_time = datetime.now()
        self.is_recording = False
        self.chunks_recorded = 0
        self.outcome_detected = False
        self.call_detected = False
        self.transcript_content = ""
        
        self.logger.info(f"=== NEW SESSION STARTED: {self.session_id} ===")
        self.logger.info(f"Alarm triggered at: {self.session_start_time}")
        
        # Start the detection process
        # import threading
        # threading.Thread(target=self._detection_workflow, daemon=True).start()
        self._detection_workflow()

    def _detection_workflow(self):
        """Main detection workflow"""
        try:
            # Phase 1: Initial delay
            self.logger.info(f"Waiting {INITIAL_DELAY_MINUTES} minutes before starting recording...")
            time.sleep(INITIAL_DELAY_MINUTES * 60)
            
            self.logger.info("Initial delay complete. Starting recording workflow.")
            
            # Phase 2: Recording and processing
            self.is_recording = True
            max_chunks = (MAX_RECORDING_MINUTES // CHUNK_DURATION_MINUTES) + 1
            
            for chunk_num in range(1, max_chunks + 1):
                if self.outcome_detected:
                    self.logger.info("Outcome detected. Stopping recording workflow.")
                    break
                
                # Record chunk
                chunk_file = self._record_chunk(chunk_num)
                if not chunk_file:
                    continue
                
                # Transcribe chunk
                transcript = self._transcribe_chunk(chunk_file)
                if transcript:
                    self.transcript_content += f"\n--- Chunk {chunk_num} ---\n{transcript}"
                    self._save_transcript()
                
                # Check for outcome after every chunk (if we have enough content)
                total_minutes = chunk_num * CHUNK_DURATION_MINUTES
                if total_minutes >= OUTCOME_CHECK_MINUTES and not self.outcome_detected:
                    self.logger.info(f"Sufficient content recorded ({total_minutes} mins). Starting analysis...")
                    self._analyze_transcript()
            
            # Timeout fallback
            if not self.outcome_detected:
                if self.call_detected:
                    self.logger.warning("Maximum recording time reached without outcome detection")
                    self._send_fallback_message()
                else:
                    self.logger.info("No call detected during entire recording session. No SMS will be sent.")
                    # Save no-call response
                    no_call_response = {
                        "outcome": "NO_CALL_DETECTED",
                        "message": "No competition call was detected in the audio stream",
                        "timestamp": datetime.now().isoformat()
                    }
                    import json
                    with open(GPT_RESPONSE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(no_call_response, f, indent=2)
            
        except Exception as e:
            self.logger.error(f"Error in detection workflow: {e}")
            self._send_fallback_message()
        finally:
            self._cleanup_session()

    def _record_chunk(self, chunk_num):
        """Record a single audio chunk using ffmpeg"""
        try:
            import subprocess, os
            # For live streams, we record in real-time chunks (no seeking)
            duration = CHUNK_DURATION_MINUTES * 60 + CHUNK_OVERLAP_SECONDS
            
            chunk_filename = f"session_{self.session_id}_chunk_{chunk_num:02d}.mp3"
            chunk_path = os.path.join(CHUNK_DIR, chunk_filename)
            
            self.logger.info(f"Recording chunk {chunk_num}: {chunk_filename} (duration: {duration}s)")
            
            # ffmpeg command for live stream recording
            cmd = [
                '/usr/bin/ffmpeg',
                '-i', LIVE_STREAM_URL,
                '-t', str(duration),  # Record for this duration
                '-acodec', 'libmp3lame',  # Use libmp3lame for better compatibility
                '-ab', '128k',
                '-ar', '44100',  # Sample rate
                '-ac', '2',      # Stereo
                '-y',            # Overwrite output file
                '-loglevel', 'error',  # Reduce ffmpeg output
                chunk_path
            ]
            
            self.logger.info(f"Running ffmpeg command: {' '.join(cmd)}")
            
            # Record chunk with timeout
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 60)
            
            if result.returncode == 0:
                if os.path.exists(chunk_path):
                    file_size = os.path.getsize(chunk_path)
                    self.logger.info(f"Chunk {chunk_num} recorded successfully. Size: {file_size} bytes")
                    self.chunks_recorded += 1
                    return chunk_path
                else:
                    self.logger.error(f"Chunk file was not created: {chunk_path}")
                    return None
            else:
                self.logger.error(f"ffmpeg error for chunk {chunk_num}:")
                self.logger.error(f"Return code: {result.returncode}")
                self.logger.error(f"stderr: {result.stderr}")
                self.logger.error(f"stdout: {result.stdout}")
                return None
                
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout recording chunk {chunk_num} after {duration + 60} seconds")
            return None
        except Exception as e:
            self.logger.error(f"Error recording chunk {chunk_num}: {e}")
            return None

    def _transcribe_chunk(self, chunk_file):
        """Transcribe audio chunk using Whisper API"""
        try:
            import os
            self.logger.info(f"Transcribing: {os.path.basename(chunk_file)}")
            
            headers = {
                'Authorization': f'Bearer {OPENAI_API_KEY}'
            }
            
            with open(chunk_file, 'rb') as audio_file:
                files = {
                    'file': audio_file,
                    'model': (None, 'whisper-1'),
                    'language': (None, 'en')
                }
                
                response = requests.post(WHISPER_API_URL, headers=headers, files=files, timeout=120)
            
            if response.status_code == 200:
                transcript = response.json().get('text', '')
                self.logger.info(f"Transcription completed. Length: {len(transcript)} characters")
                return transcript
            else:
                self.logger.error(f"Whisper API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error transcribing chunk: {e}")
            return None
    
    def _save_transcript(self):
        """Save current transcript to file"""
        try:
            with open(TRANSCRIPT_FILE, 'w', encoding='utf-8') as f:
                f.write(self.transcript_content)
            self.logger.info("Transcript saved to file")
        except Exception as e:
            self.logger.error(f"Error saving transcript: {e}")

    def _analyze_transcript(self):
        """Analyze transcript with GPT-3.5 for outcome detection"""
        try:
            self.logger.info("Analyzing transcript with GPT-3.5 Turbo...")
            
            # Bulletproof analysis (no timing extraction)
            analysis = self._call_gpt_analysis(self.transcript_content)
            if not analysis:
                return
            
            self.logger.info(f"GPT Analysis Result: {analysis}")
            
            # Check if a call was made
            if analysis.get('call_made', False):
                self.call_detected = True
            
            outcome = analysis.get('outcome', 'UNKNOWN')
            
            if outcome in ['WIN', 'LOSE']:
                self.logger.info(f"{outcome} detected! Recording additional time for complete context...")
                # Record additional time to ensure we have complete context
                self._record_additional_context(analysis)
            elif outcome == 'UNKNOWN':
                self.logger.info("Outcome still unknown. Continuing recording...")
                
        except Exception as e:
            self.logger.error(f"Error analyzing transcript: {e}")

    def _record_additional_context(self, initial_analysis):
        """Record additional chunks to ensure complete context"""
        try:
            outcome = initial_analysis.get('outcome')
            
            # Record additional chunks for complete context
            additional_chunks = NEXT_ROUND_WAIT_MINUTES // CHUNK_DURATION_MINUTES + 1
            start_chunk = self.chunks_recorded + 1
            end_chunk = start_chunk + additional_chunks
            
            self.logger.info(f"Recording {additional_chunks} additional chunks for complete context")
            
            for chunk_num in range(start_chunk, end_chunk + 1):
                chunk_file = self._record_chunk(chunk_num)
                if chunk_file:
                    transcript = self._transcribe_chunk(chunk_file)
                    if transcript:
                        self.transcript_content += f"\n--- Chunk {chunk_num} ---\n{transcript}"
                        self._save_transcript()
            
            # Re-analyze with complete transcript
            final_analysis = self._call_gpt_analysis(self.transcript_content)
            if final_analysis:
                self.logger.info(f"Final Analysis Result: {final_analysis}")
                self._finalize_and_send_sms(final_analysis)
            else:
                # Use initial analysis if final analysis fails
                self._finalize_and_send_sms(initial_analysis)
            
        except Exception as e:
            self.logger.error(f"Error recording additional context: {e}")
            self._finalize_and_send_sms(initial_analysis)

    def _finalize_and_send_sms(self, analysis):
        """Generate final SMS and send notification"""
        try:
            outcome = analysis.get('outcome', 'UNKNOWN')
            
            # Generate SMS message using simple templates
            if outcome == 'WIN':
                sms_message = WIN_SMS_TEMPLATE
            elif outcome == 'LOSE':
                sms_message = LOSE_SMS_TEMPLATE
            else:
                sms_message = FALLBACK_MESSAGE
            
            # Create final result
            from datetime import datetime
            import json
            final_result = {
                "call_made": analysis.get('call_made', False),
                "outcome": outcome,
                "sms_message": sms_message,
                "confidence": analysis.get('confidence', 'medium'),
                "stage_1_call_initiated": analysis.get('stage_1_call_initiated', False),
                "stage_2_call_completed": analysis.get('stage_2_call_completed', False),
                "stage_3_clear_outcome": analysis.get('stage_3_clear_outcome', False),
                "timestamp": datetime.now().isoformat()
            }
            
            # Save final response
            with open(GPT_RESPONSE_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_result, f, indent=2)
            
            # Send SMS
            self._send_sms(sms_message)
            self.outcome_detected = True
            
        except Exception as e:
            self.logger.error(f"Error finalizing SMS: {e}")
            self._send_fallback_message()
            self.outcome_detected = True
    
    def _call_gpt_analysis(self, transcript):
        """Call GPT-3.5 Turbo for transcript analysis"""
        try:
            prompt = BULLETPROOF_ANALYSIS_PROMPT.format(transcript_text=transcript)
            
            headers = {
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            data = {
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
            
            response = requests.post(GPT_API_URL, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                gpt_response = response.json()
                content = gpt_response['choices'][0]['message']['content']
                
                # Validate and parse JSON response
                is_valid, result = self._validate_gpt_response(content)
                if is_valid:
                    return result
                else:
                    self.logger.error(f"Invalid GPT response: {result}")
                    return None
            else:
                self.logger.error(f"GPT API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error calling GPT: {e}")
            return None
    
    def _validate_gpt_response(self, response_text):
        """Validate GPT response format"""
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
                    self.logger.warning("WIN/LOSE declared without all stages detected. Forcing UNKNOWN.")
                    data["outcome"] = "UNKNOWN"
                
            return True, data
            
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON response: {e}"
    
    def _send_sms(self, message):
        """Send SMS notification (placeholder - implement your SMS service)"""
        try:
            self.logger.info(f"SMS NOTIFICATION: {message}")
            
            # TODO: Implement actual SMS sending logic here
            # This could be Twilio, AWS SNS, or your existing SMS service
            manager = RedisContactManager()
            manager.redis_client.set("SPLASH_MESSAGE",message)
            # For now, just log the message
            print(f"\n🔔 SMS ALERT: {message}\n")
            
        except Exception as e:
            self.logger.error(f"Error sending SMS: {e}")
    
    def _send_fallback_message(self):
        """Send fallback message when outcome cannot be determined"""
        self.logger.info("Sending fallback message")
        self._send_sms(FALLBACK_MESSAGE)
        
        # Save fallback response
        from datetime import datetime
        import json
        fallback_response = {
            "outcome": "TIMEOUT",
            "message": FALLBACK_MESSAGE,
            "timestamp": datetime.now().isoformat()
        }
        with open(GPT_RESPONSE_FILE, 'w', encoding='utf-8') as f:
            json.dump(fallback_response, f, indent=2)
    
    def _cleanup_session(self):
        """Clean up session files and reset state"""
        try:
            import os
            self.logger.info("Cleaning up session...")
            
            # Clean up transcript file for next session
            if os.path.exists(TRANSCRIPT_FILE):
                os.remove(TRANSCRIPT_FILE)
                self.logger.info("Transcript file cleaned up")
            
            self.is_recording = False
            self.logger.info(f"=== SESSION {self.session_id} COMPLETED ===")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

# ============= ASYNC FUNCTION FOR SERVER INTEGRATION =============
def detect_splash_cash_outcome_async():
    """Function called by splash.py - creates detector and starts session"""
    detector = SplashCashDetector()
    detector.start_detection_session()

# # ============= MAIN EXECUTION =============
# def main():
#     """Main function for testing"""
#     detector = SplashCashDetector()
    
#     print("Splash Cash Detector Ready!")
#     print("Call detector.start_detection_session() to begin detection after alarm trigger")
    
#     return detector

# def start_splash_the_cash():
#     # Create detector instance
#     detector = main()
    
#     # Keep script running for testing
#     try:
#         detector.start_detection_session()
            
#     except KeyboardInterrupt:
#         print("\nScript terminated by user")
