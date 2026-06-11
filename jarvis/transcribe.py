import numpy as np

from .config import CONFIG


ALLOWED_LANGS = ("en", "he")


class Transcriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(CONFIG.whisper_model, device="cpu",
                                  compute_type=CONFIG.whisper_compute)

    def _run(self, f32, language=None):
        segments, info = self.model.transcribe(
            f32, beam_size=1, vad_filter=True, language=language)
        return list(segments), info

    def transcribe(self, audio: np.ndarray) -> tuple[str, str, float]:
        """int16 mono 16kHz -> (text, language_code, confidence 0..1).

        Language is locked to ALLOWED_LANGS: if whisper free-detects anything
        else (accents confuse it), re-run forced to the likelier allowed one.
        Confidence = mean token probability damped by no-speech probability —
        a transcription-quality signal, NOT language certainty.
        """
        import math
        f32 = audio.astype(np.float32) / 32768.0
        segs, info = self._run(f32)
        lang = info.language
        if lang not in ALLOWED_LANGS:
            probs = dict(info.all_language_probs or [])
            lang = max(ALLOWED_LANGS, key=lambda l: probs.get(l, 0.0))
            segs, info = self._run(f32, language=lang)
        text = " ".join(s.text.strip() for s in segs).strip()
        if not segs:
            return "", lang, 0.0
        conf = sum(math.exp(s.avg_logprob) for s in segs) / len(segs)
        nospeech = max(s.no_speech_prob for s in segs)
        return text, lang, conf * (1.0 - nospeech)


def _main():
    """Transcribe a wav file: python -m jarvis.transcribe file.wav"""
    import sys
    import wave
    with wave.open(sys.argv[1], "rb") as w:
        assert w.getframerate() == CONFIG.sample_rate and w.getnchannels() == 1
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    text, lang, prob = Transcriber().transcribe(audio)
    print(f"[{lang} {prob:.2f}] {text}")


if __name__ == "__main__":
    _main()
