import streamlit as st
import pyaudio
import wave
import os
import asyncio
import websockets
import base64
import json
import assemblyai as aai
from configure import auth_key
from datetime import datetime

# AssemblyAI config
aai.settings.api_key = auth_key
WS_URL = f"wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"
HEADERS = [("Authorization", auth_key)]

RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

FRAMES_PER_BUFFER = 3200
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

if 'recording' not in st.session_state:
    st.session_state.recording = False
    st.session_state.audio_buffer = []
    st.session_state.sentence_chunks = []
    st.session_state.current_transcript = ""

def save_audio_chunk(audio_frames, chunk_num):
    filename = os.path.join(RECORDINGS_DIR, f"sentence_chunk_{chunk_num}_{int(datetime.now().timestamp())}.wav")
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pyaudio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(audio_frames))
    return filename

async def transcribe_and_chunk():
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=FRAMES_PER_BUFFER)
    st.session_state.audio_buffer = []
    st.session_state.sentence_chunks = []
    st.session_state.current_transcript = ""
    chunk_num = 1

    async with websockets.connect(
        WS_URL,
        ping_interval=5,
        ping_timeout=20,
        extra_headers=HEADERS
    ) as ws:
        async def send_audio():
            while st.session_state.recording:
                data = stream.read(FRAMES_PER_BUFFER)
                st.session_state.audio_buffer.append(data)
                data_b64 = base64.b64encode(data).decode("utf-8")
                await ws.send(json.dumps({"audio_data": data_b64}))
                await asyncio.sleep(0.01)

        async def receive_transcript():
            nonlocal chunk_num
            sentence_endings = (".", "?", "!")
            while st.session_state.recording:
                try:
                    result_str = await ws.recv()
                    result = json.loads(result_str)
                    if result.get('message_type') == 'FinalTranscript':
                        text = result.get('text', '').strip()
                        st.session_state.current_transcript += (" " if st.session_state.current_transcript else "") + text
                        # Check for sentence ending
                        if text and text[-1] in sentence_endings:
                            # Save audio chunk and transcript
                            filename = save_audio_chunk(st.session_state.audio_buffer, chunk_num)
                            st.session_state.sentence_chunks.append({
                                "audio_file": filename,
                                "transcript": st.session_state.current_transcript.strip()
                            })
                            st.session_state.audio_buffer = []
                            st.session_state.current_transcript = ""
                            st.info(f"Saved chunk {chunk_num}: {filename}")
                            chunk_num += 1
                except Exception as e:
                    print(f"Error in receive: {e}")
                    break

        await asyncio.gather(send_audio(), receive_transcript())
    stream.stop_stream()
    stream.close()
    p.terminate()

def start_sentence_chunking():
    st.session_state.recording = True
    asyncio.run(transcribe_and_chunk())

def stop_sentence_chunking():
    st.session_state.recording = False

st.title("Audio Chunking by Sentence End")

col1, col2 = st.columns(2)
with col1:
    if not st.session_state.recording:
        st.button("Start Sentence Chunking", on_click=start_sentence_chunking)
with col2:
    if st.session_state.recording:
        st.button("Stop", on_click=stop_sentence_chunking)

if st.session_state.sentence_chunks:
    st.subheader("Sentence Chunks")
    for i, chunk in enumerate(st.session_state.sentence_chunks, 1):
        st.write(f"Chunk {i}: {chunk['audio_file']}")
        st.write(f"Transcript: {chunk['transcript']}") 