import numpy as np

from jarvis.config import CONFIG
from jarvis.recorder import FRAME_SAMPLES, Recorder


class StubVad:
    """Speech pattern scripted per frame."""
    def __init__(self, pattern):
        self.pattern = list(pattern)
        self.i = 0

    def is_speech(self, _buf, _rate):
        val = self.pattern[min(self.i, len(self.pattern) - 1)]
        self.i += 1
        return val


def frames(n):
    return (np.zeros(FRAME_SAMPLES, dtype=np.int16) for _ in range(n))


def speech_frames(speech_n, silence_n):
    pattern = [True] * speech_n + [False] * silence_n
    return StubVad(pattern), frames(speech_n + silence_n + 10)


def test_returns_audio_after_speech_then_silence():
    silence_frames_needed = int(CONFIG.silence_stop_s * 1000 / CONFIG.vad_frame_ms)
    vad, fr = speech_frames(30, silence_frames_needed + 5)
    audio = Recorder(vad=vad).record(fr)
    assert audio is not None
    assert len(audio) >= 30 * FRAME_SAMPLES  # at least the speech portion


def test_returns_none_when_user_never_speaks():
    vad = StubVad([False])
    audio = Recorder(vad=vad).record(frames(1000))
    assert audio is None


def test_returns_none_when_speech_too_short():
    # 2 speech frames (60ms) < min_command_s
    silence_frames_needed = int(CONFIG.silence_stop_s * 1000 / CONFIG.vad_frame_ms)
    vad, fr = speech_frames(2, silence_frames_needed + 5)
    old = CONFIG.min_command_s
    CONFIG.min_command_s = 2.0
    try:
        assert Recorder(vad=vad).record(fr) is None
    finally:
        CONFIG.min_command_s = old


def test_level_callback_fires():
    levels = []
    silence_frames_needed = int(CONFIG.silence_stop_s * 1000 / CONFIG.vad_frame_ms)
    vad, fr = speech_frames(10, silence_frames_needed + 5)
    Recorder(vad=vad).record(fr, on_level=levels.append)
    assert len(levels) > 0
