import json

from fastapi.testclient import TestClient

from jarvis.events import BUS
from jarvis.server import app


def test_ws_receives_current_state_then_events():
    BUS.sticky.clear()  # other tests may have left sticky events on the global bus
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
