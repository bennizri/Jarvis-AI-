# Jarvis Voice Perfection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the voice loop feel solid and trustworthy: Jarvis never triggers on his own voice, never hijacks ambient speech as commands, never cuts you mid-sentence, always signals what he's doing (start/stop chimes, timers), survives Ctrl-C and audio errors gracefully, can be cancelled by voice, and ships a diagnostic tool for tuning.

**Architecture:** Six defects, six mechanisms. (1) A global `SPEAKING` event in `speak.py` — every speaker output sets it; the wake loop discards mic frames while set (no self-trigger). (2) A confidence gate (`quality.py`) — whisper's language probability + word count decide whether captured audio was a real command; follow-up captures need a higher bar than explicit wakes. (3) Recording UX — end-of-capture chime, longer pause tolerance, shorter max; transcription runs under a watchdog timeout with elapsed-time prints. (4) Voice cancel — saying the wake word + "stop" while a task runs terminates the claude subprocess. (5) Lifecycle hardening — SIGINT handler for clean shutdown, per-iteration exception guard with stream re-init. (6) `python -m jarvis.diag` — record/playback/VAD-timeline/transcribe with timings, for tuning thresholds with real data.

**Tech Stack:** existing Jarvis daemon; no new dependencies.

**Git:** User handles all commits — NO commit steps (user rule overrides skill default).

---

### Task 1: Self-trigger suppression — `SPEAKING` event

**Files:**
- Modify: `jarvis/speak.py`
- Modify: `jarvis/jarvis.py` (main loop)
- Test: `tests/test_speak.py` (add 2 tests)

- [ ] **Step 1: Add failing tests to `tests/test_speak.py`**

```python
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
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_speak.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'SPEAKING'`

- [ ] **Step 3: Implement in `jarvis/speak.py`**

Add at top (after imports):

```python
import threading

SPEAKING = threading.Event()  # mic must ignore the speakers while set


def _play(cmd: list[str]) -> None:
    """All speaker output goes through here so the wake loop can gate on it."""
    SPEAKING.set()
    try:
        subprocess.run(cmd, check=False)
    finally:
        SPEAKING.clear()
```

Replace the subprocess calls:
- in `speak()` say-fallback line: `_play(["say", "-v", voice_for(lang), text])`
- in `_neural()`: `_play(["afplay", path])` (replaces `subprocess.run(["afplay", path], check=False)`)
- `chime()`: `_play(["afplay", "-t", "0.6", "/System/Library/Sounds/Glass.aiff"])`

NOTE: `test_say_engine_invokes_say` asserts `subprocess.run(["say", ...], check=False)` — `_play` still calls `subprocess.run(cmd, check=False)` so it keeps passing.

- [ ] **Step 4: Gate the wake loop in `jarvis/jarvis.py`** — in `main()` right after `data, _ = stream.read(n)` add:

```python
        if speak.SPEAKING.is_set():
            wake.reset()  # drop frames of our own voice
            continue
```

- [ ] **Step 5: Run, verify pass**

Run: `uv run pytest tests/test_speak.py -v` → 6 PASS, and `uv run pytest -q` → all PASS.

---

### Task 2: Confidence gate — stop hijacking ambient speech (`jarvis/quality.py`)

**Files:**
- Create: `jarvis/quality.py`
- Create: `tests/test_quality.py`
- Modify: `jarvis/transcribe.py` (return confidence)
- Modify: `jarvis/jarvis.py` (use the gate)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_quality.py
from jarvis.quality import accept


def test_explicit_wake_accepts_short_commands():
    assert accept("run the tests", lang_prob=0.9, woke=True)
    assert accept("hello", lang_prob=0.4, woke=True)  # wake = user meant it


def test_followup_requires_confidence_and_length():
    assert not accept("you", lang_prob=0.9, woke=False)          # too short
    assert not accept("so anyway whatever", lang_prob=0.3, woke=False)  # low conf
    assert accept("now rename the file to final", lang_prob=0.8, woke=False)


def test_empty_never_accepted():
    assert not accept("", lang_prob=0.99, woke=True)
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_quality.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `jarvis/quality.py`**

```python
MIN_FOLLOWUP_WORDS = 3
MIN_FOLLOWUP_LANG_PROB = 0.5


def accept(text: str, lang_prob: float, woke: bool) -> bool:
    """Is this transcription a command the user actually meant?

    Explicit wake = strong intent, accept almost anything.
    Follow-up window = mic was opened on our initiative; demand more evidence
    so ambient speech doesn't become an accidental task.
    """
    if not text.strip():
        return False
    if woke:
        return True
    words = len(text.split())
    return words >= MIN_FOLLOWUP_WORDS and lang_prob >= MIN_FOLLOWUP_LANG_PROB
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_quality.py -v` → 3 PASS

- [ ] **Step 5: Return confidence from `jarvis/transcribe.py`** — replace `transcribe()`:

```python
    def transcribe(self, audio: np.ndarray) -> tuple[str, str, float]:
        """int16 mono 16kHz -> (text, language_code, language_probability)."""
        f32 = audio.astype(np.float32) / 32768.0
        segments, info = self.model.transcribe(f32, beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, info.language, float(info.language_probability)
```

and in `_main()` update: `text, lang, prob = Transcriber().transcribe(audio)` and `print(f"[{lang} {prob:.2f}] {text}")`.

- [ ] **Step 6: Use the gate in `jarvis/jarvis.py` `handle_command`** — replace the transcribe block:

```python
    BUS.set_state("transcribing")
    text, lang, prob = stt.transcribe(audio)
    lang = lang if lang in CONFIG.voices else "en"
    if not accept(text, prob, woke):
        if woke:
            speak.phrase("didnt_catch", lang)
        print(f"(rejected: '{text[:40]}' prob={prob:.2f} woke={woke})", flush=True)
        BUS.set_state("idle")
        return None
```

with import `from .quality import accept` at the top.

- [ ] **Step 7: Run full suite**

Run: `uv run pytest -q` → all PASS.

---

### Task 3: Recording UX — end chime, pause tolerance, live feedback

**Files:**
- Modify: `jarvis/config.py` (tuning values)
- Modify: `jarvis/speak.py` (end chime)
- Modify: `jarvis/jarvis.py` (use it + prints)

- [ ] **Step 1: Tune `jarvis/config.py` recording block** — replace values:

```python
    # recording
    vad_aggressiveness: int = 2             # 0-3, higher = stricter speech detection
    silence_stop_s: float = 1.8             # pause tolerance before cut (was 1.2 — cut users mid-thought)
    max_command_s: float = 20.0             # whisper-on-CPU stays fast enough
    min_command_s: float = 0.4
    no_speech_timeout_s: float = 5.0
```

- [ ] **Step 2: Add end chime to `jarvis/speak.py`**

```python
def chime_end() -> None:
    """Distinct short sound: 'got it, stopped recording'."""
    _play(["afplay", "-t", "0.4", "/System/Library/Sounds/Tink.aiff"])
```

- [ ] **Step 3: Use in `jarvis/jarvis.py` `handle_command`** — right after `audio = record_command(rec)` (before the None check) add:

```python
    if audio is not None:
        speak.chime_end()
        print(f"(captured {len(audio) / CONFIG.sample_rate:.1f}s)", flush=True)
```

- [ ] **Step 4: Verify**

Run: `uv run pytest -q` → all PASS. Live: wake → speak → hear Tink when it stops listening; pausing ~1.5s mid-sentence no longer cuts you off.

---

### Task 4: Transcription watchdog + elapsed feedback

**Files:**
- Modify: `jarvis/config.py` (timeout)
- Modify: `jarvis/jarvis.py` (watchdog)

- [ ] **Step 1: Config** — add to the whisper block of `jarvis/config.py`:

```python
    transcribe_timeout_s: float = 45.0
```

- [ ] **Step 2: Watchdog in `jarvis/jarvis.py`** — add imports:

```python
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
```

module-level: `_STT_POOL = ThreadPoolExecutor(max_workers=1)`

In `handle_command`, replace the direct call `text, lang, prob = stt.transcribe(audio)` with:

```python
    t0 = time.monotonic()
    future = _STT_POOL.submit(stt.transcribe, audio)
    try:
        text, lang, prob = future.result(timeout=CONFIG.transcribe_timeout_s)
    except FutureTimeout:
        print("(transcription timed out)", flush=True)
        speak.phrase("didnt_catch", "en")
        BUS.set_state("idle")
        return None
    print(f"(transcribed in {time.monotonic() - t0:.1f}s)", flush=True)
```

with `import time` at top.

- [ ] **Step 3: Verify**

Run: `uv run pytest -q` → all PASS; `uv run python -c "import ast; ast.parse(open('jarvis/jarvis.py').read()); print('OK')"` → OK.

---

### Task 5: Voice cancel — "Hey Jarvis, stop"

**Files:**
- Modify: `jarvis/dispatch.py` (expose the subprocess)
- Modify: `jarvis/jarvis.py` (cancel path)
- Modify: `jarvis/speak.py` (phrase)
- Test: `tests/test_dispatch.py` (on_proc callback)

- [ ] **Step 1: Add failing test to `tests/test_dispatch.py`**

```python
def test_run_task_on_proc_callback(monkeypatch):
    import jarvis.dispatch as d

    class FakeProc:
        stdout = iter(())
        stderr = None
        returncode = 0
        def wait(self):
            return 0

    captured = []
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: FakeProc())
    d.run_task("x", on_proc=captured.append)
    assert isinstance(captured[0], FakeProc)
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: FAIL — unexpected keyword `on_proc`

- [ ] **Step 3: Implement in `jarvis/dispatch.py`** — `run_task` signature:

```python
def run_task(task: str, session_id: str | None = None, model: str = "",
             on_proc=None) -> tuple[str, str, bool, str | None]:
```

after the `proc = subprocess.Popen(...)` line add:

```python
    if on_proc:
        on_proc(proc)
```

(`FakeProc.stdout` is an empty iterator, so the read loop and `assert proc.stdout is not None` must tolerate it — change `assert proc.stdout is not None` to `if proc.stdout is not None:` wrapping the for-loop.)

- [ ] **Step 4: Phrases in `jarvis/speak.py` PHRASES dict** — add:

```python
    "cancelled": {"he": "ביטלתי את המשימה", "en": "Task cancelled"},
```

- [ ] **Step 5: Cancel path in `jarvis/jarvis.py`**

`Conversation` gains: `self.proc = None` in `__init__`.

`dispatch_async` run_task call becomes:

```python
        clean, spoken, ok, sess = run_task(
            text, convo.session_id, model,
            on_proc=lambda p: setattr(convo, "proc", p))
```

`RESET_PHRASES` line gains a sibling:

```python
CANCEL_WORDS = {"stop", "cancel", "עצור", "תעצור", "בטל"}
```

In `main()`, replace the busy branch:

```python
        if task_thread and task_thread.is_alive():
            if not woke:
                continue
            stream.stop()
            speak.chime()
            audio = record_command(rec)
            cancelled = False
            if audio is not None:
                future = _STT_POOL.submit(stt.transcribe, audio)
                try:
                    text, _, _ = future.result(timeout=CONFIG.transcribe_timeout_s)
                except FutureTimeout:
                    text = ""
                if any(w in text.lower().split() for w in CANCEL_WORDS):
                    cancelled = True
            if cancelled and convo.proc and convo.proc.poll() is None:
                convo.proc.terminate()
                speak.phrase("cancelled", "en")
                print("(task cancelled by voice)", flush=True)
            else:
                speak.phrase("working", "en")
            wake.reset()
            stream.start()
            continue
```

- [ ] **Step 6: Run, verify pass**

Run: `uv run pytest -q` → all PASS. Live: start a long task, say "Hey Jarvis" → chime → "stop" → "Task cancelled".

---

### Task 6: Lifecycle hardening — clean Ctrl-C + crash-proof loop

**Files:**
- Modify: `jarvis/jarvis.py` (signal handler + iteration guard)

- [ ] **Step 1: Implement** — add `import signal` at top. In `main()` before the stream setup:

```python
    running = {"on": True}

    def _shutdown(*_):
        running["on"] = False
        print("\nshutting down…", flush=True)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
```

Change `while True:` to `while running["on"]:` and wrap the loop body:

```python
    while running["on"]:
        try:
            data, _ = stream.read(n)
            ...entire existing body...
        except sd.PortAudioError as e:
            print(f"(audio error: {e} — reopening mic)", flush=True)
            try:
                stream.close()
            except Exception:
                pass
            stream = sd.InputStream(samplerate=CONFIG.sample_rate, channels=1,
                                    dtype="int16", blocksize=n)
            stream.start()
        except Exception as e:  # never die mid-conversation
            print(f"(recovered from: {type(e).__name__}: {e})", flush=True)
            BUS.set_state("idle")
    stream.stop()
    print("bye")
```

- [ ] **Step 2: Verify**

Run: `uv run pytest -q` → all PASS. Live: `./run.sh`, Ctrl-C → prints "shutting down… bye", NO traceback.

---

### Task 7: Diagnostic tool (`jarvis/diag.py`)

**Files:**
- Create: `jarvis/diag.py`

- [ ] **Step 1: Implement**

```python
"""Voice pipeline diagnostics: uv run python -m jarvis.diag

Records 5s, plays it back, prints a VAD timeline, transcribes with timings.
Use this to tune wake_threshold / vad_aggressiveness / silence_stop_s with
real data from YOUR mic and room.
"""
import time
import wave

import numpy as np
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
```

- [ ] **Step 2: Verify (manual)**

Run: `uv run python -m jarvis.diag` → speak during the 5s; expect playback, a VAD bar with █ where you spoke, transcription with confidence + timing.

---

### Task 8: Final E2E + docs

**Files:**
- Modify: `README.md` (troubleshooting section)

- [ ] **Step 1: README append**

```markdown
## Troubleshooting voice

- `uv run python -m jarvis.wake` — live wake-word scores; set `wake_threshold` just below your scores.
- `uv run python -m jarvis.diag` — record/playback + VAD timeline + transcription timing.
- Jarvis hears himself? `speak.SPEAKING` gating should prevent it — check speakers aren't on max with mic gain high.
- Cut off mid-sentence? Raise `silence_stop_s`. Accidental commands after answers? The follow-up gate needs 3+ words at ≥0.5 confidence — raise either in `jarvis/quality.py`.
- Cancel a running task: "Hey Jarvis" → "stop".
```

- [ ] **Step 2: Verification script**

1. `uv run pytest -q` → all PASS.
2. `./run.sh` → "Jarvis online" does NOT trigger a wake (no instant `WAKE — listening...`).
3. Wake → speak with a 1.5s mid-sentence pause → not cut off; Tink chime when capture ends.
4. While Jarvis speaks a long answer, his own voice never wakes him.
5. After the answer, stay silent → "(heard nothing…)" → idle; mumble two words → rejected, not dispatched.
6. Long task → "Hey Jarvis" → "stop" → "Task cancelled".
7. Ctrl-C → "shutting down… bye", no traceback.

---

## Risks / notes

- The cancel path runs whisper while a task is live — CPU spike acceptable; the alternative (keyword-spotting model) is v3.
- `language_probability` is a proxy for "was this clear speech"; if it over-rejects Hebrew follow-ups, lower `MIN_FOLLOWUP_LANG_PROB` to 0.4 (tune with `jarvis.diag`).
- SIGINT during `stream.read` exits within ~80ms; during a claude task the worker is daemon — process exits, claude child gets orphaned then reaped; acceptable.

## Self-review notes

- Defect→task mapping: self-trigger→T1, ambient hijack→T2, mid-sentence cut→T3, no feedback→T3+T4, no cancel→T5, ugly crashes→T6, "tune it for my voice/room"→T7.
- Type consistency: `transcribe()` returns 3-tuple — updated in transcribe.py `_main`, jarvis.py handle_command, busy-branch cancel, diag.py; `accept(text, lang_prob, woke)` matches quality.py; `_play` keeps `subprocess.run(cmd, check=False)` signature so existing speak tests pass; `run_task(..., on_proc=)` matches dispatch test.
- No placeholders.
