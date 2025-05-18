# Code Blue: Real-time Voice Recognition with Speaker Detection

This application provides real-time speech transcription with speaker diarization using AssemblyAI's API. The app can identify different speakers, detect speaker names from introductions, and save recordings for later use.

## Features

- Real-time speech-to-text transcription
- Speaker diarization (differentiating between speakers)
- Automatic speaker name detection from introductions
- Recording storage in M4A format
- Word count tracking per speaker
- Interactive Streamlit interface

## Setup

1. Get your AssemblyAI API token for free at [assemblyai.com](https://www.assemblyai.com)
2. Create a `configure.py` file with your API key:
   ```python
   auth_key = "your-api-key-here"
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Dependencies
* streamlit
* pyaudio
* websockets
* assemblyai
* pydub

## Usage

1. Run the Streamlit app:
   ```bash
   streamlit run live_recording.py
   ```

2. Use the interface to:
   - Click "Start Recording" to begin transcription
   - Speak naturally - the app will automatically detect different speakers
   - Introduce yourself with phrases like "My name is [Name]" for automatic name detection
   - Click "Stop Recording" to end the session

3. Recordings are automatically saved in the `recordings` folder with timestamp-based names:
   - Format: `recording_YYYYMMDD_HHMMSS.m4a`
   - Example: `recording_20240315_143045.m4a`

## Features in Detail

### Speaker Detection
- Automatically assigns letters (A, B, C, etc.) to different speakers
- Updates to real names when speakers introduce themselves
- Tracks word count per speaker

### Recording Management
- Saves high-quality M4A audio files
- Organizes recordings in a dedicated 'recordings' directory
- Timestamps each recording for easy reference

### Real-time Display
- Shows last 10 messages in conversation
- Displays speaker statistics
- Provides immediate feedback on speaker identification
