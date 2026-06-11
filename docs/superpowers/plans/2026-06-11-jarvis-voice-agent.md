# Jarvis Voice Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Always-on "Hey Jarvis" voice agent for macOS — Hebrew/English speech → Claude Code headless execution → Iron Man HUD web UI + spoken replies.

**Architecture:** Python daemon (wake word → VAD record → whisper transcribe → `claude -p` stream-json dispatch → `say` TTS) publishing every stage to an event bus; FastAPI serves a static canvas HUD over WebSocket. Voice pipeline runs in the main thread, claude tasks in a worker thread so wake word stays live ("still working").

**Tech Stack:** Python 3.11/3.12 (uv), openwakeword+onnxruntime, faster-whisper, webrtcvad-wheels, sounddevice, FastAPI+uvicorn, vanilla JS canvas UI, macOS `say`/`afplay`.

**Git:** User handles all commits — NO commit steps in this plan (user rule overrides skill default).

**Spec:** `docs/superpowers/specs/2026-06-11-jarvis-voice-agent-design.md`

---

### Task 1: Scaffold + config

**Files:**
- Create: `pyproject.toml`, `jarvis/__init__.py`, `jarvis/config.py`, `run.sh`, `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "jarvis"
version = "0.1.0"
description = "Hey Jarvis voice agent for macOS"
requires-python = ">=3.11,<3.13"
dependencies = [
    "openwakeword>=0.6",
    "onnxruntime>=1.16",
    "faster-whisper>=1.0",
    "sounddevice>=0.4",
    "webrtcvad-wheels>=2.0",
    "numpy>=1.24,<2.3",
    "fastapi>=0.110",
    "uvicorn>=0.29",
]

[dependency-groups]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `jarvis/__init__.py` and `tests/__init__.py`** (both empty)

- [ ] **Step 3: Create `jarvis/config.py`**

```python
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
    wake_threshold: float = 0.5
    # recording
    vad_aggressiveness: int = 2             # 0-3, higher = stricter speech detection
    silence_stop_s: float = 1.2
    max_command_s: float = 30.0
    min_command_s: float = 0.4
    no_speech_timeout_s: float = 5.0
    # whisper
    whisper_model: str = "small"
    whisper_compute: str = "int8"
    # dispatch
    working_dir: Path = Path(__file__).resolve().parent.parent / "workspace"
    permission_profile: str = "default"     # "default" | "yolo"
    allowed_tools: str = "Bash Read Edit Write Glob Grep WebSearch WebFetch Agent"
    # server
    port: int = 8765
    # tts
    voices: dict = field(default_factory=lambda: {"he": "Carmit", "en": "Samantha"})


CONFIG = Config()
```

- [ ] **Step 4: Create `run.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")"
(sleep 2 && open "http://localhost:8765") &
exec uv run python -m jarvis.jarvis
```

- [ ] **Step 5: Verify env resolves**

Run: `cd "/Users/bennizri/AI agent" && chmod +x run.sh && uv sync && uv run python -c "import jarvis.config; print(jarvis.config.CONFIG.port)"`
Expected: `8765`

---

### Task 2: Event bus

**Files:**
- Create: `jarvis/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write failing tests**

```python
import asyncio
import json

from jarvis.events import EventBus


def test_emit_fans_out_to_all_subscribers():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.emit("transcript", text="שלום", lang="he")
        await asyncio.sleep(0)  # let call_soon_threadsafe callbacks run
        m1, m2 = json.loads(q1.get_nowait()), json.loads(q2.get_nowait())
        assert m1 == {"type": "transcript", "text": "שלום", "lang": "he"}
        assert m2 == m1

    asyncio.run(scenario())


def test_set_state_tracks_and_emits():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        bus.set_state("listening")
        await asyncio.sleep(0)
        assert bus.state == "listening"
        assert json.loads(q.get_nowait()) == {"type": "state", "state": "listening"}

    asyncio.run(scenario())


def test_emit_without_loop_is_noop():
    bus = EventBus()
    bus.emit("state", state="idle")  # must not raise


def test_unsubscribe_stops_delivery():
    async def scenario():
        bus = EventBus()
        bus.attach_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit("state", state="idle")
        await asyncio.sleep(0)
        assert q.empty()

    asyncio.run(scenario())
```

- [ ] **Step 2: Run tests, verify fail**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.events'`

- [ ] **Step 3: Implement `jarvis/events.py`**

```python
import asyncio
import json
import threading


class EventBus:
    """Thread-safe fan-out from the voice pipeline threads to async WS clients."""

    def __init__(self):
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.state = "idle"

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def emit(self, type_: str, **data) -> None:
        if self._loop is None:
            return
        msg = json.dumps({"type": type_, **data}, ensure_ascii=False)
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            self._loop.call_soon_threadsafe(q.put_nowait, msg)

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", state=state)


BUS = EventBus()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_events.py -v`
Expected: 4 PASS

---

### Task 3: Dispatch — claude command, stream-json parsing, SPOKEN extraction

**Files:**
- Create: `jarvis/dispatch.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write failing tests**

```python
import json

from jarvis.config import CONFIG
from jarvis.dispatch import SPOKEN_TAG, build_cmd, extract_spoken, parse_line


def test_build_cmd_default_profile_uses_allowed_tools():
    cmd = build_cmd("list files")
    assert cmd[0] == "claude"
    assert cmd[1] == "-p"
    assert "list files" in cmd[2]
    assert SPOKEN_TAG in cmd[2]  # spoken-summary instruction appended
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--allowedTools" in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_yolo_profile():
    CONFIG.permission_profile = "yolo"
    try:
        assert "--dangerously-skip-permissions" in build_cmd("x")
    finally:
        CONFIG.permission_profile = "default"


def test_parse_line_tool_use():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]}})
    assert parse_line(line) == [{"kind": "tool", "name": "Bash", "detail": "ls -la"}]


def test_parse_line_text_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "checking files"}]}})
    assert parse_line(line) == [{"kind": "text", "text": "checking files"}]


def test_parse_line_result():
    line = json.dumps({"type": "result", "subtype": "success", "result": "done"})
    assert parse_line(line) == [{"kind": "result", "ok": True, "text": "done"}]


def test_parse_line_garbage_and_irrelevant():
    assert parse_line("not json{") == []
    assert parse_line(json.dumps({"type": "system", "subtype": "init"})) == []


def test_extract_spoken():
    text = "Did the thing.\nDetails here.\nSPOKEN: All done, three files changed."
    clean, spoken = extract_spoken(text)
    assert spoken == "All done, three files changed."
    assert "SPOKEN:" not in clean
    assert "Details here." in clean


def test_extract_spoken_missing():
    clean, spoken = extract_spoken("no tag here")
    assert clean == "no tag here" and spoken == ""
```

- [ ] **Step 2: Run tests, verify fail**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.dispatch'`

- [ ] **Step 3: Implement `jarvis/dispatch.py`**

```python
import json
import subprocess

from .config import CONFIG
from .events import BUS

SPOKEN_TAG = "SPOKEN:"
PROMPT_SUFFIX = (
    f"\n\nIMPORTANT: End your final answer with a line starting with '{SPOKEN_TAG} ' "
    "followed by ONE short spoken-style sentence summarizing the outcome, "
    "in the same language as this task."
)


def build_cmd(task: str) -> list[str]:
    cmd = ["claude", "-p", task + PROMPT_SUFFIX,
           "--output-format", "stream-json", "--verbose"]
    if CONFIG.permission_profile == "yolo":
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd += ["--allowedTools", CONFIG.allowed_tools]
    return cmd


def _tool_detail(block: dict) -> str:
    inp = block.get("input", {})
    for key in ("description", "file_path", "command", "pattern", "prompt"):
        if key in inp:
            return str(inp[key])[:120]
    return ""


def parse_line(line: str) -> list[dict]:
    """One stream-json NDJSON line -> list of UI-level events."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return []
    events: list[dict] = []
    if obj.get("type") == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                events.append({"kind": "tool", "name": block.get("name", "?"),
                               "detail": _tool_detail(block)})
            elif block.get("type") == "text" and block.get("text"):
                events.append({"kind": "text", "text": block["text"]})
    elif obj.get("type") == "result":
        events.append({"kind": "result", "ok": obj.get("subtype") == "success",
                       "text": obj.get("result") or ""})
    return events


def extract_spoken(text: str) -> tuple[str, str]:
    """Split SPOKEN: line out of the answer. Returns (clean_text, spoken)."""
    spoken, kept = "", []
    for ln in text.splitlines():
        if ln.strip().startswith(SPOKEN_TAG):
            spoken = ln.strip()[len(SPOKEN_TAG):].strip()
        else:
            kept.append(ln)
    return "\n".join(kept).strip(), spoken


def run_task(task: str) -> tuple[str, str, bool]:
    """Run claude headless, stream agent events to BUS. Returns (text, spoken, ok)."""
    CONFIG.working_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(build_cmd(task), cwd=CONFIG.working_dir,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    full, ok = "", False
    assert proc.stdout is not None
    for line in proc.stdout:
        for ev in parse_line(line):
            if ev["kind"] == "tool":
                BUS.emit("agent_event", name=ev["name"], detail=ev["detail"])
            elif ev["kind"] == "text":
                BUS.emit("agent_event", name="jarvis", detail=ev["text"][:200])
            else:
                full, ok = ev["text"], ev["ok"]
    proc.wait()
    if proc.returncode != 0 and not full:
        err = (proc.stderr.read() if proc.stderr else "")[:500]
        BUS.emit("error", message=err or f"claude exited {proc.returncode}")
        return "", "", False
    clean, spoken = extract_spoken(full)
    return clean, spoken, ok
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: 8 PASS

---

### Task 4: Recorder (VAD end-pointing)

**Files:**
- Create: `jarvis/recorder.py`
- Test: `tests/test_recorder.py`

- [ ] **Step 1: Write failing tests** (stub VAD injected — no real audio needed)

```python
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
```

- [ ] **Step 2: Run tests, verify fail**

Run: `uv run pytest tests/test_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.recorder'`

- [ ] **Step 3: Implement `jarvis/recorder.py`**

```python
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
        silence_ms = total_ms = 0
        for frame in frames_iter:
            total_ms += CONFIG.vad_frame_ms
            if total_ms > CONFIG.max_command_s * 1000:
                break
            if on_level:
                on_level(float(np.abs(frame).mean()) / 32768.0)
            voiced.append(frame)
            if self.vad.is_speech(frame.tobytes(), CONFIG.sample_rate):
                started = True
                silence_ms = 0
            else:
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_recorder.py -v`
Expected: 4 PASS

---

### Task 5: Speak (TTS) + canned phrases

**Files:**
- Create: `jarvis/speak.py`
- Test: `tests/test_speak.py`

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import patch

from jarvis import speak


def test_voice_for_language():
    assert speak.voice_for("he") == "Carmit"
    assert speak.voice_for("en") == "Samantha"
    assert speak.voice_for("fr") == "Samantha"  # unknown -> english voice


def test_speak_invokes_say():
    with patch("subprocess.run") as run:
        speak.speak("שלום", "he")
        run.assert_called_once_with(["say", "-v", "Carmit", "שלום"], check=False)


def test_phrase_known_key():
    with patch("subprocess.run") as run:
        speak.phrase("didnt_catch", "he")
        args = run.call_args[0][0]
        assert args[:3] == ["say", "-v", "Carmit"]
```

- [ ] **Step 2: Run tests, verify fail**

Run: `uv run pytest tests/test_speak.py -v`
Expected: FAIL — `AttributeError`/import error

- [ ] **Step 3: Implement `jarvis/speak.py`**

```python
import subprocess

from .config import CONFIG

PHRASES = {
    "ready": {"he": "ג'ארביס מוכן", "en": "Jarvis online"},
    "didnt_catch": {"he": "לא שמעתי, נסה שוב", "en": "I didn't catch that"},
    "working": {"he": "עדיין עובד על זה", "en": "Still working on it"},
    "failed": {"he": "המשימה נכשלה", "en": "The task failed"},
}


def voice_for(lang: str) -> str:
    return CONFIG.voices.get(lang, CONFIG.voices["en"])


def speak(text: str, lang: str) -> None:
    if text:
        subprocess.run(["say", "-v", voice_for(lang), text], check=False)


def phrase(key: str, lang: str) -> None:
    speak(PHRASES[key].get(lang, PHRASES[key]["en"]), lang)


def check_voices() -> list[str]:
    """Returns missing voice names (warn at startup)."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return [v for v in CONFIG.voices.values() if v not in out]


def chime() -> None:
    subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_speak.py -v`
Expected: 3 PASS

- [ ] **Step 5: Manual sanity — hear both voices**

Run: `uv run python -c "from jarvis import speak; print('missing:', speak.check_voices()); speak.phrase('ready','en'); speak.phrase('ready','he')"`
Expected: prints `missing: []` (or names — if Carmit missing, install via System Settings → Accessibility → Spoken Content → System Voice → Manage Voices → Hebrew), speaks both phrases aloud.

---

### Task 6: Wake word detector

**Files:**
- Create: `jarvis/wake.py`

(No unit test — model-dependent. Standalone live check instead.)

- [ ] **Step 1: Implement `jarvis/wake.py`**

```python
import numpy as np

from .config import CONFIG


class WakeDetector:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model
        openwakeword.utils.download_models([CONFIG.wake_model])
        self.model = Model(wakeword_models=[CONFIG.wake_model],
                           inference_framework="onnx")

    def detect(self, frame: np.ndarray) -> bool:
        """frame: int16 mono, CONFIG.wake_frame_samples long."""
        score = self.model.predict(frame)[CONFIG.wake_model]
        if score >= CONFIG.wake_threshold:
            self.model.reset()
            return True
        return False


def _main():
    """Live mic check: prints a line every time the wake word fires."""
    import sounddevice as sd
    det = WakeDetector()
    print("Say 'Hey Jarvis'... (ctrl-c to stop)")
    n = CONFIG.wake_frame_samples
    with sd.InputStream(samplerate=CONFIG.sample_rate, channels=1,
                        dtype="int16", blocksize=n) as stream:
        while True:
            data, _ = stream.read(n)
            if det.detect(data[:, 0]):
                print("WAKE DETECTED")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 2: Live check (downloads model on first run, triggers mic permission prompt)**

Run: `uv run python -m jarvis.wake` — say "Hey Jarvis" 3 times.
Expected: `WAKE DETECTED` printed each time; no prints when talking normally. If macOS mic prompt appears, click Allow.

---

### Task 7: Transcriber

**Files:**
- Create: `jarvis/transcribe.py`

(No unit test — model-dependent. Standalone check with generated speech.)

- [ ] **Step 1: Implement `jarvis/transcribe.py`**

```python
import numpy as np

from .config import CONFIG


class Transcriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(CONFIG.whisper_model, device="cpu",
                                  compute_type=CONFIG.whisper_compute)

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        """int16 mono 16kHz -> (text, language_code)."""
        f32 = audio.astype(np.float32) / 32768.0
        segments, info = self.model.transcribe(f32, beam_size=5, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language


def _main():
    """Transcribe a wav file: python -m jarvis.transcribe file.wav"""
    import sys
    import wave
    with wave.open(sys.argv[1], "rb") as w:
        assert w.getframerate() == CONFIG.sample_rate and w.getnchannels() == 1
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    text, lang = Transcriber().transcribe(audio)
    print(f"[{lang}] {text}")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 2: Generate test wavs with `say` and verify both languages**

Run:
```bash
say -v Samantha -o /tmp/en.wav --data-format=LEI16@16000 "open the project and run the tests"
say -v Carmit -o /tmp/he.wav --data-format=LEI16@16000 "תפתח את הפרויקט ותריץ את הטסטים"
uv run python -m jarvis.transcribe /tmp/en.wav
uv run python -m jarvis.transcribe /tmp/he.wav
```
Expected: first prints `[en] ...open the project...`, second prints `[he] ...תפתח את הפרויקט...` (minor wording drift OK; language codes must be `en` and `he`). First run downloads the whisper model (~500MB).

---

### Task 8: Web server (FastAPI + WS)

**Files:**
- Create: `jarvis/server.py`, `ui/index.html` (placeholder for test)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

```python
import json

from fastapi.testclient import TestClient

from jarvis.events import BUS
from jarvis.server import app


def test_ws_receives_current_state_then_events():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            first = json.loads(ws.receive_text())
            assert first["type"] == "state"
            BUS.emit("transcript", text="hi", lang="en")
            msg = json.loads(ws.receive_text())
            assert msg == {"type": "transcript", "text": "hi", "lang": "en"}


def test_serves_index():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "J.A.R.V.I.S" in r.text
```

- [ ] **Step 2: Create placeholder `ui/index.html`**

```html
<!doctype html><html><head><title>J.A.R.V.I.S</title></head><body>J.A.R.V.I.S</body></html>
```

- [ ] **Step 3: Run tests, verify fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.server'`

- [ ] **Step 4: Implement `jarvis/server.py`**

```python
import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .events import BUS

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
app = FastAPI()


@app.on_event("startup")
async def _startup():
    BUS.attach_loop(asyncio.get_running_loop())


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    q = BUS.subscribe()
    try:
        await websocket.send_text(json.dumps({"type": "state", "state": BUS.state}))
        while True:
            await websocket.send_text(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        BUS.unsubscribe(q)


app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")


def start_server() -> None:
    """Run uvicorn in a daemon thread; pipeline stays in the main thread."""
    import uvicorn

    def run():
        uvicorn.run(app, host="127.0.0.1", port=CONFIG.port, log_level="warning")

    threading.Thread(target=run, daemon=True, name="jarvis-server").start()
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: 2 PASS

---

### Task 9: HUD UI — Iron Man style

**Files:**
- Create: `ui/index.html` (replace placeholder), `ui/style.css`, `ui/ws.js`, `ui/hud.js`, `ui/graph.js`

UI contract (from spec): reacts to WS events `state`, `mic_level`, `transcript`, `agent_event`, `answer`, `error`. States: `idle | listening | transcribing | working | speaking`. Hebrew text renders RTL.

- [ ] **Step 1: Create `ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>J.A.R.V.I.S</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div id="scanlines"></div>
<header>
  <span class="brand">J.A.R.V.I.S</span>
  <span id="status-label">OFFLINE</span>
  <span id="conn-dot" class="dot"></span>
</header>
<main>
  <section id="left">
    <canvas id="core"></canvas>
    <div id="transcript" class="panel">
      <h2>// TRANSCRIPT</h2>
      <p id="transcript-text">—</p>
    </div>
  </section>
  <section id="right">
    <div id="mission" class="panel">
      <h2>// MISSION CONTROL</h2>
      <canvas id="graph"></canvas>
      <ul id="log"></ul>
    </div>
    <div id="answer" class="panel">
      <h2>// OUTPUT</h2>
      <p id="spoken-line"></p>
      <pre id="answer-text"></pre>
    </div>
  </section>
</main>
<script src="ws.js"></script>
<script src="hud.js"></script>
<script src="graph.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `ui/style.css`**

```css
:root {
  --cyan: #2ee6ff; --cyan-dim: #0a4a57; --amber: #ffb347;
  --green: #4dff9d; --red: #ff4d5e; --bg: #04080d; --panel: #07121acc;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: radial-gradient(ellipse at 35% 40%, #0a1620 0%, var(--bg) 70%);
  color: var(--cyan); font-family: "SF Mono", Menlo, monospace;
  height: 100vh; overflow: hidden;
}
#scanlines {
  position: fixed; inset: 0; pointer-events: none; z-index: 10;
  background: repeating-linear-gradient(0deg, transparent 0 2px, #00000022 2px 4px);
}
header {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 24px; border-bottom: 1px solid var(--cyan-dim);
  text-shadow: 0 0 8px var(--cyan);
}
.brand { font-size: 20px; letter-spacing: 8px; }
#status-label { margin-left: auto; letter-spacing: 3px; font-size: 12px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--red); }
.dot.on { background: var(--green); box-shadow: 0 0 8px var(--green); }
main { display: flex; height: calc(100vh - 53px); }
#left { flex: 1.1; display: flex; flex-direction: column; padding: 16px; gap: 16px; }
#right { flex: 1; display: flex; flex-direction: column; padding: 16px 16px 16px 0; gap: 16px; }
#core { flex: 1; width: 100%; min-height: 0; }
.panel {
  background: var(--panel); border: 1px solid var(--cyan-dim);
  border-radius: 6px; padding: 12px 16px; backdrop-filter: blur(4px);
}
.panel h2 { font-size: 11px; letter-spacing: 3px; color: #6fd8e8; margin-bottom: 8px; }
#transcript-text { font-size: 16px; min-height: 24px; }
#transcript-text.rtl { direction: rtl; text-align: right; }
#mission { flex: 1.4; display: flex; flex-direction: column; min-height: 0; }
#graph { flex: 1; width: 100%; min-height: 0; }
#log {
  list-style: none; max-height: 130px; overflow-y: auto;
  font-size: 11px; color: #8fc7d4; margin-top: 8px;
}
#log li { padding: 2px 0; border-bottom: 1px dashed #0a3a45; }
#log li b { color: var(--amber); }
#answer { flex: 1; min-height: 0; display: flex; flex-direction: column; }
#spoken-line { color: var(--green); font-size: 14px; margin-bottom: 6px; text-shadow: 0 0 6px var(--green); }
#spoken-line.rtl, #answer-text.rtl { direction: rtl; text-align: right; }
#answer-text { flex: 1; overflow-y: auto; font-size: 12px; color: #b8e6f0; white-space: pre-wrap; }
body.error header { border-bottom-color: var(--red); }
```

- [ ] **Step 3: Create `ui/ws.js`** (connection + event routing; other files register handlers on `window.JARVIS`)

```javascript
window.JARVIS = {
  state: "idle",
  micLevel: 0,
  handlers: { state: [], mic_level: [], transcript: [], agent_event: [], answer: [], error: [] },
  on(type, fn) { this.handlers[type].push(fn); },
};

(function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  const dot = document.getElementById("conn-dot");
  ws.onopen = () => dot.classList.add("on");
  ws.onclose = () => { dot.classList.remove("on"); setTimeout(connect, 1500); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "state") window.JARVIS.state = msg.state;
    if (msg.type === "mic_level") window.JARVIS.micLevel = msg.level;
    (window.JARVIS.handlers[msg.type] || []).forEach((fn) => fn(msg));
  };
})();

const LABELS = { idle: "STANDBY", listening: "LISTENING", transcribing: "ANALYZING",
                 working: "EXECUTING", speaking: "RESPONDING" };
window.JARVIS.on("state", (m) => {
  document.getElementById("status-label").textContent = LABELS[m.state] || m.state.toUpperCase();
  document.body.classList.toggle("error", false);
});
window.JARVIS.on("transcript", (m) => {
  const el = document.getElementById("transcript-text");
  el.textContent = m.text;
  el.classList.toggle("rtl", m.lang === "he");
});
window.JARVIS.on("answer", (m) => {
  const isHe = /[֐-׿]/.test(m.spoken || m.text);
  const spoken = document.getElementById("spoken-line");
  const full = document.getElementById("answer-text");
  spoken.textContent = m.spoken ? `🗣 ${m.spoken}` : "";
  full.textContent = m.text;
  spoken.classList.toggle("rtl", isHe);
  full.classList.toggle("rtl", isHe);
});
window.JARVIS.on("error", (m) => {
  document.body.classList.add("error");
  document.getElementById("status-label").textContent = "ERROR";
  const li = document.createElement("li");
  li.innerHTML = `<b>ERROR</b> ${m.message}`;
  document.getElementById("log").prepend(li);
});
```

- [ ] **Step 4: Create `ui/hud.js`** — arc-reactor core animation

```javascript
(function () {
  const canvas = document.getElementById("core");
  const ctx = canvas.getContext("2d");

  const COLORS = { idle: "#2ee6ff", listening: "#2ee6ff", transcribing: "#ffb347",
                   working: "#ffb347", speaking: "#4dff9d" };
  const SPIN = { idle: 0.2, listening: 0.5, transcribing: 1.2, working: 2.5, speaking: 0.8 };

  let t = 0;
  function resize() {
    canvas.width = canvas.clientWidth * devicePixelRatio;
    canvas.height = canvas.clientHeight * devicePixelRatio;
  }
  window.addEventListener("resize", resize);
  resize();

  function ring(cx, cy, r, width, color, alpha, dashes, rot) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rot);
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = width;
    ctx.shadowBlur = 18;
    ctx.shadowColor = color;
    if (dashes) ctx.setLineDash(dashes);
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function draw() {
    const st = window.JARVIS.state;
    const color = COLORS[st] || COLORS.idle;
    t += 0.016 * (SPIN[st] || 0.2);
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) / 2 * 0.62;
    ctx.clearRect(0, 0, w, h);

    // breathing / mic-reactive core
    let pulse = 1 + Math.sin(t * 4) * 0.04;
    if (st === "listening") pulse = 1 + window.JARVIS.micLevel * 2.2;

    const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, base * 0.42 * pulse);
    grad.addColorStop(0, "#ffffff");
    grad.addColorStop(0.25, color);
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, base * 0.42 * pulse, 0, Math.PI * 2);
    ctx.fill();

    // rotating ring stack
    ring(cx, cy, base * 0.55, 3, color, 0.9, [40, 18], t);
    ring(cx, cy, base * 0.72, 1.5, color, 0.55, [8, 10], -t * 1.6);
    ring(cx, cy, base * 0.88, 5, color, 0.35, [90, 50], t * 0.7);
    ring(cx, cy, base * 1.0, 1, color, 0.25, null, 0);

    // tick marks
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-t * 0.5);
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.6;
    for (let i = 0; i < 24; i++) {
      ctx.rotate(Math.PI / 12);
      ctx.beginPath();
      ctx.moveTo(base * 0.93, 0);
      ctx.lineTo(base * (i % 6 === 0 ? 0.99 : 0.96), 0);
      ctx.stroke();
    }
    ctx.restore();

    requestAnimationFrame(draw);
  }
  draw();
})();
```

- [ ] **Step 5: Create `ui/graph.js`** — mission-control node graph + log

```javascript
(function () {
  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d");
  const log = document.getElementById("log");
  // name -> {angle, activity (0..1 decaying), count}
  const nodes = new Map();

  function resize() {
    canvas.width = canvas.clientWidth * devicePixelRatio;
    canvas.height = canvas.clientHeight * devicePixelRatio;
  }
  window.addEventListener("resize", resize);
  resize();

  window.JARVIS.on("agent_event", (m) => {
    if (!nodes.has(m.name)) {
      nodes.set(m.name, { angle: Math.random() * Math.PI * 2, activity: 1, count: 0 });
    }
    const n = nodes.get(m.name);
    n.activity = 1;
    n.count += 1;
    const li = document.createElement("li");
    li.innerHTML = `<b>${m.name}</b> ${m.detail || ""}`;
    log.prepend(li);
    while (log.children.length > 60) log.removeChild(log.lastChild);
  });

  window.JARVIS.on("state", (m) => {
    if (m.state === "listening") { nodes.clear(); log.innerHTML = ""; }
  });

  function draw() {
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * 0.34;
    ctx.clearRect(0, 0, w, h);
    const busy = window.JARVIS.state === "working";

    // center core
    ctx.fillStyle = busy ? "#ffb347" : "#2ee6ff";
    ctx.shadowBlur = 16;
    ctx.shadowColor = ctx.fillStyle;
    ctx.beginPath();
    ctx.arc(cx, cy, 9 * devicePixelRatio, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = `${10 * devicePixelRatio}px Menlo`;
    ctx.fillText("JARVIS", cx + 14 * devicePixelRatio, cy + 4);

    for (const [name, n] of nodes) {
      n.activity = Math.max(0.15, n.activity * 0.985);
      const x = cx + Math.cos(n.angle) * R;
      const y = cy + Math.sin(n.angle) * R;
      // pulsing edge
      ctx.strokeStyle = `rgba(46,230,255,${n.activity * 0.8})`;
      ctx.lineWidth = (0.5 + n.activity * 2) * devicePixelRatio;
      ctx.shadowBlur = 10 * n.activity;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
      // node
      ctx.fillStyle = `rgba(255,179,71,${0.4 + n.activity * 0.6})`;
      ctx.beginPath();
      ctx.arc(x, y, (4 + n.activity * 5) * devicePixelRatio, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#8fc7d4";
      ctx.fillText(`${name} ×${n.count}`, x + 10 * devicePixelRatio, y + 3);
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
```

- [ ] **Step 6: Verify server tests still pass + visual smoke test**

Run: `uv run pytest tests/test_server.py -v`
Expected: 2 PASS

Then visual check with fake events:
```bash
uv run python - <<'EOF'
import threading, time
from jarvis.server import start_server
from jarvis.events import BUS
start_server()
time.sleep(1.5)
print("open http://localhost:8765 — demo loop running, ctrl-c to stop")
while True:
    BUS.set_state("listening")
    for i in range(40):
        BUS.emit("mic_level", level=abs(__import__("math").sin(i/4))*0.5); time.sleep(0.05)
    BUS.emit("transcript", text="תריץ את הטסטים בפרויקט", lang="he")
    BUS.set_state("transcribing"); time.sleep(1.5)
    BUS.set_state("working")
    for name, detail in [("Bash","pytest -v"),("Read","src/app.py"),("Explore","scanning repo"),("Bash","pytest -v"),("Edit","src/app.py")]:
        BUS.emit("agent_event", name=name, detail=detail); time.sleep(1.2)
    BUS.emit("answer", text="All 12 tests pass.", spoken="הכל עובד, כל הטסטים עוברים")
    BUS.set_state("speaking"); time.sleep(2)
    BUS.set_state("idle"); time.sleep(3)
EOF
```
Expected in browser: arc reactor pulses with mic level, transcript shows Hebrew RTL, mission control shows nodes (Bash, Read, Explore, Edit) lighting up with pulsing edges + log lines, answer panel shows spoken line in green RTL, state label cycles STANDBY→LISTENING→ANALYZING→EXECUTING→RESPONDING.

---

### Task 10: Main orchestrator

**Files:**
- Create: `jarvis/jarvis.py`

- [ ] **Step 1: Implement `jarvis/jarvis.py`**

```python
import shutil
import sys
import threading

import sounddevice as sd

from . import speak
from .config import CONFIG
from .dispatch import run_task
from .events import BUS
from .recorder import FRAME_SAMPLES, Recorder
from .server import start_server
from .transcribe import Transcriber
from .wake import WakeDetector


def mic_frames(samples: int):
    """Yield int16 mono frames of `samples` from the default mic, forever."""
    with sd.InputStream(samplerate=CONFIG.sample_rate, channels=1,
                        dtype="int16", blocksize=samples) as stream:
        while True:
            data, _ = stream.read(samples)
            yield data[:, 0]


def record_command(rec: Recorder):
    frames = mic_frames(FRAME_SAMPLES)
    return rec.record(frames, on_level=lambda lv: BUS.emit("mic_level", level=lv))


def dispatch_async(text: str, lang: str) -> threading.Thread:
    def work():
        clean, spoken, ok = run_task(text)
        BUS.emit("answer", text=clean, spoken=spoken, ok=ok)
        BUS.set_state("speaking")
        if spoken:
            speak.speak(spoken, lang)
        elif not ok:
            speak.phrase("failed", lang)
        BUS.set_state("idle")

    t = threading.Thread(target=work, daemon=True, name="jarvis-task")
    t.start()
    return t


def startup_checks() -> None:
    if not shutil.which("claude"):
        sys.exit("FATAL: `claude` CLI not found on PATH.")
    missing = speak.check_voices()
    if missing:
        print(f"WARNING: missing macOS voices: {missing} — "
              "install via System Settings > Accessibility > Spoken Content.")


def main() -> None:
    startup_checks()
    start_server()
    print(f"HUD: http://localhost:{CONFIG.port}")
    print("Loading models (first run downloads them)...")
    wake, rec, stt = WakeDetector(), Recorder(), Transcriber()
    task_thread: threading.Thread | None = None
    BUS.set_state("idle")
    speak.phrase("ready", "en")
    print("Ready. Say 'Hey Jarvis'.")

    wake_stream = mic_frames(CONFIG.wake_frame_samples)
    for frame in wake_stream:
        if not wake.detect(frame):
            continue
        if task_thread and task_thread.is_alive():
            speak.phrase("working", "en")
            continue
        speak.chime()
        BUS.set_state("listening")
        audio = record_command(rec)
        if audio is None:
            speak.phrase("didnt_catch", "en")
            BUS.set_state("idle")
            continue
        BUS.set_state("transcribing")
        text, lang = stt.transcribe(audio)
        lang = lang if lang in CONFIG.voices else "en"
        if not text:
            speak.phrase("didnt_catch", lang)
            BUS.set_state("idle")
            continue
        print(f"[{lang}] {text}")
        BUS.emit("transcript", text=text, lang=lang)
        BUS.set_state("working")
        task_thread = dispatch_async(text, lang)


if __name__ == "__main__":
    main()
```

**Known simplification (acceptable v1):** `record_command` opens a second mic stream via a fresh `mic_frames` generator while the wake generator's stream is still open. On macOS two input streams on the same device work, but if `sounddevice` raises, fix = close/reopen pattern: make `mic_frames` a context-managed class. Don't pre-build the fix unless the error occurs.

- [ ] **Step 2: Full test suite green**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 3: End-to-end live test (English)**

Run: `./run.sh`
Then: say "Hey Jarvis" → chime → say "create a file called hello dot text with the word hello in it".
Expected: HUD shows full cycle; terminal prints transcript; `workspace/hello.txt` exists after; Jarvis speaks a one-line English summary.
Verify: `cat "/Users/bennizri/AI agent/workspace/hello.txt"` → contains "hello".

- [ ] **Step 4: End-to-end live test (Hebrew)**

Say "Hey Jarvis" → «תיצור קובץ בשם שלום נקודה טקסט עם המילה שלום בפנים».
Expected: transcript RTL in HUD, file created, spoken reply in Hebrew (Carmit voice).

- [ ] **Step 5: Busy behavior test**

Give a long task ("Hey Jarvis... write a long story to story.txt"), then while working say "Hey Jarvis" again.
Expected: speaks "Still working on it", task continues, no second task starts.

---

### Task 11: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Jarvis — voice agent for macOS

Say **"Hey Jarvis"**, speak a task in **Hebrew or English**, watch it execute in the HUD, hear the answer.

## Run

```bash
./run.sh          # starts daemon + opens HUD at http://localhost:8765
```

First run: downloads wake-word model (small) + whisper model (~500MB), and macOS asks for mic permission.

## Requirements

- macOS, `uv`, `claude` CLI on PATH
- Hebrew voice "Carmit": System Settings → Accessibility → Spoken Content → System Voice → Manage Voices

## Config

Edit `jarvis/config.py`:
- `working_dir` — where claude tasks run (default `./workspace`)
- `permission_profile` — `"default"` (allowlisted tools) or `"yolo"` (skip all permission checks)
- `whisper_model` — `small` (default) / `medium` (better Hebrew, slower)
- `wake_threshold` — raise if false triggers, lower if it misses you

## Architecture

See `docs/superpowers/specs/2026-06-11-jarvis-voice-agent-design.md`.

Voice pipeline: openwakeword → webrtcvad → faster-whisper → `claude -p` (stream-json) → `say`.
UI: FastAPI + WebSocket → canvas HUD (arc reactor + mission-control agent graph).

## v2 ideas

Hebrew wake phrase, launchd autostart, multi-turn conversations, task queue.
```

- [ ] **Step 2: Final verification — full suite + manual smoke**

Run: `uv run pytest -v` → all PASS. Then one more `./run.sh` cycle with any quick voice task.
```

---

## Self-review notes

- **Spec coverage:** wake (T6), VAD record (T4), transcribe (T7), dispatch+SPOKEN+permissions (T3), TTS+phrases (T5), event protocol (T2/T8), HUD all states + RTL + mission control + error flash (T9), busy="still working" + orchestration + startup checks (T10), whisper download UX (print in T10 + README), WS reconnect (ws.js), claude-missing fatal (T10). Gap check: "UI shows download progress state" from spec — downgraded to terminal print + README note (faster-whisper doesn't expose progress callbacks cleanly); acceptable v1 deviation.
- **Type consistency:** `Recorder(vad=)` injection used by tests matches T4 signature; `FRAME_SAMPLES` imported in T10 from recorder; `extract_spoken` returns `(clean, spoken)` used in `run_task`; `BUS` singleton shared by dispatch/server/jarvis. T8 test asserts `"J.A.R.V.I.S" in r.text` — satisfied by both placeholder and final HTML.
```
