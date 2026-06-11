# Jarvis — voice agent for macOS

Say **"Hey Jarvis"**, speak a task in **Hebrew or English**, watch it execute in the HUD, hear the answer.

## Run

```bash
./run.sh          # starts daemon + opens HUD at http://localhost:8765
```

First run: downloads wake-word model (small) + whisper model (~500MB), and macOS asks for mic permission.

## Requirements

- macOS, `uv`, `claude` CLI on PATH
- Hebrew voice "Carmit": System Settings → Accessibility → Spoken Content → System Voice → Manage Voices

## Config

Edit `jarvis/config.py`:
- `working_dir` — where claude tasks run (default `./workspace`)
- `permission_profile` — `"default"` (allowlisted tools) or `"yolo"` (skip all permission checks)
- `whisper_model` — `small` (default) / `medium` (better Hebrew, slower)
- `wake_threshold` — raise if false triggers, lower if it misses you

## Architecture

See `docs/superpowers/specs/2026-06-11-jarvis-voice-agent-design.md`.

Voice pipeline: openwakeword → webrtcvad → faster-whisper → `claude -p` (stream-json) → `say`.
UI: FastAPI + WebSocket → canvas HUD (arc reactor + mission-control agent graph).

## Jarvis 2.0

- **Human voice:** neural TTS (edge-tts — British male EN, natural HE). Offline → falls back to `say`. Engine: `tts_engine` in config.
- **Conversation mode:** after each answer the mic reopens for follow-ups (same Claude session); "new conversation" resets context.
- **Fast chat / full work:** short questions → fast model; real tasks → full power (`chat_model` / `work_model`).
- **"Test it":** Jarvis starts the app in background and drives your visible Chrome through the flows while narrating to the HUD.
- **Memory:** `workspace/memory/` — index + per-topic files, maintained automatically.

## Fleet Command

Jarvis commands a fleet of cloud agents (claude.ai routines):

- "Hey Jarvis, create an agent that reviews HIApply commits every morning"
- "Hey Jarvis, what are my agents doing?" / "status of the HIApply agent"
- "Hey Jarvis, run the leads agent now"

Every agent reports by email (`[JARVIS] <name> <OK|WARN|FAIL>`); Jarvis polls the
inbox, shows reports in the HUD (AGENT REPORTS chips), speaks failures aloud, and
gives a daily digest at 09:30 (`digest_time`). Fleet state: `workspace/fleet-registry.json`
+ `workspace/memory/agents.md`. Delete routines at https://claude.ai/code/routines.

## Troubleshooting voice

- `uv run python -m jarvis.wake` — live wake-word scores; set `wake_threshold` just below your scores.
- `uv run python -m jarvis.diag` — record/playback + VAD timeline + transcription timing.
- Cut off mid-sentence? Raise `silence_stop_s`. Accidental commands after answers? The follow-up gate needs 3+ words at ≥0.5 confidence — tune in `jarvis/quality.py`.
- Cancel a running task: "Hey Jarvis" → "stop".
- Ctrl-C now shuts down cleanly; audio errors auto-recover.

## v3 ideas

Hebrew wake phrase, barge-in/cancel by voice, phone push on FAIL, launchd autostart.
