import json
import subprocess

from .config import CONFIG
from .events import BUS

SPOKEN_TAG = "SPOKEN:"
PROMPT_SUFFIX = (
    f"\n\nIMPORTANT: End your final answer with a line starting with '{SPOKEN_TAG} ' "
    "followed by what you would SAY out loud — natural, warm, conversational, like a "
    "sharp human assistant (1-3 short sentences, same language as the task; Hebrew "
    "task → Hebrew answer). Never read lists, paths, or code aloud; tell the outcome "
    "the way a person would, e.g. 'Done — the file is ready and tests pass.'"
)


def build_cmd(task: str, session_id: str | None = None,
              model: str = "") -> list[str]:
    cmd = ["claude", "-p", task + PROMPT_SUFFIX,
           "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
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
                       "text": obj.get("result") or "",
                       "session": obj.get("session_id")})
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


def run_task(task: str, session_id: str | None = None, model: str = "",
             on_proc=None) -> tuple[str, str, bool, str | None]:
    """Run claude headless, stream agent events to BUS.

    Returns (text, spoken, ok, session_id) — session_id feeds the next
    --resume call so the conversation continues across voice commands.
    on_proc receives the live subprocess (voice-cancel needs the handle).
    """
    CONFIG.working_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(build_cmd(task, session_id, model), cwd=CONFIG.working_dir,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if on_proc:
        on_proc(proc)
    full, ok, sess = "", False, session_id
    for line in proc.stdout or ():
        for ev in parse_line(line):
            if ev["kind"] == "tool":
                BUS.emit("agent_event", name=ev["name"], detail=ev["detail"])
            elif ev["kind"] == "text":
                BUS.emit("agent_event", name="jarvis", detail=ev["text"][:200])
            else:
                full, ok = ev["text"], ev["ok"]
                sess = ev.get("session") or sess
    proc.wait()
    if proc.returncode != 0 and not full:
        err = (proc.stderr.read() if proc.stderr else "")[:500]
        BUS.emit("error", message=err or f"claude exited {proc.returncode}")
        return "", "", False, sess
    clean, spoken = extract_spoken(full)
    return clean, spoken, ok, sess
