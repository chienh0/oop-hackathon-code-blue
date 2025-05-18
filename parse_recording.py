import assemblyai as aai
import os
import json
from datetime import datetime
from configure import auth_key

# Configure AssemblyAI
aai.settings.api_key = auth_key

# File paths
RECORDINGS_DIR = "recordings"
AUDIO_FILE = os.path.join(RECORDINGS_DIR, "code_blue_recording.mp3")
TRANSCRIPT_FILE = os.path.join(RECORDINGS_DIR, "code_blue_recording_transcript.json")

def process_with_speaker_diarization(audio_file):
    try:
        config = aai.TranscriptionConfig(
            speaker_labels=True,
        )
        print(f"Processing {audio_file} with diarization config: {config}")
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_file, config=config)
        messages = []
        speaker_stats = {}
        for utterance in transcript.utterances:
            speaker = utterance.speaker
            text = utterance.text
            confidence = utterance.confidence
            timestamp = datetime.now().strftime("%H:%M:%S")
            messages.append({
                'timestamp': timestamp,
                'speaker': f"Speaker {speaker}",
                'text': text,
                'confidence': confidence
            })
            if speaker not in speaker_stats:
                speaker_stats[speaker] = 0
            speaker_stats[speaker] += len(text.split())
        return messages, speaker_stats
    except Exception as e:
        print(f"Diarization Error: {str(e)}")
        return [], {}

def save_transcript(filename, messages, speaker_stats):
    transcript_data = {
        'messages': messages,
        'speaker_statistics': speaker_stats,
        'recording_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(filename, 'w') as f:
        json.dump(transcript_data, f, indent=2)
    print(f"Transcript saved as {filename}")

def main():
    if not os.path.exists(AUDIO_FILE):
        print(f"Audio file not found: {AUDIO_FILE}")
        return
    messages, speaker_stats = process_with_speaker_diarization(AUDIO_FILE)
    save_transcript(TRANSCRIPT_FILE, messages, speaker_stats)

if __name__ == "__main__":
    main()