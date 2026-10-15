# Task design

**v1.2 totals: 120 text tasks** = Core v1.0 54 (dev 36 / test 18) + Hard 65 (dev 43 / test 22, see [hard.md](hard.md)), plus 12 synthetic McBench-Vision frames (multimodal dimension).

## Core (v1.0)

- 54 tasks = 5 hand-curated (legacy) + 49 procedural, 9 categories × 6, difficulty easy/medium/hard.
- Split: **dev 36 / test 18** (held-out). Test prompts are public (deterministic offline env), but official leaderboard numbers are reported on `--split all` and per split; tuning on test is against policy (see GOVERNANCE.md).
- Generator: `scripts/gen_tasks.py --seed 20261015`. Each task stores `reference` = solver optimum or infeasibility proof on snapshot v1.0.
- Schema (`mcbench/data/tasks/v1.0.json`): `id, category, difficulty, split, title, prompt, constraints, objective, expected_outcome, user_replies?, adversarial?, dimensions, author, reference`.

Constraint keys: `max_payable, min_kind{汉堡/饮品/小食/甜品/主食}, max_kcal, min_kcal, min_protein, max_sodium, sugar_free_drinks, no_spicy, no_coffee, people, min_items, use_coupon, …` (see `mcbench/units.py:evaluate`).
