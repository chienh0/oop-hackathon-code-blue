import streamlit as st
import websockets
import asyncio
import base64
import json
from configure import auth_key
import pyaudio

# Initialize session state
if 'text' not in st.session_state:
	st.session_state['text'] = 'Listening...'
	st.session_state['run'] = False
	st.session_state['loop_started'] = False

FRAMES_PER_BUFFER = 3200
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
p = pyaudio.PyAudio()

stream = p.open(
	format=FORMAT,
	channels=CHANNELS,
	rate=RATE,
	input=True,
	frames_per_buffer=FRAMES_PER_BUFFER
)

def start_listening():
	st.session_state['run'] = True

def stop_listening():
	st.session_state['run'] = False

st.title('Get real-time transcription')
start, stop = st.columns(2)
start.button('Start listening', on_click=start_listening)
stop.button('Stop listening', on_click=stop_listening)

URL = "wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"

async def send_receive():
	async with websockets.connect(
		URL,
		extra_headers={"Authorization": auth_key},
		ping_interval=5,
		ping_timeout=20
	) as _ws:

		await asyncio.sleep(0.1)
		print("Receiving SessionBegins ...")
		session_begins = await _ws.recv()
		print(session_begins)

		async def send():
			while st.session_state['run']:
				try:
					data = stream.read(FRAMES_PER_BUFFER)
					data = base64.b64encode(data).decode("utf-8")
					json_data = json.dumps({"audio_data": str(data)})
					await _ws.send(json_data)
				except Exception as e:
					print("Send error:", e)
					break
				await asyncio.sleep(0.01)

		async def receive():
			while st.session_state['run']:
				try:
					result_str = await _ws.recv()
					data = json.loads(result_str)
					if data.get("message_type") == "FinalTranscript":
						st.session_state['text'] = data['text']
				except Exception as e:
					print("Receive error:", e)
					break

		await asyncio.gather(send(), receive())

# Render current transcript
st.markdown(f"**Transcript:** {st.session_state['text']}")

# Launch websocket loop when 'run' is True and not already started
if st.session_state['run'] and not st.session_state['loop_started']:
	st.session_state['loop_started'] = True
	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)

	loop.create_task(send_receive())

