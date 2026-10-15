#!/usr/bin/env bash
# Resume the full McBench-Hard run for all Codex models (k=1), then the Core test split, then rebuild the board.
set -e
export PATH="$(npm prefix -g)/bin:$PATH"
python3 -m mcbench run --config models.codex.json --task-set hard-v1.1 --split all --max-steps 150 --jobs 8 --resume --out runs/hard-v1.1
python3 -m mcbench run --config models.codex.json --task-set v1.0 --split test --max-steps 150 --jobs 8 --resume --out runs/core-test-v1.1
python3 -m mcbench combine runs/hard-v1.1 runs/core-test-v1.1 --note "Hard 32 + Core test 18 · offline frozen snapshot"
