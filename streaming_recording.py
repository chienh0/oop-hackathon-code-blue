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
from pydub import AudioSegment
import time

# Configure AssemblyAI
aai.settings.api_key = auth_key

# Configure recordings directory
RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Configure speaker settings
MIN_SPEAKERS = 5  # Minimum number of speakers to detect
MAX_SPEAKERS = 9  # Maximum number of speakers to detect

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

def save_audio_file(audio_chunks, base_filename="recording"):
	# Save audio chunks to WAV file first
	wav_filename = os.path.join(RECORDINGS_DIR, f"{base_filename}.wav")
	m4a_filename = os.path.join(RECORDINGS_DIR, f"{base_filename}.m4a")
	transcript_filename = os.path.join(RECORDINGS_DIR, f"{base_filename}_transcript.json")
	
	with wave.open(wav_filename, 'wb') as wf:
		wf.setnchannels(CHANNELS)
		wf.setsampwidth(p.get_sample_size(FORMAT))
		wf.setframerate(RATE)
		wf.writeframes(b''.join(audio_chunks))
	
	# Convert to M4A using pydub
	audio = AudioSegment.from_wav(wav_filename)
	audio.export(m4a_filename, format="ipod")  # ipod format = M4A
	
	# Return all filenames
	return wav_filename, m4a_filename, transcript_filename


def start_listening():
	st.session_state['text'] = []
	st.session_state['audio_chunks'] = []
	st.session_state['run'] = True
	st.session_state['speakers'] = {}

def save_transcript(filename, messages, speaker_stats):
	"""Save transcript with speaker information to JSON file"""
	transcript_data = {
		'messages': messages,
		'speaker_statistics': speaker_stats,
		'speaker_names': st.session_state['voice_names'],
		'recording_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	}
	
	with open(filename, 'w') as f:
		json.dump(transcript_data, f, indent=2)

def stop_listening():
	st.session_state['run'] = False
	if st.session_state['audio_chunks']:
		with st.spinner('Processing audio for speaker identification...'):
			# Save audio to files
			timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
			base_filename = f"recording_{timestamp}"
			wav_file, m4a_file, transcript_file = save_audio_file(st.session_state['audio_chunks'], base_filename)
			# Save transcript to JSON file
			save_transcript(transcript_file, st.session_state['text'], st.session_state['speakers'])
			
			# Clean up WAV file but keep M4A and transcript
			os.remove(wav_file)
			st.success(f"Recording saved as {m4a_file}\nTranscript saved as {transcript_file}")

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

st.title('Code Blue')

# Configuration sidebar
with st.sidebar:
	st.header("Configuration")
	num_speakers = st.slider("Expected Number of Speakers", 
							min_value=MIN_SPEAKERS, 
							max_value=MAX_SPEAKERS, 
							value=MIN_SPEAKERS,
							help="Select the number of distinct voices you expect in the recording")
	st.info(f"Currently configured to detect between {MIN_SPEAKERS} and {MAX_SPEAKERS} different speakers")

# Recording controls
col1, col2 = st.columns(2)
with col1:
	start_button = st.button('Start Recording', on_click=start_listening)
with col2:
	stop_button = st.button('Stop Recording', on_click=stop_listening)

# Display areas
transcript_area = st.empty()
speaker_info = st.empty()

# Updated URL with more specific diarization parameters
URL = (f"wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"
		f"&speaker_labels=true"
		f"&diarization=true"
		f"&speakers_expected={num_speakers}"
		f"&diarization_min_speakers={MIN_SPEAKERS}"
		f"&diarization_max_speakers={MAX_SPEAKERS}"
		f"&speaker_threshold=0.2"
		f"&diarization_threshold=0.5")

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
				current_speaker = None
				speaker_change_threshold = 0.2  # More sensitive threshold for speaker changes
				min_segment_duration = 1.0  # Minimum duration (seconds) before allowing speaker change
				last_change_time = time.time()
				
				while st.session_state['run']:
					try:
						result_str = await _ws.recv()
						result = json.loads(result_str)

						if result.get('message_type') == 'FinalTranscript':
							text = result.get('text', '').strip()
							speaker_id = result.get('speaker_id') or result.get('speaker') or 'Unknown'
							confidence = result.get('confidence', 0)
							current_time = time.time()
							
							# Enhanced speaker change logic
							time_since_last_change = current_time - last_change_time
							should_change_speaker = (
								confidence > speaker_change_threshold and
								time_since_last_change >= min_segment_duration and
								speaker_id != current_speaker
							)
							
							if should_change_speaker:
								print(f"Speaker change: {current_speaker} -> {speaker_id} "
										f"(conf: {confidence}, time: {time_since_last_change:.1f}s)")
								current_speaker = speaker_id
								last_change_time = current_time
							elif current_speaker is None:
								current_speaker = speaker_id
								last_change_time = current_time
							
							# Use the determined speaker
							effective_speaker = current_speaker or speaker_id

							# Try to detect name if not already known
							if effective_speaker not in st.session_state['voice_names']:
								detected_name = detect_name_from_text(text, effective_speaker)
								if detected_name:
									current_letter = st.session_state['speaker_letters'].get(effective_speaker, '?')
									st.info(f"Person {current_letter} identified as {detected_name}")
								
							# Get or assign letter if needed
							if effective_speaker not in st.session_state['speaker_letters']:
								st.session_state['speaker_letters'][effective_speaker] = get_next_letter()

							# Get current speaker name or letter designation
							speaker_name = get_speaker_name(effective_speaker)
							
							# Update speaker statistics
							if effective_speaker not in st.session_state['speakers']:
								st.session_state['speakers'][effective_speaker] = 0
							st.session_state['speakers'][effective_speaker] += len(text.split())
							
							# Create message with confidence score
							message = {
								'timestamp': datetime.now().strftime("%H:%M:%S"),
								'speaker': speaker_name,
								'text': text,
								'confidence': confidence
							}
							st.session_state['text'].append(message)
							
							# Update displays with confidence scores
							messages_display = ""
							for msg in st.session_state['text'][-10:]:  # Show last 10 messages
								conf_str = f" (Confidence: {msg.get('confidence', 0):.2f})" if msg.get('confidence') else ""
								messages_display += f"[{msg['timestamp']}] **{msg['speaker']}**{conf_str}: {msg['text']}\n\n"
							transcript_area.markdown(messages_display)
							
							# Show identified speakers with more details
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
