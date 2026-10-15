# 共建任务 / Contributing tasks

1. `pip install -e .[dev]`
2. `mcbench tasks new --id community-<handle>-01 --category budget --difficulty medium` → `tasks/community/community-<handle>-01.yml`
3. Fill in `prompt`, `constraints`, `objective`, `expected_outcome`, **`dimensions` (required)**, `author`.
4. `mcbench tasks validate tasks/community/` — checks schema and solves the task on snapshot v1.0 (feasible tasks must have a solution; infeasible tasks must be *proven* infeasible).
5. Open a PR (template checklist). CI re-validates and runs offline scripted baselines.
6. Merged community tasks enter the next minor release (`v1.1`, …); you are credited in `CONTRIBUTORS.md` and the task `author` field on the leaderboard.

Review checklist: realistic user need · unambiguous constraints (or deliberately ambiguous with `user_replies`) · no other brands · no gambling/superstition · no personal data · solver-validated.
