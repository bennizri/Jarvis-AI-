from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # audio
    sample_rate: int = 16000
    wake_frame_samples: int = 1280          # 80ms — openwakeword's expected frame
    vad_frame_ms: int = 30                  # webrtcvad frame size
    # wake
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.25            # calibrated to user's voice 2026-06-11
    # recording
    vad_aggressiveness: int = 2             # 0-3, higher = stricter speech detection
    silence_stop_s: float = 1.8             # pause tolerance before cut
    max_command_s: float = 20.0             # whisper-on-CPU stays fast enough
    min_command_s: float = 0.4
    no_speech_timeout_s: float = 5.0
    # whisper
    whisper_model: str = "small"
    whisper_compute: str = "int8"
    transcribe_timeout_s: float = 45.0
    # dispatch
    working_dir: Path = Path(__file__).resolve().parent.parent / "workspace"
    permission_profile: str = "default"     # "default" | "yolo"
    allowed_tools: str = ("Bash Read Edit Write Glob Grep WebSearch WebFetch Agent "
                          "Skill ToolSearch RemoteTrigger KillShell TaskOutput "
                          "mcp__plugin_superpowers-chrome_chrome__use_browser")
    chat_model: str = "haiku"               # snappy answers for small talk/questions
    work_model: str = ""                    # "" = CLI default (full power)
    # server
    port: int = 8765
    open_hud_on_wake: bool = True           # bring HUD browser tab to front on wake
    # fleet (cloud routine monitoring)
    fleet_poll_s: int = 600
    fleet_model: str = "haiku"              # cheap model for status/report polls
    reports_poll_s: int = 300
    speak_failures: bool = True             # announce FAIL reports aloud when idle
    digest_time: str = "09:30"              # daily spoken fleet digest, local time
    # tts
    tts_engine: str = "neural"              # "neural" (edge-tts) | "say" (offline)
    tts_timeout_s: float = 6.0              # neural synth must answer fast or we fall back
    voices: dict = field(default_factory=lambda: {"he": "Carmit", "en": "Samantha"})
    neural_voices: dict = field(default_factory=lambda: {
        "he": "he-IL-AvriNeural",           # natural Hebrew male
        "en": "en-GB-RyanNeural",           # British male — the Jarvis vibe
    })


CONFIG = Config()
