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

def process_with_speaker_diarization(audio_file):
	try:
		# Configure transcription with speaker diarization
		config = aai.TranscriptionConfig(speaker_labels=True)
		
		# Create transcriber and transcribe the audio file
		transcriber = aai.Transcriber()
		transcript = transcriber.transcribe(
			audio_file,
			config=config
		)

		# Process and display utterances with speaker labels
		messages = []
		for utterance in transcript.utterances:
			message = {
				'timestamp': datetime.now().strftime("%H:%M:%S"),
				'speaker': f"Speaker {utterance.speaker}",
				'text': utterance.text
			}
			messages.append(message)
		
		return messages
	except Exception as e:
		st.error(f"Error in speaker diarization: {e}")
		return []

def start_listening():
	st.session_state['text'] = []
	st.session_state['audio_chunks'] = []
	st.session_state['run'] = True
	st.session_state['speakers'] = {}

def stop_listening():
	st.session_state['run'] = False
	if st.session_state['audio_chunks']:
		with st.spinner('Processing audio for speaker identification...'):
			# Save audio to file
			audio_file = save_audio_file(st.session_state['audio_chunks'])
			# Process with speaker diarization
			messages = process_with_speaker_diarization(audio_file)
			# Update transcript with speaker information
			st.session_state['text'].extend(messages)
			# Clean up temporary file
			os.remove(audio_file)

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

# Updated URL with real-time speaker diarization
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
			print("Connected to AssemblyAI websocket with speaker detection")

			async def send():
				while st.session_state['run']:
					try:
						data = stream.read(FRAMES_PER_BUFFER)
						# Store audio chunk for later processing
						st.session_state['audio_chunks'].append(data)
						# Send for real-time transcription
						data_b64 = base64.b64encode(data).decode("utf-8")
						json_data = json.dumps({"audio_data": str(data_b64)})
						await _ws.send(json_data)
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
							speaker_id = result.get('speaker', 'Unknown')
							text = result.get('text', '').strip()

							# Try to detect name if not already known
							if speaker_id not in st.session_state['voice_names']:
								detected_name = detect_name_from_text(text, speaker_id)
								if detected_name:
									current_letter = st.session_state['speaker_letters'].get(speaker_id, '?')
									st.info(f"Person {current_letter} identified as {detected_name}")
								
							# Get or assign letter if needed
							if speaker_id not in st.session_state['speaker_letters']:
								st.session_state['speaker_letters'][speaker_id] = get_next_letter()

							# Get current speaker name or letter designation
							speaker_name = get_speaker_name(speaker_id)
							
							# Update speaker statistics
							if speaker_id not in st.session_state['speakers']:
								st.session_state['speakers'][speaker_id] = 0
							st.session_state['speakers'][speaker_id] += len(text.split())
							
							# Create message
							message = {
								'timestamp': datetime.now().strftime("%H:%M:%S"),
								'speaker': speaker_name,
								'text': text
							}
							st.session_state['text'].append(message)
							
							# Update displays
							messages_display = ""
							for msg in st.session_state['text'][-10:]:  # Show last 10 messages
								messages_display += f"[{msg['timestamp']}] **{msg['speaker']}:** {msg['text']}\n\n"
							transcript_area.markdown(messages_display)
							
							# Show identified speakers
							info_text = "### Speakers in Conversation\n"
							for spk_id, words in st.session_state['speakers'].items():
								name = get_speaker_name(spk_id)
								info_text += f"{name}: {words} words spoken\n"
							speaker_info.markdown(info_text)

					except Exception as e:
						print(f"Error in receive: {e}")
						break

			await asyncio.gather(send(), receive())
	except Exception as e:
		print(f"Connection error: {e}")
		st.error(f"Connection error: {e}")

if st.session_state['run']:
	asyncio.run(send_receive())
