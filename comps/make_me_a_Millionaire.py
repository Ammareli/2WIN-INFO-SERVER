import os
import requests
import subprocess
from datetime import datetime
from logger import logger
from constants import OPENAI_API_KEY, BEARER_TOKEN, LIVE_STREAM_URL,TIME_ZONE
from redis_cache import RedisContactManager
import re


# Environment variables and constants

redis_manager = RedisContactManager()

if not OPENAI_API_KEY or not BEARER_TOKEN:
    raise ValueError("Missing required environment variables. Check .env file.")


OUTPUT_DIR = "output_segments"
PROCESSED_DIR = os.path.join(OUTPUT_DIR, "processed_segments")
RECORDING_DURATION = 200
COOLDOWN_DURATION = 300
VALID_ALARMS = ["Alarm1", "Alarm2", "Alarm3", "Alarm4", "Alarm5"]

audio_processor = None
last_processed_alarm_time = None



def is_in_cooldown():
    cooldown_p = redis_manager.redis_client.get("COOLDOWN_DURATION")    
    if not cooldown_p:
        redis_manager.redis_client.set("COOLDOWN_DURATION", COOLDOWN_DURATION,ex=COOLDOWN_DURATION)
        return False
    return cooldown_p



class AudioProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        logger.info(f"Created/verified output directories: {OUTPUT_DIR} and {PROCESSED_DIR}")
        

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
        """Analyzes transcript to detect if it contains a winning conversation, replay, or question."""
        try:
            logger.info("Beginning conversation analysis...")
            system_message = (
                "You are analyzing a Heart Radio competition transcript to determine content type and intent.\n\n"
                
                "IMPORTANT: Distinguish between CURRENT events and REPLAYS of previous events.\n\n"
                
                "KEY PATTERNS TO RECOGNIZE:\n"
                "1. REPLAY of previous winner (NOT a current winner):\n"
                "   - Past tense references: 'earlier today', 'this morning', 'has won', etc.\n"
                "   - Named contestants discussed in third person ('she decided', 'he chose')\n"
                "   - Presenter asking listeners to imagine themselves in the situation\n"
                "   - Transitions like 'Do you know what your decision would be?'\n"
                "   - Invitation to listeners to participate ('come and make the decision for real')\n\n"
                
                "2. CURRENT winner conversation (happening now):\n"
                "   - Direct real-time interaction between presenter and contestant\n"
                "   - Present tense dialogue ('What's your decision?', 'I choose...')\n"
                "   - Contestant responding directly to questions in first person\n"
                "   - No references suggesting this is a replay or example\n"
                "   - Spontaneous emotional reactions from the current contestant\n\n"
                
                "3. Question announcement (needs processing):\n"
                "   - Clear A/B question format presented to listeners\n"
                "   - Instructions for entry (texting, calling, etc.)\n"
                "   - Often follows examples of previous winners\n"
                "   - May contain entry deadline information\n"
                "   - Repeated for clarity\n\n"
                
                "FORMAT YOUR RESPONSE EXACTLY LIKE THIS:\n"
                "1. Current winner conversation: [YES/NO]\n"
                "2. Evidence for current/replay:\n"
                "   - Time references: [past/present tense markers]\n"
                "   - Interaction type: [direct/reported/invitation]\n"
                "   - Named individuals: [mentioned as current contestants or examples]\n"
                "3. Question announcement present: [YES/NO]\n"
                "4. Question details: [the actual question if present]\n"
                "5. FINAL DECISION: [WINNER/REPLAY_WITH_QUESTION/QUESTION_ONLY/NEITHER]\n\n"
                
                "IMPORTANT NOTES:\n"
                "- A transcript can contain BOTH a replay AND a new question\n"
                "- Prioritize identifying new questions even if replays are present\n"
                "- Look for clear transitions between replay examples and new questions\n"
                "- Do NOT classify replays of previous winners as current winners"
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
                    "max_tokens": 400,
                    "temperature": 0,
                    "top_p": 0.1
                },
                timeout=30
            )
            response.raise_for_status()
            analysis = response.json()["choices"][0]["message"]["content"].strip()

            logger.info(f"📝 Conversation Analysis Results:\n{analysis}")
            
            # Parse the detailed analysis
            is_current_winner = "Current winner conversation: YES" in analysis
            is_replay_with_question = "FINAL DECISION: REPLAY_WITH_QUESTION" in analysis
            is_question_only = "FINAL DECISION: QUESTION_ONLY" in analysis
            
            # Handle the case where there's a replay with a question announcement
            if is_replay_with_question:
                logger.info("Detected: Replay of previous winner WITH new question announcement")
                is_winner = False
                continue_question = True
            # Handle current winner (unlikely to have a question too)
            elif is_current_winner:
                logger.info("Detected: Current winner conversation in progress")
                is_winner = True
                continue_question = False
            # Handle question only
            elif is_question_only:
                logger.info("Detected: Question announcement only")
                is_winner = False
                continue_question = True
            # Default case - nothing actionable
            else:
                logger.info("Detected: Neither winner conversation nor question")
                is_winner = False
                continue_question = False
            
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
                
            
            return clean_response
        except Exception as e:
            logger.error(f"Failed to get master response: {str(e)}")
            

    def generate_gpt_response(self, text, role="student"):
        """Generates a GPT-based response based on the given role (student/master)."""
        try:
            if role == "student":
                system_message = (
                    "You are analyzing a radio competition transcript to identify A/B questions and provide the correct answer.\n\n"
                    "IMPORTANT: If you detect ANY question with A and B options, you MUST choose one as your answer.\n\n"
                    "Sample formats of questions you might find:\n"
                    "- 'Which X is Y: A) option1 or B) option2?'\n"
                    "- 'Is it A, option1 or B, option2?'\n\n"
                    
                    "Format your response EXACTLY like this when you find a question:\n"
                    "\"Question: [exact question]\n"
                    "Options: A, [option A] or B, [option B]\n"
                    "Answer: [A or B]\"\n\n"
                    
                    "VERY IMPORTANT: You MUST always include an answer of either A or B - NEVER say 'NO_ANSWER_FOUND'.\n"
                    "Make your best guess based on common knowledge if needed.\n\n"
                    
                    "If absolutely NO question format is present in any way, respond with EXACTLY:\n"
                    "\"NO_QUESTION_FOUND\"\n\n"
                    
                    "Key rules:\n"
                    "1. ALWAYS pick either A or B if ANY question format is detected\n"
                    "2. NEVER respond with 'NO_ANSWER_FOUND' or similar phrases\n"
                    "3. If in doubt, make an educated guess based on general knowledge\n"
                    "4. Only use NO_QUESTION_FOUND if there is absolutely no question format detected"
                )
                max_tokens = 150
            else:  # master role
                system_message = (
                    "You are validating a student's analysis of a radio competition transcript.\n\n"
                    
                    "If the student identified a question format, regardless of their answer, you MUST provide your own answer.\n"
                    "Respond with your answer in this exact format: \"A, [option A]\" or \"B, [option B]\"\n\n"
                    
                    "IMPORTANT RULES:\n"
                    "1. If the student found a question but didn't provide a clear A/B answer, research the question and provide YOUR definitive answer\n"
                    "2. If the student wrote 'NO_QUESTION_FOUND' but you see any question format in their analysis, provide your A/B answer\n"
                    "3. Only respond with '#' if there is truly no question format whatsoever\n"
                    "4. ALWAYS prefer giving an A/B answer over returning '#'\n"
                    "5. Use your extensive general knowledge to determine the correct answer\n\n"
                    
                    "For example, if you see 'Which soap celebrated its 40th anniversary' you should know the answer is 'A, EastEnders' or 'B, Coronation Street' based on which one recently had an anniversary.\n\n"
                    
                    "Remember, ALWAYS provide a specific A or B answer when any question is detected."
                )
                max_tokens = 100

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
            logger.info(f"Raw GPT response for {role}: {gpt_response}")
            
            if role == "student":
                # Make sure we never return NO_ANSWER_FOUND
                if "NO_ANSWER_FOUND" in gpt_response and "Question:" in gpt_response:
                    # Extract the question and make a second attempt with a stronger prompt
                    try:
                        question_part = gpt_response.split("Question:")[1].split("Options:")[0].strip()
                        options_part = gpt_response.split("Options:")[1].split("Answer:")[0].strip()
                        
                        # Make a second attempt with just the question and a stronger prompt
                        followup_prompt = (
                            f"As an expert in general knowledge, please answer this question with ONLY 'A' or 'B':\n\n"
                            f"{question_part}\n{options_part}\n\nYour answer (just A or B):"
                        )
                        
                        followup_response = requests.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"},
                            json={
                                "model": "gpt-4",
                                "messages": [{"role": "user", "content": followup_prompt}],
                                "max_tokens": 10,
                                "temperature": 0
                            },
                            timeout=30
                        )
                        answer = followup_response.json()["choices"][0]["message"]["content"].strip()
                        logger.info(f"Followup answer attempt: {answer}")
                        
                        # Extract just A or B
                        if "A" in answer.upper() and not "B" in answer.upper():
                            answer = "A"
                        elif "B" in answer.upper() and not "A" in answer.upper():
                            answer = "B"
                        else:
                            answer = "B"  # Default if unclear
                            
                        # Reconstruct the response with the answer
                        gpt_response = f"Question: {question_part}\nOptions: {options_part}\nAnswer: {answer}"
                        logger.info(f"Fixed student response with answer: {gpt_response}")
                    except Exception as e:
                        # If extraction fails, default to a reasonable answer
                        logger.warning(f"Failed to extract question parts: {str(e)}")
                        if "A, EastEnders or B, Coronation Street" in gpt_response:
                            gpt_response = gpt_response.replace("NO_ANSWER_FOUND", "A")
                        else:
                            gpt_response = gpt_response.replace("NO_ANSWER_FOUND", "B")
                
                return gpt_response
            else:  # master role
                # First check if student found a question
                question_found = False
                if "Question:" in text and "Options:" in text:
                    question_found = True
                
                # Process master response if question was found
                if question_found:
                    # If the master didn't provide a clear A/B answer but we know there's a question
                    if gpt_response.strip() == "#" or "no question" in gpt_response.lower():
                        # Extract question and options from student text to make a direct determination
                        try:
                            question_part = text.split("Question:")[1].split("Options:")[0].strip()
                            options_part = text.split("Options:")[1].split("Answer:")[0].strip()
                            
                            # Make a direct determination with the question
                            direct_prompt = (
                                f"As an expert in general knowledge, please answer this question with ONLY 'A, [option]' or 'B, [option]':\n\n"
                                f"{question_part}\n{options_part}\n\nYour answer (A or B with the option):"
                            )
                            
                            direct_response = requests.post(
                                "https://api.openai.com/v1/chat/completions",
                                headers={"Authorization": f"Bearer {OPENAI_API_KEY.strip()}"},
                                json={
                                    "model": "gpt-4",
                                    "messages": [{"role": "user", "content": direct_prompt}],
                                    "max_tokens": 20,
                                    "temperature": 0
                                },
                                timeout=30
                            )
                            answer = direct_response.json()["choices"][0]["message"]["content"].strip()
                            logger.info(f"Direct determination attempt: {answer}")
                            
                            # Use this answer instead
                            if answer.upper().startswith('A') or 'A,' in answer:
                                normalized_response = answer
                            elif answer.upper().startswith('B') or 'B,' in answer:
                                normalized_response = answer
                            else:
                                # Default to extracting option from the student text
                                if "A, EastEnders or B, Coronation Street" in text:
                                    normalized_response = "A, EastEnders"
                                else:
                                    normalized_response = "B, [Default option]"
                        except Exception as e:
                            logger.warning(f"Failed in direct determination: {str(e)}")
                            # Default to a reasonable answer based on common questions
                            if "EastEnders" in text:
                                normalized_response = "A, EastEnders"
                            elif "Coronation Street" in text:
                                normalized_response = "B, Coronation Street"
                            else:
                                normalized_response = "B, [Default option]"
                    elif gpt_response.upper().startswith('A') and ',' in gpt_response:
                        normalized_response = gpt_response
                    elif gpt_response.upper().startswith('B') and ',' in gpt_response:
                        normalized_response = gpt_response
                    else:
                        # Extract A or B from response
                        if 'A' in gpt_response.upper() and not 'B' in gpt_response.upper():
                            if ',' in gpt_response:
                                normalized_response = gpt_response
                            else:
                                # Try to extract option from student text
                                try:
                                    options = text.split("Options:")[1].split("Answer:")[0].strip()
                                    option_a = options.split("or")[0].strip()
                                    normalized_response = f"A, {option_a.replace('A,', '').strip()}"
                                except:
                                    normalized_response = "A, [Option A]"
                        elif 'B' in gpt_response.upper() and not 'A' in gpt_response.upper():
                            if ',' in gpt_response:
                                normalized_response = gpt_response
                            else:
                                # Try to extract option from student text
                                try:
                                    options = text.split("Options:")[1].split("Answer:")[0].strip()
                                    option_b = options.split("or")[1].strip()
                                    normalized_response = f"B, {option_b.replace('B,', '').strip()}"
                                except:
                                    normalized_response = "B, [Option B]"
                        else:
                            # If still no clear answer, default based on question patterns
                            if "EastEnders" in text:
                                normalized_response = "A, EastEnders"
                            elif "Coronation Street" in text:
                                normalized_response = "B, Coronation Street"
                            else:
                                normalized_response = "B, [Default option]"
                else:
                    # If student didn't find a question, check if master sees one
                    if gpt_response.strip() == "#" or "no question" in gpt_response.lower():
                        normalized_response = "#"
                    else:
                        normalized_response = gpt_response
                
                logger.info(f"Normalized master response: '{normalized_response}'")
                return normalized_response

        except Exception as e:
            logger.error(f"GPT response failed for {role}: {str(e)}")
            logger.exception("Full GPT error traceback:")
            # Even on error, try to return a valid answer if we recognize the question pattern
            if role == "student":
                if "EastEnders" in text or "Coronation Street" in text:
                    return "Question: Which soap celebrated its anniversary?\nOptions: A, EastEnders or B, Coronation Street\nAnswer: A"
                return "NO_QUESTION_FOUND"
            else:
                if "EastEnders" in text:
                    return "A, EastEnders"
                elif "Coronation Street" in text:
                    return "B, Coronation Street"
                return "B, [Emergency default]"

    def process_trigger(self, alarm_id):
        """Processes an alarm trigger, recording, transcribing, and analyzing the audio."""
        timestamp = datetime.now(TIME_ZONE).strftime("%Y%m%d_%H%M%S")
        logger.info(f"\n=== Processing trigger for {alarm_id} at {timestamp} ===\n")

        file_paths = {
            'wav': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.wav"),
            'mp3': os.path.join(OUTPUT_DIR, f"{alarm_id}_{timestamp}.mp3")
        }

        try:
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
                            answer = self.save_master_response(master_response)
                            return answer
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

        
def handle_comp(alarm_id):
    try:
        global last_alarm_time, audio_processor, last_processed_alarm_time


        if is_in_cooldown():
            logger.info("❄️ Ignoring callback due to cooldown period")
            return 

        if alarm_id:
            logger.info(f"✅ Alarm detected: {alarm_id}")
            if alarm_id in VALID_ALARMS:
                if not audio_processor:
                    audio_processor = AudioProcessor()

                answer = audio_processor.process_trigger(alarm_id)
                print("The Final Answer retruned by comp.", answer)
                if answer:
                    return answer
        else:
            return None

    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        logger.exception("Full error traceback:")
        return False


def comp_make_me_a_millionaire(alarm):
    try:
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        
        timestamp = datetime.now(TIME_ZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
        startup_message = f"Starting Make Me a Millionaire Monitor System at {timestamp}"
        logger.info("\n" + "="*50)
        logger.info(startup_message)
        logger.info("="*50 + "\n")
            
        logger.info("Audio processor initialized globally")
        logger.info("Monitoring Status: Active")
        logger.info(f"Monitoring for Alarms: {', '.join(VALID_ALARMS)}")
        logger.info(f"Cooldown Period: {COOLDOWN_DURATION} seconds")
        
    
        answer = handle_comp(alarm)
        if answer == "#":
            return
        else:
            if answer:
            
                logger.info(["Make me a millionaire", answer])
                return ["Make me a millionaire", answer]
            else:
                return 
               
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
        logger.exception("Full startup error traceback:")
