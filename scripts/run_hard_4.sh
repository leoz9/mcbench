#!/usr/bin/env bash
# Hard TEST (22) + Core TEST (18) for 4 Codex models; resume-safe.
# Core for gpt-6-luna / gpt-5.6-luna reuses the v1.0 test-split traces (copied into
# runs/core-test-v1.1 as *-codex__*), so only the two sol models are run on Core here.
# Exits 3 if Codex reports a usage/rate limit (no trace is written for that task).
set -e
export PATH="/home/box/.local/bin:$(npm prefix -g)/bin:$PATH"
cd /workspace/mcbench
python3 -m mcbench run --config models.codex.4.json --task-set hard-v1.1 --split test --max-steps 150 --jobs 8 --resume --out runs/hard-v1.1
# restore Core traces parked while the sol Core run was incomplete
if compgen -G "runs/core-test-v1.1/partial/*.json" > /dev/null; then
  mv runs/core-test-v1.1/partial/*.json runs/core-test-v1.1/traces/
fi
python3 -m mcbench run --config models.codex.sol.json --task-set v1.0 --split test --max-steps 150 --jobs 8 --resume --out runs/core-test-v1.1
python3 -m mcbench combine runs/hard-v1.1 runs/core-test-v1.1 --note "Hard test 22 + Core test 18 · offline frozen snapshot · 4 Codex models (luna Core from v1.0 test traces re-scored under v1.1)"
