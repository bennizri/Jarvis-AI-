# Jarvis Fleet Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Jarvis from a single voice agent into the commander of a fleet of up to ~30 cloud agents (claude.ai routines): create, monitor, and control them by voice, see live fleet status + agent reports in the HUD, get proactive spoken alerts on failures, and a daily spoken digest.

**Architecture:** Three planes. **Control plane** — Jarvis's inner Claude uses the `RemoteTrigger` tool (list/create/update/run) driven by voice; conventions in `workspace/CLAUDE.md` make every created agent standardized. **Data plane** — cloud agents can't push to the Mac, so every agent emails a report to the user's inbox with subject `[JARVIS] <agent-name> <OK|WARN|FAIL>`; the daemon polls Gmail (through a cheap headless claude call) and turns reports into HUD events + spoken alerts. **State plane** — `workspace/fleet-registry.json` written by the inner Claude on every create/update (purpose, repo, schedule), merged with the live RemoteTrigger list by the daemon's fleet poller and pushed to the HUD over the existing event bus.

**Tech Stack:** existing Jarvis daemon (Python 3.12/uv, FastAPI WS, vanilla-JS HUD), `claude` CLI headless as the only gateway to claude.ai APIs (RemoteTrigger + Gmail MCP), haiku model for cheap polls.

**Git:** User handles all commits — NO commit steps in this plan (user rule overrides skill default).

**Existing modules this builds on:** `jarvis/config.py` (CONFIG), `jarvis/events.py` (BUS, STICKY_TYPES), `jarvis/fleet.py` (v1 poll), `jarvis/server.py`, `jarvis/jarvis.py`, `ui/*`, `workspace/CLAUDE.md`.

---

## Phase 0 — manual prerequisite (user, one-time)

- [ ] **GitHub re-auth:** claude.ai → Settings → connected apps → GitHub → authorize, grant access to `idanizri/HIApply` (and any repo future agents will use). Until then, every cloud run on that repo fails with `github_repo_access_denied`.
- [ ] **Verify:** in this repo run `claude -p "Use RemoteTrigger action run with trigger_id trig_017sefGH6wDbnWxK7kNodXeE and report the result" --output-format json` → result should NOT contain `github_repo_access_denied`.

---

### Task 1: Shared headless-claude JSON helper (`jarvis/cli.py`)

Both fleet polling and report polling shell out to `claude -p` and need "give me ONLY a JSON array" parsing. One helper, DRY.

**Files:**
- Create: `jarvis/cli.py`
- Create: `tests/test_cli.py`
- Modify: `jarvis/fleet.py` (rewritten in Task 2 to use it)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py
import json

from jarvis.cli import parse_json_array


def wrap(result: str) -> str:
    return json.dumps({"type": "result", "result": result})


def test_parse_plain_array():
    items = [{"a": 1}]
    assert parse_json_array(wrap(json.dumps(items))) == items


def test_parse_fenced_array():
    items = [{"a": 1}]
    fenced = "```json\n" + json.dumps(items) + "\n```"
    assert parse_json_array(wrap(fenced)) == items


def test_parse_empty():
    assert parse_json_array(wrap("[]")) == []


def test_parse_garbage_returns_none():
    assert parse_json_array("not json") is None
    assert parse_json_array(wrap("sorry, no tool")) is None
    assert parse_json_array(wrap('{"not": "list"}')) is None
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.cli'`

- [ ] **Step 3: Implement `jarvis/cli.py`**

```python
import json
import subprocess

from .config import CONFIG


def parse_json_array(stdout: str) -> list | None:
    """claude --output-format json stdout -> list, None if unparseable."""
    try:
        result = json.loads(stdout).get("result", "")
    except json.JSONDecodeError:
        return None
    text = result.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


def run_json_prompt(prompt: str, timeout: int = 180) -> list | None:
    """Headless claude call (cheap model) that must answer with a JSON array."""
    try:
        res = subprocess.run(
            ["claude", "-p", prompt, "--model", CONFIG.fleet_model,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
            cwd=CONFIG.working_dir)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return parse_json_array(res.stdout) if res.returncode == 0 else None
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 4 PASS

---

### Task 2: Fleet poll v2 — ids + registry merge (`jarvis/fleet.py` rewrite)

**Files:**
- Modify: `jarvis/fleet.py` (full replacement below)
- Modify: `tests/test_fleet.py` (full replacement below)

- [ ] **Step 1: Replace `tests/test_fleet.py`**

```python
import json

from jarvis.fleet import merge_registry


def test_merge_adds_purpose_from_registry():
    agents = [{"id": "trig_1", "name": "A", "enabled": True,
               "cron": "0 9 * * *", "next_run_at": ""}]
    registry = {"trig_1": {"purpose": "daily code review", "repo": "org/x"}}
    merged = merge_registry(agents, registry)
    assert merged[0]["purpose"] == "daily code review"


def test_merge_unknown_agent_gets_empty_purpose():
    agents = [{"id": "trig_2", "name": "B"}]
    assert merge_registry(agents, {})[0]["purpose"] == ""


def test_merge_handles_missing_id():
    agents = [{"name": "no-id"}]
    assert merge_registry(agents, {"x": {"purpose": "p"}})[0]["purpose"] == ""
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_fleet.py -v`
Expected: FAIL — `ImportError: cannot import name 'merge_registry'`

- [ ] **Step 3: Replace `jarvis/fleet.py`**

```python
import json
import threading
import time

from .cli import run_json_prompt
from .config import CONFIG
from .events import BUS

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
            time.sleep(CONFIG.fleet_poll_s)

    threading.Thread(target=loop, daemon=True, name="jarvis-fleet").start()
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_fleet.py tests/test_cli.py -v`
Expected: 7 PASS

- [ ] **Step 5: Live check (real claude call, ~30-60s)**

Run: `uv run python -c "from jarvis.fleet import fetch_fleet; print(fetch_fleet())"`
Expected: list containing `HIApply daily agent` with its `id` (`trig_017sefGH6wDbnWxK7kNodXeE`), or `None` if claude/network unavailable (then debug before continuing).

---

### Task 3: Agent reports inbox poll (`jarvis/reports.py`)

Cloud agents email reports (convention enforced in Task 7). The daemon polls Gmail through headless claude + Gmail MCP, dedupes, and emits `report` events; new FAILs get spoken when Jarvis is idle.

**Files:**
- Create: `jarvis/reports.py`
- Create: `tests/test_reports.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reports.py
from jarvis.reports import diff_new

OLD = [{"agent": "hiapply", "status": "OK", "summary": "all good",
        "msg_id": "m1"}]


def test_diff_new_returns_only_unseen():
    new = OLD + [{"agent": "leads", "status": "FAIL", "summary": "crash",
                  "msg_id": "m2"}]
    fresh = diff_new(new, {"m1"})
    assert [r["msg_id"] for r in fresh] == ["m2"]


def test_diff_new_handles_missing_msg_id():
    fresh = diff_new([{"agent": "x", "status": "OK", "summary": ""}], set())
    assert fresh == []  # no msg_id -> can't dedupe -> drop


def test_diff_new_empty():
    assert diff_new([], {"m1"}) == []
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_reports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.reports'`

- [ ] **Step 3: Implement `jarvis/reports.py`**

```python
import threading
import time

from . import speak
from .cli import run_json_prompt
from .config import CONFIG
from .events import BUS

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
                for r in fresh:
                    if r.get("status") == "FAIL" and BUS.state == "idle" \
                            and CONFIG.speak_failures:
                        speak.speak(f"Agent {r.get('agent', '?')} failed: "
                                    f"{r.get('summary', '')[:80]}", "en")
            time.sleep(CONFIG.reports_poll_s)

    threading.Thread(target=loop, daemon=True, name="jarvis-reports").start()
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_reports.py -v`
Expected: 3 PASS

- [ ] **Step 5: Verify Gmail MCP is reachable from headless claude**

Run: `claude -p "List my Gmail labels. Answer with just the count." --model haiku --output-format json | head -c 400`
Expected: a result mentioning a number. **If it errors with "no such tool": headless runs can't see claude.ai-connected MCPs — STOP and record this in the plan; fallback is Drive-file reports (agents write `jarvis-reports/<name>.md` to Drive, poll via Drive MCP locally or skip Phase 3 and rely on the claude.ai routines page).** This is the single biggest external risk of the plan.

---

### Task 4: Config + sticky events for fleet/reports

**Files:**
- Modify: `jarvis/config.py`
- Modify: `jarvis/events.py:6` (STICKY_TYPES)
- Test: `tests/test_events.py` (add one test)

- [ ] **Step 1: Add config fields** — in `jarvis/config.py`, replace the fleet block with:

```python
    # fleet (cloud routine monitoring)
    fleet_poll_s: int = 600
    fleet_model: str = "haiku"              # cheap model for status/report polls
    reports_poll_s: int = 300
    speak_failures: bool = True             # announce FAIL reports aloud when idle
    digest_time: str = "09:30"              # daily spoken fleet digest, local time
```

- [ ] **Step 2: Make `reports` sticky** — in `jarvis/events.py` change:

```python
STICKY_TYPES = {"fleet", "reports"}  # replayed to every newly connected client
```

- [ ] **Step 3: Add failing test to `tests/test_events.py`**

```python
def test_sticky_event_cached_for_late_subscribers():
    bus = EventBus()
    bus.emit("fleet", agents=[])  # no loop attached — still cached
    assert json.loads(bus.sticky["fleet"]) == {"type": "fleet", "agents": []}
```

- [ ] **Step 4: Run, verify pass** (implementation already exists from earlier work; this locks it)

Run: `uv run pytest tests/test_events.py -v`
Expected: 5 PASS

---

### Task 5: Daily spoken digest (`jarvis/digest.py`)

**Files:**
- Create: `jarvis/digest.py`
- Create: `tests/test_digest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_digest.py
import json

from jarvis.digest import compose_digest


def test_compose_counts_and_failures():
    fleet_msg = json.dumps({"type": "fleet", "agents": [
        {"name": "A", "enabled": True}, {"name": "B", "enabled": False}]})
    reports_msg = json.dumps({"type": "reports", "reports": [
        {"agent": "A", "status": "FAIL", "summary": "boom"},
        {"agent": "A", "status": "OK", "summary": "fine"}]})
    text = compose_digest(fleet_msg, reports_msg)
    assert "2 agents" in text and "1 disabled" in text and "A failed" in text


def test_compose_no_data():
    assert compose_digest(None, None) == ""
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_digest.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `jarvis/digest.py`**

```python
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
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_digest.py -v`
Expected: 2 PASS

---

### Task 6: Wire monitors into the daemon (`jarvis/jarvis.py`) + allow RemoteTrigger

**Files:**
- Modify: `jarvis/jarvis.py` (imports + `main()` startup block)
- Modify: `jarvis/config.py:26` (allowed_tools)

- [ ] **Step 1: Add tools to the inner Claude's allowlist** — in `jarvis/config.py` replace the `allowed_tools` line with:

```python
    allowed_tools: str = ("Bash Read Edit Write Glob Grep WebSearch WebFetch "
                          "Agent RemoteTrigger ToolSearch")
```

- [ ] **Step 2: Start monitors** — in `jarvis/jarvis.py` add imports:

```python
from .digest import start_digest
from .reports import start_reports_monitor
```

and in `main()` after `start_fleet_monitor()`:

```python
    start_reports_monitor()
    start_digest()
```

- [ ] **Step 3: Verify**

Run: `uv run pytest -q` → all PASS, and `uv run python -c "import ast; ast.parse(open('jarvis/jarvis.py').read()); print('OK')"` → `OK`

---

### Task 7: Agent-factory conventions (`workspace/CLAUDE.md`)

This is what makes 30 agents manageable instead of chaos: every agent Jarvis creates is born standardized.

**Files:**
- Modify: `/Users/bennizri/AI agent/workspace/CLAUDE.md` — replace the `## Agent fleet — you are the commander` section with:

- [ ] **Step 1: Write the section**

```markdown
## Agent fleet — you are the commander
You manage a fleet of cloud agents (claude.ai routines) via the **RemoteTrigger** tool.

### Voice intents
- "status of my agents / מה הסוכנים עושים" → RemoteTrigger list → spoken summary
  (count, enabled, next runs, recent failures from memory/agents.md).
- "create an agent that ..." → factory procedure below.
- "pause / resume / run agent X" → RemoteTrigger update/run (list first, match name).
- Deleting is impossible via API — direct the user to https://claude.ai/code/routines.

### Agent factory — EVERY new agent MUST:
1. **Dedupe:** RemoteTrigger list first; if a routine with the same purpose exists,
   say so and offer update instead of create.
2. **Standard prompt footer** — append to the agent's prompt verbatim:
   "When finished, email a report to admin@mediafuse.org using the Gmail tool.
   Subject: [JARVIS] <agent-name> <OK|WARN|FAIL>. Body: 5-line max summary of what
   you found/did. FAIL only when you could not complete the task."
3. **Attach the Gmail connector** in mcp_connections (uuid 2e583bac-2d99-4578-8a30-74998f0b421a,
   name Gmail, url https://gmailmcp.googleapis.com/mcp/v1).
4. **Default read-only:** unless the user explicitly asks for commits/PRs, the prompt
   must say "Do NOT commit or push."
5. **Preflight:** after create, immediately RemoteTrigger run. If it returns
   github_repo_access_denied, tell the user to re-authorize GitHub at claude.ai
   settings — this is the #1 failure cause. Say it plainly.
6. **Register:** update `fleet-registry.json` (object keyed by routine id:
   {"purpose": "...", "repo": "...", "schedule_local": "..."}) and append a row to
   `memory/agents.md`. Both live in this directory.
7. **Quota sanity:** if the fleet already has 30+ routines, warn before creating more.
```

- [ ] **Step 2: Verify by voice** — say: "Hey Jarvis, what's the status of my agents?"
Expected: spoken count + names; HUD OUTPUT shows the list.

---

### Task 8: HUD Fleet Command panel v2 + reports feed

**Files:**
- Modify: `ui/index.html` (fleet panel gets a reports feed)
- Modify: `ui/ws.js` (fleet handler shows purpose + report status; new reports handler)
- Modify: `ui/style.css` (status chips)

- [ ] **Step 1: `ui/index.html`** — replace the fleet panel block with:

```html
    <div id="fleet" class="panel">
      <h2>// AGENT FLEET</h2>
      <ul id="fleet-list"><li class="dim">no fleet data yet…</li></ul>
      <h2 style="margin-top:10px">// AGENT REPORTS</h2>
      <ul id="report-list"><li class="dim">no reports yet…</li></ul>
    </div>
```

- [ ] **Step 2: `ui/ws.js`** — replace the existing `window.JARVIS.on("fleet", ...)` block with:

```javascript
window.JARVIS.on("fleet", (m) => {
  const list = document.getElementById("fleet-list");
  list.innerHTML = "";
  if (!m.agents.length) {
    list.innerHTML = '<li class="dim">no cloud agents yet</li>';
    return;
  }
  for (const a of m.agents) {
    const li = document.createElement("li");
    const next = a.next_run_at ? new Date(a.next_run_at).toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
    li.innerHTML = `<span class="agent-dot ${a.enabled ? "on" : "off"}"></span>` +
      `<span class="agent-name"></span>` +
      `<span class="agent-purpose"></span>` +
      `<span class="agent-next">${next}</span>`;
    li.querySelector(".agent-name").textContent = a.name;
    li.querySelector(".agent-purpose").textContent = a.purpose || "";
    list.appendChild(li);
  }
});

window.JARVIS.on("reports", (m) => {
  const list = document.getElementById("report-list");
  list.innerHTML = "";
  if (!m.reports.length) {
    list.innerHTML = '<li class="dim">no reports yet</li>';
    return;
  }
  for (const r of m.reports.slice(0, 12)) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="chip ${r.status}"></span>` +
      `<span class="agent-name"></span> <span class="report-summary"></span>`;
    li.querySelector(".chip").textContent = r.status;
    li.querySelector(".agent-name").textContent = r.agent;
    li.querySelector(".report-summary").textContent = r.summary || "";
    list.appendChild(li);
  }
});
```

- [ ] **Step 3: `ui/style.css`** — append:

```css
#fleet-list .agent-purpose { color: #46707c; font-size: 10px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
#report-list { list-style: none; font-size: 11px; }
#report-list li { padding: 3px 0; border-bottom: 1px dashed #0a3a45; }
#report-list .chip { font-size: 9px; padding: 1px 6px; border-radius: 3px;
  margin-right: 6px; letter-spacing: 1px; }
#report-list .chip.OK { background: #0c3a26; color: var(--green); }
#report-list .chip.WARN { background: #3a2c0c; color: var(--amber); }
#report-list .chip.FAIL { background: #3a0c14; color: var(--red); }
#report-list .report-summary { color: #8fc7d4; }
```

- [ ] **Step 4: Verify** — `uv run pytest tests/test_server.py -v` → 2 PASS. Then restart `./run.sh`: fleet panel shows `HIApply daily agent` with green dot within ~60s of startup (first poll).

---

### Task 9: Scale + docs

**Files:**
- Modify: `README.md` (fleet section)
- Modify: `docs/superpowers/specs/2026-06-11-jarvis-voice-agent-design.md` (append fleet design)

- [ ] **Step 1: README fleet section** — append:

```markdown
## Fleet Command

Jarvis commands a fleet of cloud agents (claude.ai routines):

- "Hey Jarvis, create an agent that reviews HIApply commits every morning"
- "Hey Jarvis, what are my agents doing?"
- "Hey Jarvis, run the HIApply agent now"

Every agent reports by email (`[JARVIS] <name> <OK|WARN|FAIL>`); Jarvis polls the
inbox, shows reports in the HUD, speaks failures aloud, and gives a daily digest
at 09:30 (config `digest_time`). Fleet state lives in `workspace/fleet-registry.json`
+ `workspace/memory/agents.md`. Manage/delete at https://claude.ai/code/routines.
```

- [ ] **Step 2: Final verification**

Run: `uv run pytest -q` → all PASS.
Voice test script:
1. "Hey Jarvis, what's the status of my agents?" → spoken count, HUD fleet panel filled.
2. "Hey Jarvis, run the HIApply agent now" → preflight result spoken (or the GitHub re-auth message if Phase 0 not done).
3. "Hey Jarvis, create an agent that checks <repo> daily at 8am for failing tests" → created with email-report footer, registered, appears in fleet panel ≤10 min, link spoken/shown.
4. Wait for the next agent run → report email arrives → REPORTS feed shows chip; if FAIL, Jarvis announces it.

---

## Risks / open issues

1. **Headless MCP availability (CRITICAL, Task 3 Step 5):** claude.ai-connected MCPs (Gmail) may be absent in `claude -p` runs. If so: switch data plane to Drive files or claude.ai routines page only; the fleet control plane (RemoteTrigger) is unaffected — it already worked headless (it created the HIApply agent).
2. **Poll cost:** fleet (10 min) + reports (5 min) ≈ ~400 haiku calls/day, cheap but nonzero; tune `fleet_poll_s`/`reports_poll_s` in config.
3. **RemoteTrigger API limits:** no delete, no run-history endpoint — that's why email reports exist. Cron min interval 1h.
4. **30-agent UI:** fleet panel scrolls; grouping by repo deferred until it actually hurts.

## Self-review notes

- Spec coverage: control (T6/T7), data (T3/T7 footer), state (T2 registry), HUD (T8), proactive (T3 speak + T5 digest), scale/docs (T9), prereq (Phase 0). 
- Type consistency: `run_json_prompt`/`parse_json_array` (T1) used by fleet (T2) and reports (T3); `BUS.sticky` dict[str,str] consumed by digest (T5) and server replay (already shipped); config fields referenced (T4) match usage in T3/T5.
- No placeholders: every step has full code/commands.
