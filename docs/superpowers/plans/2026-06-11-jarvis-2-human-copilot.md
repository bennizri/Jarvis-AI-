# Jarvis 2.0 — Human Voice + Autonomous Testing + Fleet Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Jarvis from a working voice pipeline into a human-sounding, genuinely useful copilot: natural neural voice (not robotic `say`), conversational answers, the ability to *run and demo projects in the user's visible Chrome* ("test it" → starts the app, drives the browser while the user watches), smart model routing (fast chats, powerful work), deeper memory — plus command of a 30-agent cloud fleet.

**Architecture:** Four phases. **A — Human voice:** swap TTS to Microsoft Edge neural voices (`edge-tts`, free, he-IL + en-GB "Jarvis-like" voices) with offline `say` fallback, and rewrite the spoken-answer instruction so replies sound like a person. **B — Autonomous testing:** teach the inner Claude a testing protocol (start the app in background, attach to the user's real Chrome via the superpowers-chrome browsing skill, walk the flows on screen, narrate to mission control) and widen its tool allowlist. **C — Fleet Command:** execute the existing fleet plan (separate doc). **D — Copilot smarts:** classify each voice task → cheap fast model for chat, full model for real work; structured long-term memory.

**Tech Stack:** existing Jarvis daemon (Python 3.12/uv, FastAPI WS, canvas HUD), `edge-tts` (neural TTS), `afplay`, superpowers-chrome plugin (CDP browser control), `claude` CLI headless.

**Git:** User handles all commits — NO commit steps (user rule overrides skill default).

---

## Phase 0 — manual prerequisites (user)

- [ ] GitHub re-auth at claude.ai settings (covers Phase C; see fleet plan Phase 0).
- [ ] Chrome must run with CDP enabled for browser control. The superpowers-chrome skill handles attach/launch; nothing to install.

---

# PHASE A — HUMAN VOICE

### Task A1: Neural TTS engine (`jarvis/speak.py` + config + dep)

**Files:**
- Modify: `pyproject.toml` (add `edge-tts`)
- Modify: `jarvis/config.py` (voice config)
- Modify: `jarvis/speak.py`
- Modify: `tests/test_speak.py`

- [ ] **Step 1: Add dependency**

In `pyproject.toml` dependencies add: `"edge-tts>=6.1",` then run `uv sync`.
Expected: `+ edge-tts` installed.

- [ ] **Step 2: Add config** — in `jarvis/config.py` replace the tts block with:

```python
    # tts
    tts_engine: str = "neural"              # "neural" (edge-tts) | "say" (offline)
    voices: dict = field(default_factory=lambda: {"he": "Carmit", "en": "Samantha"})
    neural_voices: dict = field(default_factory=lambda: {
        "he": "he-IL-AvriNeural",           # natural Hebrew male
        "en": "en-GB-RyanNeural",           # British male — the Jarvis vibe
    })
```

- [ ] **Step 3: Update tests** — in `tests/test_speak.py` replace the whole file:

```python
from unittest.mock import patch

from jarvis import speak
from jarvis.config import CONFIG


def setup_function(_):
    CONFIG.tts_engine = "say"  # tests never hit the network


def teardown_function(_):
    CONFIG.tts_engine = "neural"


def test_voice_for_language():
    assert speak.voice_for("he") == "Carmit"
    assert speak.voice_for("en") == "Samantha"
    assert speak.voice_for("fr") == "Samantha"  # unknown -> english voice


def test_say_engine_invokes_say():
    with patch("subprocess.run") as run:
        speak.speak("שלום", "he")
        run.assert_called_once_with(["say", "-v", "Carmit", "שלום"], check=False)


def test_phrase_known_key():
    with patch("subprocess.run") as run:
        speak.phrase("didnt_catch", "he")
        args = run.call_args[0][0]
        assert args[:3] == ["say", "-v", "Carmit"]


def test_neural_falls_back_to_say_when_unavailable():
    CONFIG.tts_engine = "neural"
    with patch("jarvis.speak._neural", return_value=False), \
         patch("subprocess.run") as run:
        speak.speak("hello", "en")
        run.assert_called_once_with(["say", "-v", "Samantha", "hello"], check=False)
```

- [ ] **Step 4: Run, verify fail**

Run: `uv run pytest tests/test_speak.py -v`
Expected: FAIL — `AttributeError: module 'jarvis.speak' has no attribute '_neural'`

- [ ] **Step 5: Implement** — in `jarvis/speak.py` replace `speak()` and add `_neural()`:

```python
def _neural(text: str, lang: str) -> bool:
    """Speak via edge-tts neural voice. Returns False so caller can fall back."""
    import asyncio
    import tempfile
    try:
        import edge_tts
    except ImportError:
        return False
    voice = CONFIG.neural_voices.get(lang, CONFIG.neural_voices["en"])
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        asyncio.run(edge_tts.Communicate(text, voice).save(path))
        subprocess.run(["afplay", path], check=False)
        return True
    except Exception:
        return False  # offline / service hiccup -> robotic but working `say`


def speak(text: str, lang: str) -> None:
    if not text:
        return
    if CONFIG.tts_engine == "neural" and _neural(text, lang):
        return
    subprocess.run(["say", "-v", voice_for(lang), text], check=False)
```

- [ ] **Step 6: Run, verify pass**

Run: `uv run pytest tests/test_speak.py -v`
Expected: 4 PASS

- [ ] **Step 7: Hear it (manual)**

Run: `uv run python -c "from jarvis import speak; speak.speak('Good evening. All systems are online and ready to work.', 'en'); speak.speak('ערב טוב, כל המערכות פועלות', 'he')"`
Expected: natural British male English + natural Hebrew, audibly better than `say`. If silent, check internet; `say` fallback should kick in.

---

### Task A2: Conversational answers (prompt + persona)

**Files:**
- Modify: `jarvis/dispatch.py:8-12` (PROMPT_SUFFIX)
- Modify: `workspace/CLAUDE.md` (persona)

- [ ] **Step 1: Replace PROMPT_SUFFIX in `jarvis/dispatch.py`**

```python
PROMPT_SUFFIX = (
    f"\n\nIMPORTANT: End your final answer with a line starting with '{SPOKEN_TAG} ' "
    "followed by what you would SAY out loud — natural, warm, conversational, like a "
    "sharp human assistant (1-3 short sentences, same language as the task; Hebrew "
    "task → Hebrew answer). Never read lists, paths, or code aloud; tell the outcome "
    "the way a person would, e.g. 'Done — the file is ready and tests pass.'"
)
```

- [ ] **Step 2: Add persona to `workspace/CLAUDE.md`** (top, after the intro line):

```markdown
## Personality
You are Jarvis: calm, capable, concise, a touch of dry wit. You talk like a trusted
human chief-of-staff, never like a form letter. You volunteer the next useful step
("Want me to also run the tests?") instead of waiting to be micromanaged.
```

- [ ] **Step 3: Verify** — `uv run pytest tests/test_dispatch.py -v` → all PASS (SPOKEN_TAG still in suffix). Voice test: ask anything; the spoken reply should sound like a person, not a status code.

---

# PHASE B — AUTONOMOUS TESTING & LIVE BROWSER CONTROL

### Task B1: Widen the inner Claude's tool allowlist

**Files:**
- Modify: `jarvis/config.py:26` (allowed_tools)
- Test: `tests/test_dispatch.py` (existing build_cmd test still passes)

- [ ] **Step 1: Replace `allowed_tools` in `jarvis/config.py`**

```python
    allowed_tools: str = ("Bash Read Edit Write Glob Grep WebSearch WebFetch Agent "
                          "Skill ToolSearch RemoteTrigger KillShell TaskOutput "
                          "mcp__plugin_superpowers-chrome_chrome__use_browser")
```

- [ ] **Step 2: Verify**

Run: `uv run pytest tests/test_dispatch.py -v`
Expected: all PASS.

---

### Task B2: Testing protocol in Jarvis's brain

**Files:**
- Modify: `workspace/CLAUDE.md` (new section before "## Known projects")

- [ ] **Step 1: Add the section**

```markdown
## Testing / demo protocol — triggers: "test it", "show me", "run it", «תבדוק», «תריץ»
When asked to test, demo, or run a project, you OWN the whole process end to end:
1. Locate the project (Known projects / memory / ~/Documents/GitHub), read its
   README or CLAUDE.md for how to run it.
2. Start the app yourself: Bash with run_in_background (dev server, backend, etc.).
   Poll the port/URL until it answers; fix trivial startup errors yourself
   (missing dep → install; busy port → pick another and say so).
3. Open it in the USER'S VISIBLE Chrome so they can watch: invoke the
   superpowers-chrome:browsing skill and use the use_browser tool — new tab with
   the app URL, then drive the main flows for real: click, type test data,
   submit forms, navigate. The user is watching the screen; move deliberately.
4. Narrate every step in your text output (it streams to the mission-control HUD).
5. Finish with what works, what's broken (file:line when known), and leave the app
   running + the tab open unless asked to clean up.
6. If a flow needs credentials, use ones from memory/ if saved; otherwise ask.
```

- [ ] **Step 2: Verify by voice (manual E2E)** — say: "Hey Jarvis, test the High Apply project and show me in the browser."
Expected: Jarvis starts HIApply's dev server in background, a Chrome tab opens on screen with the app, forms get filled/clicked while mission control streams the steps, spoken human-sounding summary at the end.

---

# PHASE C — FLEET COMMAND

- [ ] **Execute the dedicated plan:** `docs/superpowers/plans/2026-06-11-jarvis-fleet-command.md` (Tasks 1–9 there, complete with code: shared CLI helper, fleet poll v2 + registry, Gmail report polling with spoken FAIL alerts, daily digest, HUD fleet panel + report chips, agent-factory conventions). It is self-contained — run it with the same execution method as this plan, after Phase B.

---

# PHASE D — COPILOT SMARTS

### Task D1: Model routing — fast chat, powerful work (`jarvis/routing.py`)

**Files:**
- Create: `jarvis/routing.py`
- Create: `tests/test_routing.py`
- Modify: `jarvis/config.py` (routing config)
- Modify: `jarvis/dispatch.py` (model param)
- Modify: `jarvis/jarvis.py` (use router)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routing.py
from jarvis.routing import classify


def test_short_question_is_chat():
    assert classify("what time is it") == "chat"
    assert classify("מה השעה") == "chat"
    assert classify("do you hear me") == "chat"


def test_action_verbs_are_work():
    assert classify("create a file called hello.txt") == "work"
    assert classify("תריץ את הטסטים בפרויקט") == "work"
    assert classify("test the high apply project") == "work"
    assert classify("fix the login bug") == "work"


def test_long_sentences_are_work():
    long_q = "can you walk me through everything that changed in the project " \
             "this week and what is still left to finish"
    assert classify(long_q) == "work"
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/test_routing.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `jarvis/routing.py`**

```python
ACTION_WORDS = {
    # en
    "create", "make", "build", "fix", "run", "test", "deploy", "install",
    "delete", "rename", "search", "send", "open", "write", "update", "refactor",
    "check", "review", "start", "stop", "pause", "schedule", "monitor",
    # he
    "תיצור", "תבנה", "תתקן", "תריץ", "תבדוק", "תתקין", "תמחק", "תחפש",
    "תשלח", "תפתח", "תכתוב", "תעדכן", "תעצור", "צור", "בנה", "תקן", "הרץ",
}

MAX_CHAT_WORDS = 9


def classify(text: str) -> str:
    """'chat' -> quick conversational answer, 'work' -> real task."""
    words = text.lower().replace("?", "").replace(".", "").split()
    if len(words) > MAX_CHAT_WORDS:
        return "work"
    if any(w in ACTION_WORDS for w in words):
        return "work"
    return "chat"
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/test_routing.py -v`
Expected: 3 PASS

- [ ] **Step 5: Config** — in `jarvis/config.py` add to the dispatch block:

```python
    chat_model: str = "haiku"               # snappy answers for small talk/questions
    work_model: str = ""                    # "" = CLI default (full power)
```

- [ ] **Step 6: Thread model through dispatch** — in `jarvis/dispatch.py`:

`build_cmd` signature becomes:

```python
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
```

`run_task` signature becomes `def run_task(task, session_id=None, model="")` and passes `model` to `build_cmd`.

- [ ] **Step 7: Use it in `jarvis/jarvis.py`** — in `handle_command`, before dispatch:

```python
    from .routing import classify  # top of file with other imports
    ...
    model = CONFIG.chat_model if classify(text) == "chat" else CONFIG.work_model
    return dispatch_async(text, lang, convo, model)
```

and `dispatch_async` gains the `model` param and calls
`run_task(text, convo.session_id, model)`.

- [ ] **Step 8: Add build_cmd model test to `tests/test_dispatch.py`**

```python
def test_build_cmd_model_flag():
    cmd = build_cmd("hi", model="haiku")
    i = cmd.index("--model")
    assert cmd[i + 1] == "haiku"
    assert "--model" not in build_cmd("hi")
```

- [ ] **Step 9: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS. Voice check: "Hey Jarvis, do you hear me?" answers in ~5-8s instead of 20+.

---

### Task D2: Structured long-term memory

**Files:**
- Modify: `workspace/CLAUDE.md` (memory section)
- Create: `workspace/memory/index.md`

- [ ] **Step 1: Replace the `## Memory` section in `workspace/CLAUDE.md`**

```markdown
## Memory
`memory/` is your long-term memory. `memory/index.md` is the table of contents —
read it FIRST on any task that mentions a person, project, preference, or anything
from a previous conversation.

Structure: one file per topic — `memory/projects/<name>.md`,
`memory/people/<name>.md`, `memory/preferences.md`, `memory/agents.md`.

Rules:
- New fact from the user → save immediately, update index.md, say you remembered.
- Corrected fact → update the file, never keep stale info.
- Every project file: path, how to run it, how to test it, current goals.
- Check memory BEFORE searching the disk and BEFORE asking the user.
```

- [ ] **Step 2: Create `workspace/memory/index.md`**

```markdown
# Memory index
- projects/hiapply.md — High Apply: AI job application platform (~/Documents/GitHub/HIApply)
```

- [ ] **Step 3: Create `workspace/memory/projects/hiapply.md`**

```markdown
# High Apply (HIApply)
- Path: ~/Documents/GitHub/HIApply · repo github.com/idanizri/HIApply
- Stack: React 19 + TS frontend, FastAPI backend, Playwright workers, PG+pgvector
- Cloud agent: "HIApply daily agent" (trig_017sefGH6wDbnWxK7kNodXeE), daily 09:23
- Conventions: files ≤300 lines, functions ≤40, credentials via Fernet encryption
```

- [ ] **Step 4: Verify by voice** — "Hey Jarvis, what do you know about High Apply?" → answers from memory without disk search.

---

### Task D3: Final E2E + docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README additions** — append:

```markdown
## Jarvis 2.0

- **Human voice:** neural TTS (edge-tts, British male EN / natural HE). Offline → falls back to `say`. Engine: `tts_engine` in config.
- **Fast chat / full work:** short questions answered by a fast model; real tasks get full power (`chat_model` / `work_model`).
- **"Test it":** Jarvis starts the app and drives your visible Chrome through the flows.
- **Memory:** `workspace/memory/` — index + per-topic files, maintained automatically.
```

- [ ] **Step 2: Full verification script**

1. `uv run pytest -q` → all PASS.
2. "Hey Jarvis, do you hear me?" → fast, human-sounding reply.
3. "Hey Jarvis, test the High Apply project, show me in the browser" → app starts, Chrome tab drives itself on screen, narration in HUD, spoken summary.
4. "Hey Jarvis, what do you know about High Apply?" → memory answer, no searching.
5. Follow-up without wake word → same session context.

---

## Risks / open issues

1. **edge-tts requires internet** — graceful fallback to `say` built in (Task A1). If Microsoft throttles, alternative: OpenAI TTS (paid key) — drop-in at `_neural`.
2. **Headless plugin/skill availability:** the inner `claude -p` must see the superpowers-chrome plugin (user-scope, should inherit). Task B2's voice E2E is the gate; if absent, fallback is Bash + `open <url>` (app still opens, no automated clicking).
3. **TTS latency:** neural adds ~1s synth time; acceptable, and chat-model routing (D1) more than compensates.
4. **classify() is heuristic** — misrouted chat→work just means slower answer; work→chat only on short imperative-less phrasing; tune ACTION_WORDS over time.
5. **Phase C risks** documented in the fleet plan (Gmail-in-headless is the big one).

## Self-review notes

- Coverage vs request: "sound like human" → A1 (neural voice) + A2 (conversational text); "also the response" → A2 + D1 speed; "tell him to test it → start all the process and control my web so I can see it" → B1+B2 (visible Chrome protocol, background app start); "real smart one that can help me do the job" → D1 routing, D2 memory, Phase C fleet, persona A2.
- Type consistency: `build_cmd(task, session_id, model)` matches `run_task(task, session_id, model)` and `dispatch_async(text, lang, convo, model)`; `CONFIG.tts_engine/neural_voices` used only in speak.py; `classify` imported in jarvis.py only.
- No placeholders: full code in every code step; Phase C delegates to a complete sibling plan by explicit path.
