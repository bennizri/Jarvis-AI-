import subprocess
import threading
from pathlib import Path

from .config import CONFIG

SPEAKING = threading.Event()  # mic must ignore the speakers while set


def _play(cmd: list[str]) -> None:
    """All speaker output goes through here so the wake loop can gate on it."""
    SPEAKING.set()
    try:
        subprocess.run(cmd, check=False)
    finally:
        SPEAKING.clear()

PHRASES = {
    "ready": {"he": "ג'ארביס מוכן", "en": "Jarvis online"},
    "didnt_catch": {"he": "לא שמעתי, נסה שוב", "en": "I didn't catch that"},
    "working": {"he": "עדיין עובד על זה", "en": "Still working on it"},
    "on_it": {"he": "על זה", "en": "On it"},
    "failed": {"he": "המשימה נכשלה", "en": "The task failed"},
    "cancelled": {"he": "ביטלתי את המשימה", "en": "Task cancelled"},
}


def voice_for(lang: str) -> str:
    return CONFIG.voices.get(lang, CONFIG.voices["en"])


_TTS_CACHE = Path("/tmp/jarvis-tts-cache")


def _neural(text: str, lang: str) -> bool:
    """Speak via edge-tts neural voice. Returns False so caller can fall back.

    Synthesis is network-bound and MUST be time-boxed — a hung request would
    freeze the main voice loop. Results are cached on disk so repeated phrases
    (chimes aside, most speech is canned) play instantly and survive offline.
    """
    path = _synth(text, lang)
    if path is None:
        return False  # offline / hung service -> robotic but working `say`
    _play(["afplay", str(path)])
    return True


def _synth(text: str, lang: str) -> Path | None:
    """Synthesize to the cache (or reuse). None on failure — caller falls back."""
    import asyncio
    import hashlib
    try:
        import edge_tts
    except ImportError:
        return None
    voice = CONFIG.neural_voices.get(lang, CONFIG.neural_voices["en"])
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()
    path = _TTS_CACHE / f"{key}.mp3"
    if not path.exists():
        try:
            _TTS_CACHE.mkdir(parents=True, exist_ok=True)
            asyncio.run(asyncio.wait_for(
                edge_tts.Communicate(text, voice).save(str(path)),
                timeout=CONFIG.tts_timeout_s))
        except Exception:
            path.unlink(missing_ok=True)  # never cache a partial file
            return None
    if not path.stat().st_size:
        path.unlink(missing_ok=True)
        return None
    return path


def warm_phrase_cache() -> None:
    """Pre-synthesize all canned phrases in the background at startup."""
    def run():
        for langs in PHRASES.values():
            for lang, text in langs.items():
                _synth(text, lang)

    threading.Thread(target=run, daemon=True, name="jarvis-tts-warm").start()


def speak(text: str, lang: str) -> None:
    if not text:
        return
    if CONFIG.tts_engine == "neural" and _neural(text, lang):
        return
    _play(["say", "-v", voice_for(lang), text])


def phrase(key: str, lang: str) -> None:
    speak(PHRASES[key].get(lang, PHRASES[key]["en"]), lang)


def check_voices() -> list[str]:
    """Returns missing voice names (warn at startup)."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return [v for v in CONFIG.voices.values() if v not in out]


def chime() -> None:
    # blocking, capped — recording must start only after the speaker is quiet,
    # otherwise the mic hears the chime and VAD end-points before the user talks
    _play(["afplay", "-t", "0.6", "/System/Library/Sounds/Glass.aiff"])


def chime_end() -> None:
    """Distinct short sound: 'got it, stopped recording'."""
    _play(["afplay", "-t", "0.4", "/System/Library/Sounds/Tink.aiff"])
