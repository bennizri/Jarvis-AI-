import asyncio
import json
import threading


STICKY_TYPES = {"fleet", "reports", "agents"}  # replayed to new clients


class EventBus:
    """Thread-safe fan-out from the voice pipeline threads to async WS clients."""

    def __init__(self):
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.state = "idle"
        self.sticky: dict[str, str] = {}

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
        msg = json.dumps({"type": type_, **data}, ensure_ascii=False)
        if type_ in STICKY_TYPES:
            self.sticky[type_] = msg
        if self._loop is None:
            return
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            self._loop.call_soon_threadsafe(q.put_nowait, msg)

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", state=state)


BUS = EventBus()
