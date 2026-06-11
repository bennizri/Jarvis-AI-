#!/bin/bash
cd "$(dirname "$0")"
export HF_HUB_DISABLE_XET=1   # xet backend hangs on this machine; plain HTTP works
(sleep 2 && open "http://localhost:8765") &
exec uv run python -m jarvis.jarvis
