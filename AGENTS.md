# AGENTS.md

Read `CLAUDE.md` first (when present). It is the instruction file for this repository and applies
in full to every coding agent. Then `README.md` and `docs/README.md` (where present).

Non-negotiables:

- Every change documents itself (`docs/<topic>/*.md`, or the `README.md` where the repo has no
  `docs/`) **in the same commit**, and updates status lines when they stop being true.
- **No AI attribution anywhere.** No AI `Co-Authored-By` trailer, no "Generated with", no session or
  model trailers, in commits, pull requests, tags or release notes.
- No time or size estimates: do the work and report concrete results.
- The word "seam" is banned. Name the mechanism instead: interface, extension point, boundary,
  injected dependency.
- Conventional Commits. Work on a feature branch and open a pull request; never push to the default
  branch directly. Reference issues without auto-close keywords.
- Python with uv (never pip): `uv sync`, then `uv run --group dev pytest`. This is a Lake library
  agent: it takes turns from Lake's agent bus (`lake_bus.py`; Lake's `docs/api/agent-bus.md`).
