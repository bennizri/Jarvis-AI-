from unittest.mock import patch

from jarvis import speak
from jarvis.config import CONFIG


def setup_function(_):
    CONFIG.tts_engine = "say"  # tests never hit the network


def teardown_function(_):
    CONFIG.tts_engine = "neural"


def test_voice_for_language():
    assert speak.voice_for("he") == "Carmit"
    assert speak.voice_for("en") == "Samantha"
    assert speak.voice_for("fr") == "Samantha"  # unknown -> english voice


def test_say_engine_invokes_say():
    with patch("subprocess.run") as run:
        speak.speak("שלום", "he")
        run.assert_called_once_with(["say", "-v", "Carmit", "שלום"], check=False)


def test_phrase_known_key():
    with patch("subprocess.run") as run:
        speak.phrase("didnt_catch", "he")
        args = run.call_args[0][0]
        assert args[:3] == ["say", "-v", "Carmit"]


def test_neural_falls_back_to_say_when_unavailable():
    CONFIG.tts_engine = "neural"
    with patch("jarvis.speak._neural", return_value=False), \
         patch("subprocess.run") as run:
        speak.speak("hello", "en")
        run.assert_called_once_with(["say", "-v", "Samantha", "hello"], check=False)


def test_speaking_event_set_during_playback():
    seen = []
    with patch("subprocess.run",
               side_effect=lambda *a, **k: seen.append(speak.SPEAKING.is_set())):
        speak.speak("hello", "en")
    assert seen == [True]
    assert not speak.SPEAKING.is_set()


def test_chime_sets_speaking_event():
    seen = []
    with patch("subprocess.run",
               side_effect=lambda *a, **k: seen.append(speak.SPEAKING.is_set())):
        speak.chime()
    assert seen == [True]
    assert not speak.SPEAKING.is_set()
