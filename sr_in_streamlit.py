import streamlit as st
import websockets
import asyncio
import base64
import json
import assemblyai as aai
from configure import auth_key
import pyaudio
from datetime import datetime

# Configure AssemblyAI
aai.settings.api_key = auth_key

# Initialize session state
if 'text' not in st.session_state:
	st.session_state['text'] = []  # List to store messages with speaker labels
	st.session_state['run'] = False
	st.session_state['audio_chunks'] = []  # Store audio chunks for processing

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

def start_listening():
	st.session_state['text'] = []
	st.session_state['audio_chunks'] = []
	st.session_state['run'] = True

def stop_listening():
	st.session_state['run'] = False
	# Process accumulated audio with speaker diarization
	if st.session_state['audio_chunks']:
		process_audio_with_speakers()

def process_audio_with_speakers():
	# Convert audio chunks to bytes
	audio_data = b''.join(st.session_state['audio_chunks'])
	
	# Configure transcription with speaker diarization
	config = aai.TranscriptionConfig(speaker_labels=True)
	
	# Create transcriber
	transcriber = aai.Transcriber()
	
	try:
		# Transcribe the audio with speaker identification
		transcript = transcriber.transcribe(
			audio_data,
			config=config
		)
		
		# Process utterances with speaker labels
		for utterance in transcript.utterances:
			message = {
				'timestamp': datetime.now().strftime("%H:%M:%S"),
				'speaker': f"Speaker {utterance.speaker}",
				'text': utterance.text
			}
			st.session_state['text'].append(message)
			
	except Exception as e:
		st.error(f"Error in transcription: {e}")

st.title('Transcription with Speaker Detection')

start, stop = st.columns(2)
start.button('Start listening', on_click=start_listening)
stop.button('Stop listening', on_click=stop_listening)

# Display area for transcriptions
transcript_area = st.empty()

URL = "wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"

async def send_receive():
	try:

		# Create a dictionary for headers
		headers = [
			("Authorization", auth_key)
		]

		async with websockets.connect(
			URL,
			ping_interval=5,
			ping_timeout=20,
			extra_headers=headers  # Pass headers as a list of tuples
		) as _ws:
			await asyncio.sleep(0.1)
			print("Connected to AssemblyAI websocket")

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
							# Display real-time transcription while recording
							message = {
								'timestamp': datetime.now().strftime("%H:%M:%S"),
								'speaker': 'Recording...',
								'text': result['text']
							}
							st.session_state['text'].append(message)
							
							# Update display
							messages_display = ""
							for msg in st.session_state['text']:
								messages_display += f"[{msg['timestamp']}] **{msg['speaker']}:** {msg['text']}\n\n"
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
