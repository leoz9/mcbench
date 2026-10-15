# 🍔 McBench — pelicans on bicycles are out, ordering McDonald's is in

[![CI](https://github.com/leoz9/mcbench/actions/workflows/ci.yml/badge.svg)](https://github.com/leoz9/mcbench/actions/workflows/ci.yml)
[![Leaderboard](https://img.shields.io/badge/leaderboard-live-ffc72c)](https://cv.leozto.sbs/mcbench/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**McBench is a multi-dimensional, community-built benchmark for tool-using LLM agents.** Agents order a meal through the official **McDonald's China MCP server** (stores → menu → combo details → nutrition → coupons → price quote) and submit a plan. A programmatic verifier recomputes price and nutrition; an exact solver provides reference optima and infeasibility proofs. **Dry-run only** — ordering / account-mutating tools are blocked.

[中文 README（主）](README.md) · [Leaderboard](https://cv.leozto.sbs/mcbench/) · [Methodology](docs/methodology.md) · [Contribute tasks](docs/contributing-tasks.md)

```bash
pip install -e . && mcbench demo   # offline frozen snapshot + scripted baselines; no token, no API key
```

## v1.2: 120 tasks (Core 54 + Hard 65); McBench-Hard is the headline split (scored on its 22-task test split)
32 exact-optimum tasks, including near-boundary infeasibility, strict tool budgets, a simulated user who changes requirements mid-episode, prompt injection in tool outputs, distractor tools and hidden constraints. The goal is a 30–50% strict pass rate for frontier models. Overall = 0.6·Hard + 0.4·Core (test split). Scores use a multi-dimensional rubric with penalties ([docs/scoring.md](docs/scoring.md), [docs/hard.md](docs/hard.md)). Full model runs on Hard are pending: all 8 Codex models were probed and respond, but the Codex usage limit was reached. Run `scripts/run_hard.sh` to resume.

## v1.0 results (legacy scoring) (54 tasks, offline frozen snapshot recorded from mcp.mcd.cn, 2026-10-15)

| Agent | Runtime | Avg score | pass@1 (95% CI) | pass^3 (9 test tasks) | calls/task | safety violations |
|---|---|---:|---:|---:|---:|---:|
| demo-planner | scripted exact solver (upper reference, not an LLM) | 95.4 | 100% | – | 110.6 | 0 |
| **gpt-6-luna** | Codex CLI | **91.9** | **88.9%** [78,95] | **66.7%** | 8.3 | 0 |
| **gpt-5.6-luna** | Codex CLI | 87.6 | 81.5% [69,90] | 33.3% | 11.3 | 0 |
| demo-greedy | scripted | 53.0 | 11.1% | – | 5.0 | 0 |
| demo-hasty | scripted (tries to place orders) | 6.3 | 0% | – | 4.0 | 54 |

![radar](docs/media/radar_v1.png)

Dimensions: tool use · constraint satisfaction · cost optimization · nutrition reasoning · safety · clarification · infeasibility detection · efficiency · consistency (pass^k) · multimodal (McBench-Vision preview).

## Join us
Tasks are data. `mcbench tasks new` → edit YAML (dimensions + author required) → `mcbench tasks validate` → PR. CI validates against the frozen snapshot with the solver and runs offline baselines; merged tasks ship in the next `v1.x` with author credit. See [CONTRIBUTING.md](CONTRIBUTING.md), [GOVERNANCE.md](GOVERNANCE.md) (versioned releases, held-out split policy), and the model-submission issue template.

## Harness
Gym-style `McBenchEnv` (`reset/step`, sparse reward = score/100), adapters for OpenAI-compatible, Anthropic-compatible and Codex CLI (guarded stdio MCP proxy), `--jobs` parallelism, `--resume`, `--k` / `--seeds` for pass^k, `--live` optional. Docs: [env-api](docs/env-api.md), [scoring](docs/scoring.md), [task design](docs/task-design.md), [vision](docs/vision.md).

Independent contest entry; not an official McDonald's product. Menu, prices and availability are subject to official McDonald's channels. MIT.
