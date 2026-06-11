import shutil
import signal
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import sounddevice as sd

warnings.filterwarnings("ignore", category=RuntimeWarning,
                        module="faster_whisper.feature_extractor")

from . import speak
from .config import CONFIG
from .digest import start_digest
from .dispatch import run_task
from .events import BUS
from .fleet import start_fleet_monitor
from .manager import MANAGER
from .quality import accept
from .recorder import FRAME_SAMPLES, Recorder
from .reports import start_reports_monitor
from .routing import classify
from .server import show_hud, start_server
from .transcribe import Transcriber
from .wake import WakeDetector

RESET_PHRASES = ("new conversation", "new chat", "שיחה חדשה")
CANCEL_WORDS = {"stop", "cancel", "עצור", "תעצור", "בטל"}
HEARING_LOG = CONFIG.working_dir / "hearing-log.tsv"


def log_hearing(verdict: str, text: str, conf: float, woke: bool) -> None:
    try:
        with open(HEARING_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')}\t{verdict}\t{conf:.2f}\t"
                    f"{woke}\t{text[:80]}\n")
    except OSError:
        pass

_STT_POOL = ThreadPoolExecutor(max_workers=1)


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


class Conversation:
    """Claude session continuity + the follow-up window after each answer."""

    def __init__(self):
        self.session_id: str | None = None
        self.followup = threading.Event()  # set when an answer finished speaking
        self.proc = None                   # live claude subprocess (for cancel)

    def maybe_reset(self, text: str) -> None:
        if any(p in text.lower() for p in RESET_PHRASES):
            self.session_id = None


def dispatch_async(text: str, lang: str, convo: Conversation,
                   model: str = "") -> threading.Thread:
    task_id = f"task-{int(time.time())}"
    MANAGER.local_started(task_id, text)

    def work():
        clean, spoken, ok, sess = run_task(
            text, convo.session_id, model,
            on_proc=lambda p: setattr(convo, "proc", p))
        convo.session_id = sess
        MANAGER.local_finished(task_id, ok, spoken or clean[:120])
        BUS.emit("answer", text=clean, spoken=spoken, ok=ok)
        BUS.set_state("speaking")
        if spoken:
            speak.speak(spoken, lang)
        elif not ok:
            speak.phrase("failed", lang)
        convo.followup.set()  # main loop opens the mic for a follow-up

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


def transcribe_guarded(stt: Transcriber, audio) -> tuple[str, str, float] | None:
    """Transcribe under a watchdog so a wedged model never freezes the loop."""
    t0 = time.monotonic()
    future = _STT_POOL.submit(stt.transcribe, audio)
    try:
        text, lang, prob = future.result(timeout=CONFIG.transcribe_timeout_s)
    except FutureTimeout:
        print("(transcription timed out)", flush=True)
        return None
    print(f"(transcribed in {time.monotonic() - t0:.1f}s)", flush=True)
    return text, lang, prob


def handle_command(rec: Recorder, stt: Transcriber, convo: Conversation,
                   woke: bool) -> threading.Thread | None:
    """One listen->transcribe->dispatch exchange. Returns the task thread."""
    BUS.set_state("listening")
    audio = record_command(rec)
    if audio is None:
        if woke:  # silence after explicit wake deserves feedback; after an
            speak.phrase("didnt_catch", "en")  # answer it just ends the convo
        print("(heard nothing — back to idle, say 'Hey Jarvis')", flush=True)
        BUS.set_state("idle")
        return None
    speak.chime_end()
    print(f"(captured {len(audio) / CONFIG.sample_rate:.1f}s)", flush=True)
    BUS.set_state("transcribing")
    result = transcribe_guarded(stt, audio)
    if result is None:
        speak.phrase("didnt_catch", "en")
        BUS.set_state("idle")
        return None
    text, lang, conf = result
    lang = lang if lang in CONFIG.voices else "en"
    if not accept(text, conf, woke):
        if woke:
            speak.phrase("didnt_catch", lang)
        log_hearing("rej", text, conf, woke)
        print(f"(rejected: '{text[:40]}' conf={conf:.2f} woke={woke})", flush=True)
        BUS.set_state("idle")
        return None
    log_hearing("ok", text, conf, woke)
    print(f"[{lang}] {text}")
    convo.maybe_reset(text)
    BUS.emit("transcript", text=text, lang=lang)
    BUS.set_state("working")
    speak.phrase("on_it", lang)
    model = CONFIG.chat_model if classify(text) == "chat" else CONFIG.work_model
    return dispatch_async(text, lang, convo, model)


def handle_busy_wake(rec: Recorder, stt: Transcriber, convo: Conversation) -> None:
    """Wake during a running task: listen briefly — 'stop' cancels it."""
    speak.chime()
    audio = record_command(rec)
    text = ""
    if audio is not None:
        result = transcribe_guarded(stt, audio)
        text = result[0] if result else ""
    if any(w in text.lower().split() for w in CANCEL_WORDS):
        if convo.proc and convo.proc.poll() is None:
            convo.proc.terminate()
        speak.phrase("cancelled", "en")
        print("(task cancelled by voice)", flush=True)
    else:
        speak.phrase("working", "en")


def main() -> None:
    startup_checks()
    start_server()
    start_fleet_monitor()
    start_reports_monitor()
    start_digest()
    print(f"HUD: http://localhost:{CONFIG.port}")
    print("Loading models (first run downloads them)...")
    wake, rec, stt = WakeDetector(), Recorder(), Transcriber()
    convo = Conversation()
    task_thread: threading.Thread | None = None
    BUS.set_state("idle")
    speak.warm_phrase_cache()
    speak.phrase("ready", "en")
    print("Ready. Say 'Hey Jarvis'.")

    running = {"on": True}

    def _shutdown(*_):
        running["on"] = False
        print("\nshutting down…", flush=True)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    n = CONFIG.wake_frame_samples

    def open_stream():
        s = sd.InputStream(samplerate=CONFIG.sample_rate, channels=1,
                           dtype="int16", blocksize=n)
        s.start()
        return s

    stream = open_stream()
    while running["on"]:
        try:
            data, _ = stream.read(n)
            if speak.SPEAKING.is_set():
                wake.reset()  # drop frames of our own voice
                continue
            woke = wake.detect(data[:, 0])
            followup = convo.followup.is_set()
            if not woke and not followup:
                continue
            if task_thread and task_thread.is_alive():
                if woke:
                    stream.stop()
                    handle_busy_wake(rec, stt, convo)
                    wake.reset()
                    stream.start()
                continue
            convo.followup.clear()
            if woke and CONFIG.open_hud_on_wake:
                show_hud()
            print("WAKE — listening..." if woke else "follow-up — listening...",
                  flush=True)
            # hand the mic to the recorder; restart afterwards so the wake
            # detector never digests minutes of stale buffered audio
            stream.stop()
            speak.chime()
            task_thread = handle_command(rec, stt, convo, woke) or task_thread
            wake.reset()
            stream.start()
        except sd.PortAudioError as e:
            print(f"(audio error: {e} — reopening mic)", flush=True)
            try:
                stream.close()
            except Exception:
                pass
            stream = open_stream()
        except Exception as e:  # never die mid-conversation
            print(f"(recovered from: {type(e).__name__}: {e})", flush=True)
            BUS.set_state("idle")
    stream.stop()
    print("bye")


if __name__ == "__main__":
    main()
