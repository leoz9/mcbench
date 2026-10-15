# Changelog

## v1.2.0 — 2026-10-15
- **120 text tasks in total** (Core 54 + Hard 65), plus 12 McBench-Vision frames. Hard gains 33 dev tasks (`scripts/gen_hard_ext.py`, seed 1201) in 7 new or extended categories: nutrition_opt, coupon_opt, dietary_strict, adversarial_user, and more boundary / followup / injection / hidden / budget tasks. All are strict exact-optimum or proven-infeasible, and every reference is re-verified.
- The v1.1 Hard tasks and the **22-task held-out test split are unchanged**, so v1.1 results stay comparable. The headline board scores Hard on the test split (`combine --hard_split test`); `scripts/run_hard.sh` runs the Hard test split.
- Offline scripted baselines re-run on all 65 Hard tasks.

## v1.1.0 — 2026-10-15
- **McBench-Hard** (32 tasks, `hard-v1.1`): exact-optimum knapsacks, distinct-item orders, near-boundary infeasibility, strict tool budgets, simulated user changing requirements mid-episode, prompt injection in tool outputs, distractor tools, hidden constraints. All references come from the solver and are re-verified in tests.
- **Multi-dimensional rubric** (`mcbench/rubric.py`): constraints / optimality (partial credit by gap) / honesty / safety / efficiency / clarification; penalties for hallucinated codes, duplicate and invalid calls, assumptions, unsafe actions, exceeded budgets; strict pass (Core gap ≤ 2%, Hard = exact). Applied retroactively, so Core v1.0 numbers changed.
- Headline board = Hard; Overall = 0.6·Hard + 0.4·Core(test). `mcbench combine`.
- Env: `followup`, `injection`, `distractor_tools`, `max_tool_calls`; solver: `distinct_codes`, `max_items`.
- All 8 Codex models probed (all respond); full Hard runs pending (Codex usage limit hit, see README).

## v1.0.0 — 2026-10-15
- 54-task versioned set (9 categories, easy/medium/hard, dev/test split), exact solver references.
- Frozen offline snapshot of real mcp.mcd.cn data (scrubbed) → deterministic offline runs.
- Metrics: pass@1 (+CI), pass^k, score breakdown, tokens, latency, tool calls, hallucinated codes, safety violations; capability radar.
- Gym-style `McBenchEnv`; adapters: OpenAI-compatible, Anthropic-compatible (via OpenAI-compatible gateway), Codex CLI (guarded stdio MCP proxy); parallel + resume.
- Community pipeline: `mcbench tasks new/validate`, CI validation, templates, governance.
- `mcbench video` explainer, McBench-Vision preview track.

## v0.1.0
- MVP: 5 tasks, mock server, leaderboard, McCut.
