# Governance

- **Versioned releases.** Task set + snapshot are versioned together (`v1.0`). Community tasks merge into `tasks/community/`, and are folded into the next `vX.Y` release by maintainers; released task files are immutable — fixes go into a new version.
- **Held-out split.** Each release has a `test` split (~1/3). Model submissions must report dev and test separately; prompt/agent tuning on test is not allowed. Maintainers may rotate a fresh held-out batch from community submissions at each minor release (kept private until the release after).
- **Leaderboard submissions** via the "Model submission" issue template with full trace bundle; maintainers re-verify traces with the verifier (`mcbench leaderboard <dir>`).
- **Compliance.** Write-blocking is non-negotiable; no other brands, gambling or superstition content; no personal data or real coupon codes.
