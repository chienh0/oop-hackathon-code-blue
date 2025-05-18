import streamlit as st
import pyaudio
import wave
import os
import time
import json
from datetime import datetime
import assemblyai as aai

# Configure AssemblyAI
# Replace with your actual API key or use your configure.py
AUDIO_API_KEY = "YOUR_ASSEMBLYAI_API_KEY"
aai.settings.api_key = AUDIO_API_KEY

RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
BATCH_DURATION = 3  # seconds

if 'recording' not in st.session_state:
    st.session_state.recording = False
    st.session_state.transcripts = []
    st.session_state.speaker_map = {}

def record_batch(batch_num):
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    for _ in range(int(RATE / CHUNK * BATCH_DURATION)):
        if not st.session_state.recording:
            break
        data = stream.read(CHUNK)
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()
    filename = os.path.join(RECORDINGS_DIR, f"batch_{batch_num}_{int(time.time())}.wav")
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
    return filename

def process_batch(audio_file, batch_num):
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        diarization=True,
        speakers_expected=5,  # or your expected number
        min_speakers=5,
        max_speakers=9
    )
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_file, config=config)
    messages = []
    for utterance in transcript.utterances:
        speaker = f"Speaker {utterance.speaker}"
        messages.append({
            "batch": batch_num,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "speaker": speaker,
            "text": utterance.text
        })
    return messages

def start_microbatch():
    st.session_state.recording = True
    st.session_state.transcripts = []
    batch_num = 1
    while st.session_state.recording:
        st.info(f"Recording batch {batch_num}...")
        audio_file = record_batch(batch_num)
        st.info(f"Processing batch {batch_num}...")
        messages = process_batch(audio_file, batch_num)
        st.session_state.transcripts.extend(messages)
        os.remove(audio_file)
        batch_num += 1

def stop_microbatch():
    st.session_state.recording = False

st.title("Micro-Batch Speaker Diarization (3s Batches)")

col1, col2 = st.columns(2)
with col1:
    if not st.session_state.recording:
        st.button("Start Microbatch Recording", on_click=start_microbatch)
with col2:
    if st.session_state.recording:
        st.button("Stop", on_click=stop_microbatch)

if st.session_state.transcripts:
    st.subheader("Transcript")
    for msg in st.session_state.transcripts:
        st.markdown(f"[Batch {msg['batch']}] **{msg['speaker']}**: {msg['text']}") 