# Releases

One page per tagged release, newest first. A page states what the release includes, what it does
not include, known issues, verification output, and where the image runs. The first release also
lists everything in the agent: its checks, its routes, its bus protocol and its environment.

A release has one `vX.Y.Z` name shared by the Git tag, the GitHub release and the private Docker
Hub image tag `oramasearch/agent-project-corpus:vX.Y.Z`. The image tag names the digest already
built from the tag; it is never produced by a second build.

| Release | Date | Summary |
|---|---|---|
| [v0.2.0](v0.2.0.md) | 2026-10-25 | Security-review fixes (constant-time service token, refused when unset; a turn's credential only to the service's own `LAKE_URL`) and a behaviour change: Lake turns are refused until the sandbox workspace (lake#1202) |
| [v0.1.0](v0.1.0.md) | 2026-10-17 | The first release: the Project Corpus Agent as a Lake library agent (agent bus, `/v1/turn`, model through Lake's gateway), prompt v3 with runnable solution and methodology checks and replay, and the batch command line |

`pyproject.toml`'s `[project].version` is the one place the version is set; `GET /healthz` reports
it, and `tests/test_release.py` fails when that version has no page here.
