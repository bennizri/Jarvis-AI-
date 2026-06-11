import numpy as np
import webrtcvad

from .config import CONFIG

FRAME_SAMPLES = CONFIG.sample_rate * CONFIG.vad_frame_ms // 1000  # 480 @ 16kHz/30ms


class Recorder:
    """Consumes 30ms int16 frames after wake; returns the spoken command audio."""

    def __init__(self, vad=None):
        self.vad = vad or webrtcvad.Vad(CONFIG.vad_aggressiveness)

    def record(self, frames_iter, on_level=None) -> np.ndarray | None:
        voiced: list[np.ndarray] = []
        started = False
        speech_run = 0
        silence_ms = total_ms = 0
        for frame in frames_iter:
            total_ms += CONFIG.vad_frame_ms
            if total_ms > CONFIG.max_command_s * 1000:
                break
            if on_level:
                on_level(float(np.abs(frame).mean()) / 32768.0)
            voiced.append(frame)
            if self.vad.is_speech(frame.tobytes(), CONFIG.sample_rate):
                speech_run += 1
                # 3 consecutive speech frames (90ms) to start — a chime tail or
                # click is shorter and must not arm the silence end-pointer
                if speech_run >= 3:
                    started = True
                silence_ms = 0
            else:
                speech_run = 0
                silence_ms += CONFIG.vad_frame_ms
                if started and silence_ms >= CONFIG.silence_stop_s * 1000:
                    break
                if not started and total_ms >= CONFIG.no_speech_timeout_s * 1000:
                    return None
        if not started:
            return None
        audio = np.concatenate(voiced)
        if len(audio) < CONFIG.min_command_s * CONFIG.sample_rate:
            return None
        return audio
