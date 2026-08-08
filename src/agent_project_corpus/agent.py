"""Generate the project creation/mutation corpus.

This trains the MAIN agent — the one that builds Pipelines and changes them. It is a tool-calling
agent, so an example is a trajectory whose every call after the first is conditioned on what the
previous call returned.

SFT here, RLVR after. The order is measured rather than preferred: a campaign against a policy
that never emits a pipeline returns a uniformly zero reward, and a group with equal rewards has
zero advantage — GRPO takes a null step and cannot learn. So this corpus exists to get the policy
to *sometimes* build a correct pipeline; the loop sharpens it from there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent_project_corpus.node import Node, land_profile, replay

PROMPT_VERSION = "v1"
PROMPTS = Path(__file__).parent / "prompts"

# The correctness profile each methodology must satisfy, and what it must NOT carry. These mirror
# the cores in zetta's plan_templates.cpp so an SFT example grades the same way the engine does.
REQUIRED: dict[str, set[str]] = {
    "gbdt": {"point_in_time", "leakage_free", "calibrated", "holdout"},
    "classifier": {"point_in_time", "leakage_free", "calibrated", "holdout"},
    "forecast": {"temporal_validation", "backtest", "holdout"},
    "anomaly": {"threshold_governed"},
    "retrieval": {"index", "grounded_in_data"},
    "uplift": {"incrementality", "holdout"},
}
FORBIDDEN: dict[str, set[str]] = {
    # No probability to calibrate, and a calibrator fit on content-held-out rows re-introduces the
    # leak temporal validation exists to prevent.
    "forecast": {"calibrated"},
    # No label to leak or calibrate.
    "anomaly": {"calibrated", "leakage_free"},
    "retrieval": {"calibrated", "leakage_free", "holdout"},
}


def _parse(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    body = fence.group(1) if fence else text[text.find("{"): text.rfind("}") + 1]
    try:
        example = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return example if example.get("example_id") and example.get("trajectory") else None


def defects(example: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    trajectory = example.get("trajectory") or []
    pipeline = example.get("pipeline") or {}

    if len(trajectory) < 2:
        problems.append("a single call is not a trajectory — nothing is conditioned on anything")

    # THE property. A call justified by the user's ask rather than an observation is a scripted
    # step, and a scripted trajectory is a lookup with extra steps.
    for step in trajectory[1:]:
        because = str(step.get("because", "")).strip()
        if not because:
            problems.append(f"call `{step.get('call')}` has no `because` — it is a scripted step")
        elif not any(other.get("call", "") in because for other in trajectory):
            problems.append(f"call `{step.get('call')}` justifies itself by the ask, not by an "
                            f"observation from a previous call")

    kind = str(example.get("kind", "create"))
    if kind == "mutate" and not example.get("before"):
        problems.append("a mutation with no `before` cannot teach what must NOT change")
    if kind == "create" and example.get("before"):
        problems.append("a creation carries a `before` pipeline")

    methodology = str(pipeline.get("model_kind", ""))
    if methodology:
        missing = REQUIRED.get(methodology, set()) - {k for k, v in pipeline.items() if v}
        if missing:
            problems.append(f"`{methodology}` is missing {sorted(missing)} — that is the "
                            f"neighbouring methodology's shape, not this one's")
        present = FORBIDDEN.get(methodology, set()) & {k for k, v in pipeline.items() if v}
        if present:
            problems.append(f"`{methodology}` carries {sorted(present)}, which does not apply to it")

    if not str(example.get("reply", "")).strip():
        problems.append("no reply — the user is told nothing about what was built")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate project creation/mutation examples.")
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--model", default=os.environ.get("PROJECT_CORPUS_MODEL", "gpt-4o"))
    parser.add_argument("--out", type=Path, default=Path("corpus"))
    args = parser.parse_args()

    client = OpenAI()
    # Without a node the observations stay written, which is the defect #989 describes. Allowed,
    # but the corpus records which examples were actually observed so nobody has to guess later.
    node: Node | None = None
    if os.environ.get("ZETTA_BASE_URL") and os.environ.get("ZETTA_TOKEN"):
        node = Node()
    else:
        print("no ZETTA_BASE_URL/ZETTA_TOKEN — observations will be WRITTEN, not observed (#989)")
    system = (PROMPTS / f"{PROMPT_VERSION}.md").read_text()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"project-sft-{PROMPT_VERSION}.jsonl"

    seen: list[str] = []
    kept = rejected = mutations = 0
    for index in range(args.examples):
        # Alternate so mutations are half the corpus rather than an afterthought — changing a
        # Pipeline is the harder half of the product and the easier half to under-represent.
        want = "mutate" if index % 2 else "create"
        avoid = ("\n\nAlready generated, pick something further away:\n"
                 + "\n".join(f"- {s}" for s in seen)) if seen else ""
        response = client.chat.completions.create(model=args.model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Produce one `{want}` example." + avoid}])

        example = _parse(response.choices[0].message.content)
        if example is None:
            print(f"[{index+1}/{args.examples}] unparseable — skipped"); rejected += 1; continue

        # Make the observations REAL (#989). The generating model writes observations that are
        # coherent by construction — one author wrote both the observation and the call that
        # responded to it — which is exactly the property a live node does not have. Land the
        # profile, replay the read calls, and keep what the node actually returned.
        if node is not None:
            try:
                land_profile(node, example.get("profile") or {}, Path("/tmp/apc-staging"))
                example["trajectory"], replay_problems = replay(node, example["trajectory"])
                example["observations_real"] = not replay_problems
            except Exception as error:  # noqa: BLE001
                replay_problems = [f"could not land or replay: {str(error)[:120]}"]
                example["observations_real"] = False
            if replay_problems:
                print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · "
                      f"{replay_problems[0]}")
                rejected += 1
                continue

        problems = defects(example)
        if problems:
            print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · {problems[0]}")
            rejected += 1
            continue

        example["prompt_version"] = PROMPT_VERSION
        with path.open("a") as handle:
            handle.write(json.dumps(example) + "\n")
        seen.append(f"{example['example_id']} ({example.get('kind')})")
        kept += 1
        mutations += example.get("kind") == "mutate"
        print(f"[{index+1}/{args.examples}] {example['example_id']} · {example.get('kind')} · "
              f"{len(example['trajectory'])} calls · kept")

    if node is not None:
        node.close()
    print(f"kept={kept} ({mutations} mutations) rejected={rejected} -> {path}")
    return 0
