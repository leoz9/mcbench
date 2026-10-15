# Changelog

## v1.0.0 — 2026-10-15
- 54-task versioned set (9 categories, easy/medium/hard, dev/test split), exact solver references.
- Frozen offline snapshot of real mcp.mcd.cn data (scrubbed) → deterministic offline runs.
- Metrics: pass@1 (+CI), pass^k, score breakdown, tokens, latency, tool calls, hallucinated codes, safety violations; capability radar.
- Gym-style `McBenchEnv`; adapters: OpenAI-compatible, Anthropic-compatible (via OpenAI-compatible gateway), Codex CLI (guarded stdio MCP proxy); parallel + resume.
- Community pipeline: `mcbench tasks new/validate`, CI validation, templates, governance.
- `mcbench video` explainer, McBench-Vision preview track.

## v0.1.0
- MVP: 5 tasks, mock server, leaderboard, McCut.
