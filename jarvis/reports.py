import threading
import time

from . import speak
from .cli import run_json_prompt
from .config import CONFIG
from .events import BUS
from .manager import MANAGER

PROMPT = (
    "Use the Gmail tools to search threads with query: subject:[JARVIS] newer_than:2d . "
    "Output ONLY a JSON array — no prose, no markdown fence. One object per message: "
    'msg_id (string, the message id), agent (string — the word after [JARVIS] in the '
    'subject), status (one of "OK","WARN","FAIL" — from the subject), '
    "summary (one short line from the body). Output [] if none or Gmail unavailable."
)


def diff_new(reports: list[dict], seen: set[str]) -> list[dict]:
    return [r for r in reports if r.get("msg_id") and r["msg_id"] not in seen]


def start_reports_monitor() -> None:
    def loop():
        seen: set[str] = set()
        while True:
            reports = run_json_prompt(PROMPT)
            if reports is not None:
                fresh = diff_new(reports, seen)
                seen.update(r["msg_id"] for r in fresh)
                if fresh:
                    BUS.emit("reports", reports=reports)
                    MANAGER.report_update(reports)
                for r in fresh:
                    if r.get("status") == "FAIL" and BUS.state == "idle" \
                            and CONFIG.speak_failures:
                        speak.speak(f"Agent {r.get('agent', '?')} failed: "
                                    f"{r.get('summary', '')[:80]}", "en")
            time.sleep(CONFIG.reports_poll_s)

    threading.Thread(target=loop, daemon=True, name="jarvis-reports").start()
