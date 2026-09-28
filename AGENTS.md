# AGENTS.md

Read `CLAUDE.md` first (when present). It is the instruction file for this repository and applies
in full to every agent, Codex included. Then `README.md` and `docs/README.md`.

Non-negotiables, restated from `CLAUDE.md` and the org conventions in
[`oramasearch/orama-bridge`](https://github.com/oramasearch/orama-bridge):

- Every change documents itself (`docs/<topic>/*.md`, or the `README.md` where the repo has no
  `docs/`) **in the same commit**, and updates status lines when they stop being true.
- **No AI attribution anywhere.** No `Co-Authored-By`, no "Generated with", no session or model
  trailers, in commits or pull requests.
- No time estimates. The word "seam" is banned.
- Work on a feature branch named for the issue, open a pull request against `main` that references the
  issue, and never push to `main` directly. Commit means push.
- Python with uv (never pip); tests with `uv run pytest` (or `uv run --group dev pytest`). This is a lake library agent: it takes turns from lake's agent bus (`lake_bus.py`, lake `docs/api/agent-bus.md`).
- The methodology work is tracked on the epic https://github.com/oramasearch/zetta/issues/984.
