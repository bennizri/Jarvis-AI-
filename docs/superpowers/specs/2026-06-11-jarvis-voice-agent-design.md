# Jarvis Voice Agent — Design Spec

Date: 2026-06-11
Status: approved pending user review

## What it is

Always-on voice assistant for macOS. User says "Hey Jarvis", speaks a task in Hebrew or English, Jarvis dispatches it to Claude Code (headless), shows everything in an Iron Man-style HUD web UI, and speaks a short answer back in the matching language.

## Decisions made

| Decision | Choice |
|---|---|
| Task types | Coding tasks + general Mac tasks |
| Activation | Always-on wake word ("Hey Jarvis", English; Hebrew wake phrase deferred to v2) |
| Wake engine | openWakeWord, pretrained `hey_jarvis` model (~1-2% CPU idle) |
| Speech-to-text | faster-whisper, local, free, auto language detect (Hebrew + English) |
| Voice reply | Yes — macOS `say`: Carmit (Hebrew), Samantha/premium (English) |
| Task executor | `claude -p` headless with `--output-format stream-json` |
| UI | Web UI at `http://localhost:8765`, Iron Man HUD style, full mission-control agent graph |
| Cost | $0 — all local, no API keys |

## Architecture

```
┌─────────────────────────── Python daemon ────────────────────────────┐
│                                                                      │
│  mic stream (sounddevice, 16kHz mono)                                │
│    → wake.py        openWakeWord "hey_jarvis"                        │
│    → recorder.py    webrtcvad capture until silence (max 30s)        │
│    → transcribe.py  faster-whisper small/int8, lang auto-detect      │
│    → dispatch.py    claude -p "<task>" --output-format stream-json   │
│    → speak.py       macOS `say`, voice matched to detected language  │
│                                                                      │
│  events.py — async event bus; every stage publishes state/events     │
│  server.py — FastAPI: serves static UI + WebSocket /ws event stream  │
│  jarvis.py — main loop / orchestrator                                │
│  config.py — thresholds, whisper model size, working dir, voices,    │
│              claude permission mode, port                            │
└──────────────────────────────────────────────────────────────────────┘
                              │ WebSocket (JSON events)
                              ▼
┌─────────────────────────── Web UI (HUD) ─────────────────────────────┐
│  Single page, vanilla JS + canvas (no build step)                    │
│                                                                      │
│  • Arc-reactor core, rotating rings, cyan/amber glow, scan lines     │
│  • States: idle breathing → listening pulse (mic level reactive) →   │
│    transcribing → working (rings spin fast) → speaking               │
│  • Transcript panel: what Jarvis heard (RTL support for Hebrew)      │
│  • Mission control: animated node graph — Jarvis core center, each   │
│    tool call / subagent a node that lights up, pulsing edges,        │
│    plus scrolling per-node activity log                              │
│  • Final answer panel + spoken-summary highlight                     │
└──────────────────────────────────────────────────────────────────────┘
```

## Event protocol (daemon → UI over WS)

| Event | Payload | UI reaction |
|---|---|---|
| `state` | `idle\|listening\|transcribing\|working\|speaking` | core animation mode |
| `mic_level` | float 0-1 (only while listening) | pulse amplitude |
| `transcript` | text + detected language | transcript panel (RTL if `he`) |
| `agent_event` | parsed stream-json: tool name, agent spawn, text delta, file paths | mission-control nodes + log |
| `answer` | full text + `spoken` summary | answer panel |
| `error` | message | red flash + error toast |

## Claude Code dispatch

- Command: `claude -p "<task>" --output-format stream-json --verbose` run in configurable working dir (`config.working_dir`).
- Permissions: headless mode can't prompt, so config exposes `permission_profile`: default = `--allowedTools "Bash Read Edit Write Glob Grep WebSearch WebFetch Agent"` (covers coding + Mac tasks); optional `yolo` profile = `--dangerously-skip-permissions` for full autonomy (off by default).
- Appended instruction: end the answer with line `SPOKEN: <one short sentence in the task's language>`. That line is spoken; full text goes to UI.
- stream-json parsed live: `tool_use` blocks → mission-control nodes (Bash, Edit, Agent/subagents, etc.); text deltas → live answer panel.
- While a task runs, wake word triggers a spoken "still working" — no queue.

## Error handling

| Failure | Behavior |
|---|---|
| Empty/garbled transcription | speaks "didn't catch that" / «לא שמעתי», back to idle |
| `claude` CLI missing | error event + spoken alert at startup check |
| Mic permission denied | clear startup error with fix instructions |
| Whisper model first download (~500MB) | UI shows download progress state |
| claude task crash / nonzero exit | error event, stderr to UI log, spoken "task failed" |
| WS client disconnected | daemon keeps working; UI reconnects automatically |

## Testing

- Each module runnable standalone: `python -m jarvis.transcribe sample.wav`, `python -m jarvis.speak "שלום" he`, `python -m jarvis.wake` (prints detections live).
- Dispatch tested with mock stream-json fixture before live claude calls.
- End-to-end: scripted run with prerecorded wav injected instead of mic.

## File layout

```
AI agent/
├── jarvis/            # Python package (each file < 300 lines)
│   ├── jarvis.py  wake.py  recorder.py  transcribe.py
│   ├── dispatch.py  speak.py  events.py  server.py  config.py
├── ui/                # static frontend
│   ├── index.html  hud.js  graph.js  ws.js  style.css
├── pyproject.toml     # uv-managed deps
└── run.sh             # start daemon + open browser
```

## v2 (explicitly out of scope now)

- Hebrew wake phrase «היי ג'ארביס» (custom openWakeWord model training)
- launchd autostart / menu bar icon
- Conversation follow-ups ("continue", multi-turn session resume)
- Task queue
