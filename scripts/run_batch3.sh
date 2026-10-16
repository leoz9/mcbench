#!/usr/bin/env bash
# Hard TEST (22) + Core TEST (18) for gpt-6-astra, gpt-reserve, gpt-5.6-sol, gpt-5.6-terra; resume-safe.
# Exits 3 on Codex usage limit; re-run to resume.
set -e
export PATH="/home/box/.local/bin:$(npm prefix -g)/bin:$PATH"
cd /workspace/mcbench
python3 -m mcbench run --config models.codex.batch3.json --task-set hard-v1.1 --split test --max-steps 150 --jobs 8 --resume --out runs/hard-v1.1
python3 -m mcbench run --config models.codex.batch3.json --task-set v1.0 --split test --max-steps 150 --jobs 8 --resume --out runs/core-test-v1.1
python3 -m mcbench combine runs/hard-v1.1 runs/core-test-v1.1 --note "Hard test 22 + Core test 18 · offline frozen snapshot · Codex models"
