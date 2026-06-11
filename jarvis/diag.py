"""Voice pipeline diagnostics: uv run python -m jarvis.diag

Records 5s, plays it back, prints a VAD timeline, transcribes with timings.
Use this to tune wake_threshold / vad_aggressiveness / silence_stop_s with
real data from YOUR mic and room.
"""
import time
import wave

import sounddevice as sd
import webrtcvad

from .config import CONFIG
from .recorder import FRAME_SAMPLES
from .transcribe import Transcriber

WAV = "/tmp/jarvis-diag.wav"


def main() -> None:
    sec = 5
    print(f"recording {sec}s — speak normally...")
    audio = sd.rec(int(sec * CONFIG.sample_rate), samplerate=CONFIG.sample_rate,
                   channels=1, dtype="int16")
    sd.wait()
    mono = audio[:, 0]

    with wave.open(WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(CONFIG.sample_rate)
        w.writeframes(mono.tobytes())
    print(f"saved {WAV} — playing back...")
    sd.play(audio, CONFIG.sample_rate)
    sd.wait()

    vad = webrtcvad.Vad(CONFIG.vad_aggressiveness)
    line = "".join(
        "█" if vad.is_speech(mono[i:i + FRAME_SAMPLES].tobytes(), CONFIG.sample_rate)
        else "·"
        for i in range(0, len(mono) - FRAME_SAMPLES, FRAME_SAMPLES))
    print(f"VAD ({CONFIG.vad_frame_ms}ms/char, aggressiveness "
          f"{CONFIG.vad_aggressiveness}):\n{line}")

    print("loading whisper...")
    stt = Transcriber()
    t0 = time.monotonic()
    text, lang, prob = stt.transcribe(mono)
    print(f"transcribed in {time.monotonic() - t0:.1f}s: [{lang} {prob:.2f}] {text}")


if __name__ == "__main__":
    main()
