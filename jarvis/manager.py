import threading
import time

from .events import BUS


class AgentManager:
    """One normalized record per agent — local Claude tasks and cloud routines.

    Statuses: running | done | failed | scheduled | paused | needs_attention.
    Every mutation re-emits the sticky 'agents' event so the HUD board and the
    voice layer always read the same truth.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, dict] = {}

    def _emit(self) -> None:
        BUS.emit("agents", agents=self.snapshot())

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(a) for a in self._agents.values()]

    def attention(self) -> list[dict]:
        return [a for a in self.snapshot() if a["status"] == "needs_attention"]

    # ---- local tasks (the inner claude runs) ----
    def local_started(self, task_id: str, description: str) -> None:
        with self._lock:
            self._agents[task_id] = {
                "id": task_id, "kind": "local", "name": description[:60],
                "status": "running", "last_report": "",
                "updated": time.strftime("%H:%M:%S")}
        self._emit()

    def local_finished(self, task_id: str, ok: bool, summary: str) -> None:
        with self._lock:
            a = self._agents.get(task_id)
            if a:
                a["status"] = "done" if ok else "failed"
                a["last_report"] = summary[:120]
                a["updated"] = time.strftime("%H:%M:%S")
        self._emit()

    # ---- cloud routines ----
    def cloud_update(self, routines: list[dict]) -> None:
        with self._lock:
            for r in routines:
                rid = r.get("id") or r.get("name", "?")
                cur = self._agents.get(rid, {})
                status = cur.get("status", "")
                if status != "needs_attention":
                    status = "scheduled" if r.get("enabled") else "paused"
                cur.update({
                    "id": rid, "kind": "cloud", "name": r.get("name", "?"),
                    "status": status, "purpose": r.get("purpose", ""),
                    "next_run_at": r.get("next_run_at", ""),
                    "last_report": cur.get("last_report", ""),
                    "updated": time.strftime("%H:%M:%S")})
                self._agents[rid] = cur
        self._emit()

    def report_update(self, reports: list[dict]) -> None:
        """Newest report per agent wins (callers pass newest-first or full set)."""
        with self._lock:
            latest: dict[str, dict] = {}
            for r in reports:
                latest.setdefault(r.get("agent", ""), r)
            for a in self._agents.values():
                r = latest.get(a["name"])
                if not r:
                    continue
                a["last_report"] = r.get("summary", "")[:120]
                if r.get("status") == "FAIL":
                    a["status"] = "needs_attention"
                elif a["status"] == "needs_attention":
                    a["status"] = "scheduled"
                a["updated"] = time.strftime("%H:%M:%S")
        self._emit()


MANAGER = AgentManager()
