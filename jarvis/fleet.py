import json
import threading
import time

from .cli import run_json_prompt
from .config import CONFIG
from .events import BUS
from .manager import MANAGER

PROMPT = (
    "Call the RemoteTrigger tool with action list. From the response, output ONLY a "
    "JSON array — no prose, no markdown fence. One object per routine with keys: "
    'id (string), name (string), enabled (bool), cron (string), next_run_at (string). '
    "If the tool is unavailable or the list is empty, output []."
)


def load_registry() -> dict:
    """fleet-registry.json is written by Jarvis's inner Claude on create/update."""
    try:
        return json.loads((CONFIG.working_dir / "fleet-registry.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def merge_registry(agents: list[dict], registry: dict) -> list[dict]:
    for a in agents:
        meta = registry.get(a.get("id") or "", {})
        a["purpose"] = meta.get("purpose", "")
    return agents


def fetch_fleet() -> list[dict] | None:
    agents = run_json_prompt(PROMPT)
    if agents is None:
        return None
    return merge_registry(agents, load_registry())


def start_fleet_monitor() -> None:
    """Background poll: keeps the HUD fleet panel current."""
    def loop():
        while True:
            agents = fetch_fleet()
            if agents is not None:
                BUS.emit("fleet", agents=agents)
                MANAGER.cloud_update(agents)
            time.sleep(CONFIG.fleet_poll_s)

    threading.Thread(target=loop, daemon=True, name="jarvis-fleet").start()
