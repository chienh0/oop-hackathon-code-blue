import streamlit as st
import websockets
import asyncio
import base64
import json
from configure import auth_key
import pyaudio
from datetime import datetime
import wave
import assemblyai as aai
import os
import re
import time

# Configure AssemblyAI
aai.settings.api_key = auth_key

# Initialize session state
if 'text' not in st.session_state:
	st.session_state['text'] = []
	st.session_state['run'] = False
	st.session_state['audio_chunks'] = []
	st.session_state['speakers'] = {}  # Track different speakers
	st.session_state['voice_names'] = {}  # Map speaker IDs to detected names
	st.session_state['speaker_letters'] = {}  # Map speaker IDs to letters (A, B, C)
	st.session_state['next_letter'] = 0  # Track next available letter
	st.session_state['speaker_analytics'] = {}  # Store speaker analytics
	st.session_state['last_batch_process'] = 0  # Track last batch process time
	st.session_state['temp_messages'] = []  # Store messages before speaker identification

FRAMES_PER_BUFFER = 3200
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
p = pyaudio.PyAudio()

# starts recording
stream = p.open(
	format=FORMAT,
	channels=CHANNELS,
	rate=RATE,
	input=True,
	frames_per_buffer=FRAMES_PER_BUFFER
)

def save_audio_file(audio_chunks, filename="temp_recording.wav"):
	# Save audio chunks to WAV file
	with wave.open(filename, 'wb') as wf:
		wf.setnchannels(CHANNELS)
		wf.setsampwidth(p.get_sample_size(FORMAT))
		wf.setframerate(RATE)
		wf.writeframes(b''.join(audio_chunks))
	return filename

def process_audio_batch():
	"""Process accumulated audio for speaker identification"""
	if not st.session_state['audio_chunks']:
		return
		
	try:
		# Save current audio to temporary file
		audio_file = save_audio_file(st.session_state['audio_chunks'], "temp_batch.wav")
		
		# Configure transcription with advanced speaker diarization
		config = aai.TranscriptionConfig(
			speaker_labels=True,
			diarization={
				"enable": True,
				"speaker_count": None,  # Let the model automatically determine speaker count
				"min_speaker_count": 2,  # At least expect 2 speakers
				"max_speaker_count": 10  # But no more than 10 speakers
			},
			punctuate=True,  # Add punctuation
			format_text=True  # Apply text formatting
		)
		
		# Create transcriber and transcribe the audio file
		transcriber = aai.Transcriber()
		transcript = transcriber.transcribe(
			audio_file,
			config=config
		)

		if transcript and hasattr(transcript, 'utterances'):
			# Clear previous speaker mappings
			st.session_state['speaker_letters'].clear()
			st.session_state['speakers'].clear()
			
			# Process utterances
			messages = []
			speakers_data = {}
			
			for utterance in transcript.utterances:
				if not hasattr(utterance, 'speaker') or not hasattr(utterance, 'text'):
					continue
					
				speaker_id = utterance.speaker
				
				# Track speaker timing data
				if speaker_id not in speakers_data:
					speakers_data[speaker_id] = {
						"total_duration": 0,
						"turns": 0,
						"first_seen_at": utterance.start
					}
				
				# Update speaker stats
				speakers_data[speaker_id]["total_duration"] += (utterance.end - utterance.start)
				speakers_data[speaker_id]["turns"] += 1
				
				# Get or assign letter
				if speaker_id not in st.session_state['speaker_letters']:
					st.session_state['speaker_letters'][speaker_id] = get_next_letter()
				
				speaker_name = get_speaker_name(speaker_id)
				
				# Create message
				message = {
					'timestamp': datetime.fromtimestamp(utterance.start/1000.0).strftime("%H:%M:%S"),
					'speaker': speaker_name,
					'text': utterance.text,
					'start_time': utterance.start,
					'end_time': utterance.end,
					'confidence': getattr(utterance, 'confidence', None)
				}
				messages.append(message)
			
			# Sort messages by start time
			messages.sort(key=lambda x: x['start_time'])
			
			# Update session state
			st.session_state['text'] = messages
			st.session_state['speaker_analytics'] = speakers_data
			
			# Display analytics
			display_speaker_analytics()
			
		# Clean up
		os.remove(audio_file)
		
	except Exception as e:
		print(f"Error in batch processing: {e}")

def start_listening():
	st.session_state['text'] = []
	st.session_state['audio_chunks'] = []
	st.session_state['run'] = True
	st.session_state['speakers'] = {}

def stop_listening():
	st.session_state['run'] = False
	if st.session_state['audio_chunks']:
		with st.spinner('Processing final audio for speaker identification...'):
			process_audio_batch()

def get_next_letter():
	"""Get next available letter (A, B, C, etc.)"""
	letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
	letter_idx = st.session_state['next_letter'] % len(letters)
	st.session_state['next_letter'] += 1
	return letters[letter_idx]

def detect_name_from_text(text, speaker_id):
	"""Detect if speaker is introducing themselves"""
	patterns = [
		# More specific patterns to avoid false positives
		r"(?i)(?:my name is|i am|i'm|this is) (?:dr\.|doctor |nurse |tech )?([A-Z][a-z]{1,20}(?: [A-Z][a-z]{1,20})?)",
		r"(?i)^(?:dr\.|doctor |nurse |tech )([A-Z][a-z]{1,20}(?: [A-Z][a-z]{1,20})?)",
	]
	
	for pattern in patterns:
		match = re.search(pattern, text)
		if match:
			name = match.group(1).strip()
			# Validate the name - must be 2-30 chars, start with capital, no numbers
			if (len(name) >= 2 and len(name) <= 30 and 
				name[0].isupper() and 
				not any(c.isdigit() for c in name) and
				not name.lower().startswith('testing')):  # Prevent "testing" false positive
				st.session_state['voice_names'][speaker_id] = name
				return name
	return None

def get_speaker_name(speaker_id):
	"""Get speaker name from voice mapping or return Person A/B/C"""
	if speaker_id in st.session_state['voice_names']:
		return st.session_state['voice_names'][speaker_id]
	
	# Assign letter if not already assigned
	if speaker_id not in st.session_state['speaker_letters']:
		st.session_state['speaker_letters'][speaker_id] = get_next_letter()
	
	return f"Person {st.session_state['speaker_letters'][speaker_id]}"

def display_speaker_analytics():
	"""Display detailed analytics about speakers"""
	if 'speaker_analytics' not in st.session_state:
		return
	
	analytics = st.session_state['speaker_analytics']
	
	st.subheader("Speaker Analytics")
	
	# Create speaker data for visualization
	speaker_data = []
	for speaker_id, data in analytics.items():
		name = get_speaker_name(speaker_id)
		speaker_data.append({
			"name": name,
			"talk_time": round(data["total_duration"] / 1000, 1),  # Convert to seconds
			"turns": data["turns"],
			"avg_turn": round((data["total_duration"] / data["turns"]) / 1000, 1) if data["turns"] > 0 else 0
		})
	
	# Display as table
	st.table(speaker_data)

st.title('Real-time Voice Recognition')

# Recording controls
col1, col2 = st.columns(2)
with col1:
	start_button = st.button('Start Recording', on_click=start_listening)
with col2:
	stop_button = st.button('Stop Recording', on_click=stop_listening)

# Display areas
transcript_area = st.empty()
speaker_info = st.empty()

# Updated URL with enhanced real-time speaker diarization parameters
URL = "wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000&speaker_labels=true"

headers = [
	("Authorization", auth_key)
]

async def send_receive():
	try:
		async with websockets.connect(
			URL,
			ping_interval=5,
			ping_timeout=20,
			extra_headers=headers
		) as _ws:
			await asyncio.sleep(0.1)
			print("Connected to AssemblyAI websocket")

			async def send():
				buffer = []  # Buffer to accumulate audio data
				buffer_duration = 0  # Track duration of buffered audio in seconds
				last_process_time = time.time()
				
				while st.session_state['run']:
					try:
						data = stream.read(FRAMES_PER_BUFFER)
						# Store audio chunk for later processing
						st.session_state['audio_chunks'].append(data)
						
						# Add to buffer
						buffer.append(data)
						buffer_duration += FRAMES_PER_BUFFER / RATE
						
						# Send when we have enough data (about 1 second)
						if buffer_duration >= 1.0:
							# Combine buffer and convert to base64
							audio_data = b''.join(buffer)
							data_b64 = base64.b64encode(audio_data).decode("utf-8")
							
							# Send for real-time transcription
							json_data = json.dumps({"audio_data": str(data_b64)})
							await _ws.send(json_data)
							
							# Clear buffer
							buffer = []
							buffer_duration = 0
						
						# Process batch every 10 seconds
						current_time = time.time()
						if current_time - last_process_time >= 10:
							process_audio_batch()
							last_process_time = current_time
							
					except Exception as e:
						print(f"Error in send: {e}")
						break
					await asyncio.sleep(0.01)

			async def receive():
				while st.session_state['run']:
					try:
						result_str = await _ws.recv()
						result = json.loads(result_str)

						if result.get('message_type') == 'FinalTranscript':
							text = result.get('text', '').strip()
							current_time = datetime.now()

							# Only process if we have actual text
							if text:
								# Create temporary message
								message = {
									'timestamp': current_time.strftime("%H:%M:%S"),
									'speaker': "Processing...",
									'text': text,
									'confidence': result.get('confidence', None)
								}
								st.session_state['temp_messages'].append(message)
								
								# Update display with all messages
								messages_display = ""
								for msg in st.session_state['text'] + st.session_state['temp_messages'][-10:]:
									confidence_str = f" (confidence: {msg.get('confidence', 'N/A')}%)" if msg.get('confidence') else ""
									messages_display += f"[{msg['timestamp']}] **{msg['speaker']}:**{confidence_str} {msg['text']}\n\n"
								transcript_area.markdown(messages_display)

					except Exception as e:
						print(f"Error in receive: {e}")
						break

			await asyncio.gather(send(), receive())
	except Exception as e:
		print(f"Connection error: {e}")
		st.error(f"Connection error: {e}")

if st.session_state['run']:
	asyncio.run(send_receive())
