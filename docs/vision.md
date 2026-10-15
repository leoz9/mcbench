# McBench-Vision (multimodal track, preview)

Goal: identify McDonald's items in a frame/video, then compute price & nutrition through MCP.

- Dataset: `mcbench vision` builds `mcbench/data/vision/v1.0/` — 12 **synthetic** frames (Pillow-rendered placeholders from snapshot menu names; NOT official photography) with gold item codes, MCP-recomputed payable and kcal. Split dev 9 / test 3.
- Metrics: item precision / recall / F1, price MAE, kcal MAE.
- Adapter contract: model receives the image + the McBench guarded MCP tools; must `submit_order` with the identified items.
- Status: an oracle upper bound is computed; **no real vision model has been run yet** (Codex CLI non-interactive exec image input not wired in this release). Contributions welcome: licensed real photos / short clips under the same schema, and an OpenAI-compatible vision adapter.
