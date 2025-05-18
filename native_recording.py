import asyncio
import threading
import pyaudio
import wave
import os
import re
import time
import yaml
from datetime import datetime
import pyttsx3
from tkinter import Tk, Button, Label, StringVar, Listbox, END

# Load CPR event phrases from YAML
with open('resuscitation_events.yaml', 'r') as f:
    event_map = yaml.safe_load(f)

cpr_start_phrases = [
    "chest compressions initiated",
    "i'm on compressions",
    "cpr started",
    "starting compressions",
    "begin cpr now",
    "compressions going",
    "starting cycles now"
]

# TTS engine
engine = pyttsx3.init()
def speak_text(text):
    engine.say(text)
    engine.runAndWait()

# Audio recording settings
FRAMES_PER_BUFFER = 3200
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
p = pyaudio.PyAudio()

RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# App state
recording = False
frames = []
events = []
timer_task = None
timer_running = False

def save_audio_file(audio_chunks, base_filename="recording"):
    wav_filename = os.path.join(RECORDINGS_DIR, f"{base_filename}.wav")
    with wave.open(wav_filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(audio_chunks))
    return wav_filename

def detect_cpr_phrase(text):
    text_lc = text.lower()
    for phrase in cpr_start_phrases:
        if phrase in text_lc:
            return phrase
    return None

def log_event(event, phrase, text):
    timestamp = datetime.now().strftime("%H:%M:%S")
    events.append({'timestamp': timestamp, 'event': event, 'phrase': phrase, 'text': text})
    event_listbox.insert(END, f"[{timestamp}] {event}: '{phrase}' in '{text}'")

def cpr_timer():
    global timer_running
    timer_running = True
    for remaining in range(120, 0, -1):
        mins, secs = divmod(remaining, 60)
        timer_var.set(f"CPR Timer: {mins:02d}:{secs:02d}")
        if remaining == 60:
            speak_text("It's been one minute, next pulse check in one minute.")
        time.sleep(1)
    timer_var.set("2 minutes up! Time for pulse check.")
    speak_text("2 minutes up! Time for pulse check.")
    timer_running = False

def start_cpr_timer():
    global timer_task
    if timer_running:
        return
    timer_task = threading.Thread(target=cpr_timer, daemon=True)
    timer_task.start()

def start_recording():
    global recording, frames
    if recording:
        return
    frames = []
    recording = True
    record_button.config(state='disabled')
    stop_button.config(state='normal')
    status_var.set("Recording...")
    threading.Thread(target=record_audio, daemon=True).start()

def stop_recording():
    global recording
    recording = False
    record_button.config(state='normal')
    stop_button.config(state='disabled')
    status_var.set("Stopped.")
    save_audio_file(frames)

def record_audio():
    global recording, frames
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=FRAMES_PER_BUFFER)
    while recording:
        data = stream.read(FRAMES_PER_BUFFER)
        frames.append(data)
        # Simulate real-time transcription (replace with actual ASR in production)
        # For demo, check for CPR phrase in random text every 5 seconds
        if len(frames) % (RATE // FRAMES_PER_BUFFER * 5) == 0:
            # Simulate a CPR phrase being spoken
            test_text = "CPR started"
            phrase = detect_cpr_phrase(test_text)
            if phrase:
                log_event('CPR_START', phrase, test_text)
                start_cpr_timer()
    stream.stop_stream()
    stream.close()

# GUI setup
root = Tk()
root.title("Code Blue Native Recorder")

status_var = StringVar(value="Idle.")
timer_var = StringVar(value="CPR Timer: --:--")

Label(root, textvariable=status_var, font=("Arial", 14)).pack(pady=5)
Label(root, textvariable=timer_var, font=("Arial", 16, "bold")).pack(pady=5)

record_button = Button(root, text="Start Recording", command=start_recording, width=20)
record_button.pack(pady=5)
stop_button = Button(root, text="Stop Recording", command=stop_recording, width=20, state='disabled')
stop_button.pack(pady=5)

Label(root, text="Detected Events:", font=("Arial", 12, "bold")).pack(pady=5)
event_listbox = Listbox(root, width=80, height=10)
event_listbox.pack(pady=5)

root.mainloop() 