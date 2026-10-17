#!/usr/bin/env bash
# Publish NVIDIA NIM models that completed Hard test 22 + Core test 18: rebuild board/README, secret-scan,
# commit, pull --rebase, push. Coexists with the opencode auto-publisher in the same checkout
# (serialised via flock; retries on index.lock). Usage: scripts/nim_publish.sh [model ...]
cd "$(dirname "$0")/.." || exit 1
exec 9>/tmp/mcbench-git.lock
flock 9
for i in 1 2 3 4 5 6; do [ -e .git/index.lock ] && sleep 10 || break; done
out=$(python3 scripts/combine_complete.py 2>&1) || { echo "combine failed: $out"; exit 1; }
comp=$(echo "$out" | sed -n "s/^nim complete: \[\(.*\)\] | held back.*/\1/p" | tr -d "' " | tr ',' ' ')
python3 scripts/readme_table.py >/dev/null
git checkout -q runs/hard-v1.1/leaderboard.json runs/core-test-v1.1/leaderboard.json 2>/dev/null
git add README.md README_EN.md web/data runs/hard-v1.1/combined_leaderboard.json \
  mcbench/nim_agent.py mcbench/harness.py mcbench/cli.py scripts/nim_supervisor.py scripts/nim_publish.sh \
  scripts/combine_complete.py scripts/readme_table.py models.nim.json 2>/dev/null
for m in $comp; do git add "runs/hard-v1.1/traces/${m}__"* "runs/core-test-v1.1/traces/${m}__"*; done
bad=$(git diff --cached | grep -cE "nvapi-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.|mcd-live/raw")
for v in NVIDIA_API_KEY MCD_MCP_TOKEN CLOUDFLARE_API_TOKEN ALIYUN_TOKEN_PLAN_KEY; do
  val="${!v}"; [ ${#val} -ge 12 ] && bad=$((bad + $(git diff --cached | grep -cF -- "${val:0:40}")))
done
if [ "$bad" != "0" ]; then echo "SECRET SCAN HIT ($bad) - not committing"; git reset -q; exit 2; fi
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
summ=$(for m in "$@"; do echo "$out" | grep -E "^${m} " | awk '{print $1" "$2}'; done | tr '\n' ';')
git commit -qm "results: NVIDIA NIM free ${*:-models} Hard+Core test complete (${summ})" || exit 1
for i in 1 2 3; do
  git pull -q --rebase --autostash origin main && git push -q origin HEAD:main && { echo "$(TZ=America/New_York date '+%F %H:%M %Z') published $* -> $(git log --oneline -1)"; exit 0; }
  git rebase --abort 2>/dev/null; sleep 20
done
echo "push failed"; exit 1
