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
import yaml
from gtts import gTTS
import io
from thefuzz import fuzz

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
	st.session_state.setdefault('detected_events', [])

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

# Load resuscitation event utterances from YAML
with open('resuscitation_events.yaml', 'r') as f:
	event_map = yaml.safe_load(f)
utterance_to_event = {}
for event, phrases in event_map.items():
	for phrase in phrases:
		utterance_to_event[phrase.lower()] = event

# Timer state
cpr_timer_task = None
cpr_timer_display = None

# List of CPR start phrases (lowercased for matching)
cpr_start_phrases = [
	"chest compressions initiated",
	"i'm on compressions",
	"initiating compressions",
	"cpr initiated",
    "starting cpr",
	"start cpr",
	"cpr started",
	"cpr start",
	"starting compressions",
	"begin cpr now",
	"compressions going",
	"starting cycles now"
]

FUZZY_THRESHOLD = 70  # Adjust as needed for sensitivity

def cancel_cpr_timer():
	global cpr_timer_task
	if cpr_timer_task and not cpr_timer_task.done():
		cpr_timer_task.cancel()
		cpr_timer_task = None
	# Clear the timer display
	if 'cpr_timer_display' in st.session_state:
		st.session_state['cpr_timer_display'].empty()
		del st.session_state['cpr_timer_display']

async def cpr_timer(triggered_by_phrase=None):
	with st.sidebar:
		if 'cpr_timer_display' not in st.session_state:
			st.session_state['cpr_timer_display'] = st.empty()
		timer_area = st.session_state['cpr_timer_display']
		# Show the trigger phrase if provided
		if triggered_by_phrase:
			st.markdown(f"**CPR Timer Triggered By:** '{triggered_by_phrase}'")
	total_seconds = 120
	for remaining in range(total_seconds, 0, -1):
		mins, secs = divmod(remaining, 60)
		timer_area.markdown(f"## ⏳ CPR Timer: {mins:02d}:{secs:02d}")
		if remaining == 110 and triggered_by_phrase:
			speak_text_streamlit("10 seconds until next pulse check.")
		await asyncio.sleep(1)
	timer_area.markdown("## ⏰ 2 minutes up! Time for pulse check.")
	del st.session_state['cpr_timer_display']

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

def speak_text_streamlit(text):
	tts = gTTS(text)
	fp = io.BytesIO()
	tts.write_to_fp(fp)
	fp.seek(0)
	st.audio(fp, format='audio/mp3')

st.title('Code Blue Co-Pilot')

# Configuration sidebar
# with st.sidebar:
# 	st.header("Configuration")
# 	num_speakers = st.slider("Expected Number of Speakers", 
# 							min_value=MIN_SPEAKERS, 
# 							max_value=MAX_SPEAKERS, 
# 							value=MIN_SPEAKERS,
# 							help="Select the number of distinct voices you expect in the recording")
# 	st.info(f"Currently configured to detect between {MIN_SPEAKERS} and {MAX_SPEAKERS} different speakers")

# Recording controls
col1, col2 = st.columns(2)
with col1:
	start_button = st.button('Start Recording', on_click=start_listening)
with col2:
	stop_button = st.button('Stop Recording', on_click=stop_listening)

# Display areas
transcript_header = st.empty()
transcript_area = st.empty()
speaker_info = st.empty()

# Updated URL with more specific diarization parameters
URL = (f"wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"
		f"&speaker_labels=true"
		f"&diarization=true"
		# f"&speakers_expected={num_speakers}"
		f"&diarization_min_speakers={MIN_SPEAKERS}"
		f"&diarization_max_speakers={MAX_SPEAKERS}"
		f"&speaker_threshold=0.2"
		f"&diarization_threshold=0.5")

headers = [
	("Authorization", auth_key)
]

async def send_receive():
	global cpr_timer_task
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
				global cpr_timer_task
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
							
							# Event detection logic
							detected = False
							for phrase, event in utterance_to_event.items():
								score = fuzz.partial_ratio(phrase.lower(), text.lower())
								if score >= FUZZY_THRESHOLD:
									st.session_state['detected_events'].append({
										'timestamp': datetime.now().strftime("%H:%M:%S"),
										'event': event,
										'phrase': phrase,
										'text': text
									})
									detected = True
									# CPR timer logic (fuzzy match for CPR_START)
									if event == 'CPR_START' and score >= FUZZY_THRESHOLD:
										print(f"CPR timer triggered by: {text}")
										cancel_cpr_timer()
										st.session_state['last_cpr_trigger_phrase'] = text
										cpr_timer_task = asyncio.create_task(cpr_timer(triggered_by_phrase=text.lower()))

							# Create message with confidence score
							message = {
								'timestamp': datetime.now().strftime("%H:%M:%S"),
								'speaker': speaker_name,
								'text': text,
								'confidence': confidence
							}
							st.session_state['text'].append(message)
							
							# Update displays with confidence scores
							transcript_header.markdown('### Live Transcript')
							messages_display = ""
							for msg in st.session_state['text'][-10:]:  # Show last 10 messages
								messages_display += f"<div style='font-size:1.5em;'>[{msg['timestamp']}]: {msg['text']}</div>\n"
							transcript_area.markdown(messages_display, unsafe_allow_html=True)

					except Exception as e:
						print(f"Error in receive: {e}")
						break

			await asyncio.gather(send(), receive())
	except Exception as e:
		print(f"Connection error: {e}")
		st.error(f"Connection error: {e}")

if st.session_state['run']:
	asyncio.run(send_receive())

# Move Detected Resuscitation Events to the sidebar (always active, real-time)
with st.sidebar:
	# Detected Resuscitation Events first
	if st.session_state['detected_events']:
		st.markdown('---\n### Detected Resuscitation Events')
		for evt in st.session_state['detected_events']:
			st.markdown(f"[{evt['timestamp']}] **{evt['event']}**: '{evt['phrase']}' in '{evt['text']}'")
	# CPR Timer (trigger phrase and timer display)
	if 'cpr_timer_display' in st.session_state:
		# Show the trigger phrase if provided (store in session state if needed)
		if st.session_state.get('last_cpr_trigger_phrase'):
			st.markdown(f"**CPR Timer Triggered By:** '{st.session_state['last_cpr_trigger_phrase']}'")
	# Play Trigger Phrase button
	if st.session_state.get('last_cpr_trigger_phrase'):
		if st.button("🔊 Play Trigger Phrase"):
			speak_text_streamlit(st.session_state['last_cpr_trigger_phrase'])

# # Add a button to test the 1-minute announcement
# if st.button("Test Announcement"):
# 	speak_text_streamlit("It's been one minute, next pulse check in one minute")