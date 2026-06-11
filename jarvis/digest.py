import json
import threading
import time
from datetime import datetime

from . import speak
from .config import CONFIG
from .events import BUS


def compose_digest(fleet_msg: str | None, reports_msg: str | None) -> str:
    if not fleet_msg:
        return ""
    agents = json.loads(fleet_msg).get("agents", [])
    disabled = sum(1 for a in agents if not a.get("enabled"))
    parts = [f"Fleet status: {len(agents)} agents, {disabled} disabled."]
    if reports_msg:
        fails = [r for r in json.loads(reports_msg).get("reports", [])
                 if r.get("status") == "FAIL"]
        for r in fails:
            parts.append(f"{r.get('agent', '?')} failed: {r.get('summary', '')[:60]}.")
        if not fails:
            parts.append("No failures reported.")
    return " ".join(parts)


def start_digest() -> None:
    def loop():
        spoken_on = ""
        while True:
            now = datetime.now()
            stamp = now.strftime("%Y-%m-%d")
            if now.strftime("%H:%M") >= CONFIG.digest_time and spoken_on != stamp \
                    and BUS.state == "idle":
                text = compose_digest(BUS.sticky.get("fleet"),
                                      BUS.sticky.get("reports"))
                if text:
                    speak.speak(text, "en")
                spoken_on = stamp
            time.sleep(30)

    threading.Thread(target=loop, daemon=True, name="jarvis-digest").start()
