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
        for msg in BUS.sticky.values():  # e.g. last fleet snapshot
            await websocket.send_text(msg)
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


_FOCUS_SCRIPT = """
tell application "Google Chrome"
    activate
    set found to false
    repeat with w in windows
        set i to 1
        repeat with t in tabs of w
            if URL of t contains "localhost:{port}" then
                set active tab index of w to i
                set index of w to 1
                set found to true
                exit repeat
            end if
            set i to i + 1
        end repeat
        if found then exit repeat
    end repeat
    if not found then open location "http://localhost:{port}"
end tell
"""


def show_hud() -> None:
    """Bring the HUD browser tab to the front (focus existing tab, else open one)."""
    import subprocess

    def run():
        url = f"http://localhost:{CONFIG.port}"
        script = _FOCUS_SCRIPT.format(port=CONFIG.port)
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, timeout=5)
        if res.returncode != 0:  # Chrome missing/not scriptable -> default browser
            subprocess.run(["open", url], check=False)

    threading.Thread(target=run, daemon=True, name="jarvis-show-hud").start()
