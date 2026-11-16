# SPDX-License-Identifier: MIT

"""The version is set once, in pyproject.toml, and every release of it has a notes page."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

from agent_project_corpus import service

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_the_installed_package_has_the_project_version():
    assert importlib.metadata.version("agent-project-corpus") == project_version()


def test_the_release_notes_exist_for_the_project_version():
    version = project_version()
    notes = ROOT / "docs" / "releases" / f"v{version}.md"
    assert notes.is_file(), f"no release notes at {notes.relative_to(ROOT)}"
    heading = notes.read_text().splitlines()[0]
    assert heading.startswith("# ") and f"v{version}" in heading
    index = (ROOT / "docs" / "releases" / "README.md").read_text()
    assert f"[v{version}](v{version}.md)" in index


def test_healthz_reports_the_project_version():
    answer = service.health()
    assert answer["ok"] is True
    assert answer["version"] == project_version()
    assert answer["prompt_version"] == service.PROMPT_VERSION
