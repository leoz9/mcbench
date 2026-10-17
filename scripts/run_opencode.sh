#!/usr/bin/env bash
# Hard TEST (22) + Core TEST (18) for opencode free models (OpenCode Zen free tier, no login/API key).
# Usage: CONFIG=models.opencode.json JOBS=4 scripts/run_opencode.sh
# Resume-safe; exits 3 on persistent rate limit / provider error — re-run to resume.
set -e
export PATH="/home/box/.local/bin:$(npm prefix -g)/bin:$PATH"
cd /workspace/mcbench
CONFIG="${CONFIG:-models.opencode.json}"
JOBS="${JOBS:-4}"
python3 -u -m mcbench run --config "$CONFIG" --task-set hard-v1.1 --split test --max-steps 150 --jobs "$JOBS" --resume --out runs/hard-v1.1
python3 -u -m mcbench run --config "$CONFIG" --task-set v1.0 --split test --max-steps 150 --jobs "$JOBS" --resume --out runs/core-test-v1.1
if [ -z "$NO_COMBINE" ]; then
  python3 -m mcbench combine runs/hard-v1.1 runs/core-test-v1.1 --note "Hard test 22 + Core test 18 · offline frozen snapshot · Codex CLI + opencode (free tier) models"
fi
