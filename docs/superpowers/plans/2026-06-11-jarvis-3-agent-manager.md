# Jarvis 3.0 — Flawless Hearing + Claude-Style Agent Management Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Make Jarvis hear Hebrew-accented English/Hebrew reliably — never guess wrong languages, never reject good commands, never accept noise. (2) Rebuild agent management the way Claude Code does it: one unified board of every agent (local tasks + cloud routines) with live statuses, an attention queue, and voice as the only control surface.

**Architecture:** **Phase H (hearing):** constrain whisper to he/en with a two-pass language lock; replace the language-probability gate with real transcription confidence (avg_logprob × no-speech); log every accept/reject decision for tuning. **Phase M (management):** an `AgentManager` singleton holds one normalized record per agent — local Claude tasks AND cloud routines — exactly like Claude Code's task list (pending/running/done/failed/needs_attention). Fleet poll, report poll, and local dispatch all write into it; it emits one sticky `agents` event; the HUD renders it as a single ops board; an attention engine flips `needs_attention` on rules (FAIL report, denied repo, task stuck) and speaks up.

**Tech Stack:** existing daemon; no new dependencies (optional later: mlx-whisper for Apple-GPU STT).

**Git:** User handles all commits — NO commit steps.

---

# PHASE H — FLAWLESS HEARING (P0, the current pain)

### Task H1: Language lock — he/en only

**Files:**
- Modify: `jarvis/transcribe.py`

- [ ] **Step 1: Replace `Transcriber.transcribe`**

```python
ALLOWED_LANGS = ("en", "he")


class Transcriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(CONFIG.whisper_model, device="cpu",
                                  compute_type=CONFIG.whisper_compute)

    def _run(self, f32, language=None):
        segments, info = self.model.transcribe(
            f32, beam_size=1, vad_filter=True, language=language)
        return list(segments), info

    def transcribe(self, audio: np.ndarray) -> tuple[str, str, float]:
        """int16 mono 16kHz -> (text, language_code, confidence 0..1).

        Language is locked to ALLOWED_LANGS: if whisper free-detects anything
        else (accents confuse it), re-run forced to the likelier allowed one.
        Confidence = mean token probability damped by no-speech probability —
        a transcription-quality signal, NOT language certainty.
        """
        import math
        f32 = audio.astype(np.float32) / 32768.0
        segs, info = self._run(f32)
        lang = info.language
        if lang not in ALLOWED_LANGS:
            probs = dict(info.all_language_probs or [])
            lang = max(ALLOWED_LANGS, key=lambda l: probs.get(l, 0.0))
            segs, info = self._run(f32, language=lang)
        text = " ".join(s.text.strip() for s in segs).strip()
        if not segs:
            return "", lang, 0.0
        conf = sum(math.exp(s.avg_logprob) for s in segs) / len(segs)
        nospeech = max(s.no_speech_prob for s in segs)
        return text, lang, conf * (1.0 - nospeech)
```

- [ ] **Step 2: Verify with generated speech**

Run:
```bash
say -v Carmit -o /tmp/he.wav --data-format=LEI16@16000 "תבדוק מה קורה עם הסוכן של היי אפלאי"
uv run python -m jarvis.transcribe /tmp/he.wav
```
Expected: `[he 0.xx] ...` — language `he`, confidence printed; NEVER `pt`/`es`/etc.

### Task H2: Confidence gate on the right signal

**Files:**
- Modify: `jarvis/quality.py` (full replacement)
- Modify: `tests/test_quality.py` (full replacement)

- [ ] **Step 1: Replace `tests/test_quality.py`**

```python
from jarvis.quality import accept


def test_wake_accepts_decent_confidence():
    assert accept("did you finish the task", conf=0.5, woke=True)
    assert accept("hello", conf=0.3, woke=True)


def test_wake_rejects_pure_noise():
    assert not accept("Aí me está me vindo a ti", conf=0.08, woke=True)
    assert not accept("", conf=0.9, woke=True)


def test_followup_moderate_bar():
    assert accept("did you finish the task for high apply", conf=0.4, woke=False)
    assert not accept("you", conf=0.9, woke=False)            # too short
    assert not accept("so anyway whatever then", conf=0.15, woke=False)  # noise
```

- [ ] **Step 2: Replace `jarvis/quality.py`**

```python
MIN_WAKE_CONF = 0.12        # explicit wake = strong intent, low bar
MIN_FOLLOWUP_CONF = 0.30    # mic opened on our initiative, higher bar
MIN_FOLLOWUP_WORDS = 3


def accept(text: str, conf: float, woke: bool) -> bool:
    """Is this transcription a command the user actually meant?

    conf is transcription quality (mean token prob × no-speech damping) from
    Transcriber.transcribe — NOT language certainty, which punishes accents.
    """
    if not text.strip():
        return False
    if woke:
        return conf >= MIN_WAKE_CONF
    return len(text.split()) >= MIN_FOLLOWUP_WORDS and conf >= MIN_FOLLOWUP_CONF
```

- [ ] **Step 3: Update call sites** — `jarvis/jarvis.py` already passes `(text, prob, woke)`; rename local var `prob` → `conf` in `handle_command` for clarity (mechanical).

- [ ] **Step 4: Run** `uv run pytest -q` → all PASS.

### Task H3: Decision log — tune with data, not vibes

**Files:**
- Modify: `jarvis/jarvis.py` (log accepted AND rejected to one file)

- [ ] **Step 1:** add module-level:

```python
HEARING_LOG = CONFIG.working_dir / "hearing-log.tsv"


def log_hearing(verdict: str, text: str, conf: float, woke: bool) -> None:
    try:
        with open(HEARING_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')}\t{verdict}\t{conf:.2f}\t"
                    f"{woke}\t{text[:80]}\n")
    except OSError:
        pass
```

Call `log_hearing("ok", ...)` on accept and `log_hearing("rej", ...)` on reject in `handle_command`. After a day of use: `column -t "workspace/hearing-log.tsv"` shows exactly where thresholds sit vs reality; adjust `quality.py` constants from evidence.

- [ ] **Step 2:** `uv run pytest -q` → all PASS.

### Task H4 (optional, if small still mishears): Apple-GPU STT

- [ ] Add `mlx-whisper` dependency; config `stt_engine: "faster" | "mlx"`; `Transcriber` picks backend (`mlx_whisper.transcribe(audio, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language=lang)`). large-v3-turbo on M-series GPU ≈ small-on-CPU speed with far better accented-speech accuracy. Gate behind a benchmark: `uv run python -m jarvis.diag` timing before/after.

---

# PHASE M — CLAUDE-STYLE AGENT MANAGEMENT

How Claude Code does it (the model to copy): one task list, every agent has id/status/description, statuses move pending→running→done/failed, the orchestrator never loses an agent, results are reviewed, and the human sees one board, not three feeds.

### Task M1: AgentManager — one source of truth (`jarvis/manager.py`)

**Files:**
- Create: `jarvis/manager.py`
- Create: `tests/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_manager.py
from jarvis.manager import AgentManager


def test_local_task_lifecycle():
    m = AgentManager()
    m.local_started("t1", "create hello.txt")
    assert m.snapshot()[0]["status"] == "running"
    m.local_finished("t1", ok=True, summary="done")
    snap = m.snapshot()[0]
    assert snap["status"] == "done" and snap["kind"] == "local"


def test_cloud_merge_and_attention_on_fail():
    m = AgentManager()
    m.cloud_update([{"id": "trig_1", "name": "HIApply daily agent",
                     "enabled": True, "next_run_at": "2026-06-12T06:23:00Z",
                     "purpose": "daily review"}])
    m.report_update([{"msg_id": "m1", "agent": "HIApply daily agent",
                      "status": "FAIL", "summary": "repo denied"}])
    snap = {a["id"]: a for a in m.snapshot()}
    assert snap["trig_1"]["status"] == "needs_attention"
    assert snap["trig_1"]["last_report"] == "repo denied"


def test_ok_report_clears_attention():
    m = AgentManager()
    m.cloud_update([{"id": "trig_1", "name": "A", "enabled": True}])
    m.report_update([{"msg_id": "m1", "agent": "A", "status": "FAIL", "summary": "x"}])
    m.report_update([{"msg_id": "m2", "agent": "A", "status": "OK", "summary": "fine"}])
    assert m.snapshot()[0]["status"] == "scheduled"


def test_attention_list():
    m = AgentManager()
    m.cloud_update([{"id": "t1", "name": "A", "enabled": True},
                    {"id": "t2", "name": "B", "enabled": True}])
    m.report_update([{"msg_id": "m1", "agent": "B", "status": "FAIL", "summary": "x"}])
    assert [a["name"] for a in m.attention()] == ["B"]
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/test_manager.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement `jarvis/manager.py`**

```python
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
```

- [ ] **Step 4:** add `"agents"` to `STICKY_TYPES` in `jarvis/events.py`.
- [ ] **Step 5:** `uv run pytest tests/test_manager.py -v` → 4 PASS.

### Task M2: Wire all three feeds into the manager

**Files:**
- Modify: `jarvis/fleet.py` (feed manager)
- Modify: `jarvis/reports.py` (feed manager)
- Modify: `jarvis/jarvis.py` (local dispatch feeds manager)

- [ ] **Step 1: fleet.py** — in the monitor loop, after `BUS.emit("fleet", agents=agents)` add:

```python
                from .manager import MANAGER
                MANAGER.cloud_update(agents)
```

(import at top, not inline, in the real edit: `from .manager import MANAGER`.)

- [ ] **Step 2: reports.py** — after the `BUS.emit("reports", ...)` block add `MANAGER.report_update(reports)` (same import).

- [ ] **Step 3: jarvis.py `dispatch_async`** — wrap the task with manager calls:

```python
    task_id = f"task-{int(time.time())}"
    MANAGER.local_started(task_id, text)

    def work():
        clean, spoken, ok, sess = run_task(...)
        ...
        MANAGER.local_finished(task_id, ok, spoken or clean[:120])
        ...
```

- [ ] **Step 4:** `uv run pytest -q` → all PASS.

### Task M3: HUD — one agents board (replaces fleet+reports panels)

**Files:**
- Modify: `ui/index.html`, `ui/ws.js`, `ui/style.css`

- [ ] **Step 1: index.html** — replace the `#fleet` panel content with:

```html
    <div id="fleet" class="panel">
      <h2>// AGENTS <span id="agents-counts"></span></h2>
      <ul id="agents-list"><li class="dim">no agents yet…</li></ul>
    </div>
```

- [ ] **Step 2: ws.js** — replace the `fleet` and `reports` handlers with one `agents` handler (keep `fleet`/`reports` keys in `handlers` for compatibility; add `agents: []`):

```javascript
const STATUS_ICON = { running: "◐", done: "●", failed: "✖", scheduled: "◷",
                      paused: "⏸", needs_attention: "▲" };
window.JARVIS.on("agents", (m) => {
  const list = document.getElementById("agents-list");
  const counts = document.getElementById("agents-counts");
  list.innerHTML = "";
  const attn = m.agents.filter(a => a.status === "needs_attention").length;
  counts.textContent = `· ${m.agents.length} total` + (attn ? ` · ${attn} need attention` : "");
  for (const a of m.agents) {
    const li = document.createElement("li");
    li.className = `st-${a.status}`;
    li.innerHTML = `<span class="st-icon">${STATUS_ICON[a.status] || "?"}</span>` +
      `<span class="agent-name"></span><span class="agent-kind">${a.kind}</span>` +
      `<span class="report-summary"></span>`;
    li.querySelector(".agent-name").textContent = a.name;
    li.querySelector(".report-summary").textContent = a.last_report || a.purpose || "";
    list.appendChild(li);
  }
});
```

- [ ] **Step 3: style.css** — append:

```css
#agents-list { list-style: none; font-size: 12px; }
#agents-list li { padding: 3px 0; border-bottom: 1px dashed #0a3a45;
  display: flex; gap: 8px; align-items: center; }
#agents-list .st-icon { width: 14px; text-align: center; }
#agents-list .agent-kind { color: #46707c; font-size: 9px; letter-spacing: 1px; }
#agents-list .report-summary { margin-left: auto; color: #8fc7d4; font-size: 10px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 45%; }
#agents-list .st-running .st-icon { color: var(--amber); }
#agents-list .st-done .st-icon { color: var(--green); }
#agents-list .st-failed .st-icon, #agents-list .st-needs_attention .st-icon { color: var(--red); }
#agents-list .st-needs_attention { background: #3a0c1422; }
```

- [ ] **Step 4:** `uv run pytest tests/test_server.py -q` → PASS; restart, board shows the HIApply agent + any local task while it runs.

### Task M4: Attention by voice + spoken alerts

**Files:**
- Modify: `workspace/CLAUDE.md` (voice intents)
- Modify: `jarvis/reports.py` (alert text comes from manager)

- [ ] **Step 1: CLAUDE.md** — add under "Voice intents":

```markdown
- "what needs my attention / מה דורש טיפול" → read workspace state: the HUD agents
  board marks needs_attention; check memory/agents.md + RemoteTrigger list + recent
  [JARVIS] emails. Answer with ONLY the items needing action and the one-line reason.
```

- [ ] **Step 2:** spoken FAIL alert (already in reports.py) stays; verify text matches the board.

### Task M5: E2E verification

- [ ] 1. `uv run pytest -q` → all PASS.
- [ ] 2. Voice: command Jarvis a task → board shows it `◐ running`, then `● done`.
- [ ] 3. Board shows HIApply agent `◷ scheduled`; after a FAIL email → `▲` + red row + spoken alert; after next OK → back to `◷`.
- [ ] 4. "Hey Jarvis, what needs my attention?" → only the red rows, with reasons.

---

## Risks / notes

- H1 doubles transcription time only when whisper guesses a non-allowed language (the failure case anyway).
- Confidence thresholds are first-pass; H3's hearing log exists precisely to tune them after a real day of use.
- M1 keeps state in memory — restart loses local-task history (cloud agents repopulate in ≤10 min). Persisting to disk is a later nicety.

## Self-review notes

- User pain → tasks: wrong language (pt) → H1; good command rejected → H2; "works real bad", need evidence → H3 log + H4 escalation path; "best ai agent manage … like claude agents" → M1 unified statuses, M2 all feeds one truth, M3 one board, M4 attention by voice.
- Type consistency: `transcribe()` stays 3-tuple `(text, lang, conf)` — call sites unchanged; `accept(text, conf, woke)` matches; MANAGER methods used in M2 match M1 signatures.
