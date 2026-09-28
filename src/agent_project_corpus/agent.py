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

from agent_project_corpus.node import Node, NodeError, land_profile, replay

PROMPT_VERSION = "v2"
PROMPTS = Path(__file__).parent / "prompts"

LEGACY_M1 = {
    "id": "M-1",
    "name": "Tabular supervised learning",
    "family": "The tabular decision core",
    "model_kinds": ["gbdt", "classifier"],
    "solutions": [],
    "inputs": [],
    "outputs": ["scores"],
    "metrics": ["held-out metrics"],
    "runnable": True,
    "partial": False,
    "issue": "",
}


def _unknown_capability(error: Exception) -> bool:
    if isinstance(error, NodeError):
        return error.code == "unknown_capability"
    code = str(getattr(error, "code", ""))
    return code == "unknown_capability" or "unknown_capability" in str(error)


def discover_methodologies(node: Any) -> tuple[list[dict[str, Any]], bool]:
    """Read the engine registry, or use the documented pre-registry M-1 behavior."""
    try:
        listed = node.read("list_methodologies") or {}
    except Exception as error:  # noqa: BLE001 - capability errors define the fallback
        if _unknown_capability(error):
            return [dict(LEGACY_M1)], True
        raise
    methodologies = listed.get("methodologies") or []
    return [entry for entry in methodologies if isinstance(entry, dict)], False


def methodology_context(methodologies: list[dict[str, Any]], legacy: bool) -> str:
    note = ""
    if legacy:
        note = (
            "This workspace predates list_methodologies. Only M-1 with GBDT "
            "classification may be used.\n"
        )
    return note + "Methodology registry for this turn:\n" + json.dumps(methodologies)


def methodology_defects(
    example: dict[str, Any],
    methodologies: list[dict[str, Any]],
) -> list[str]:
    methodology_id = str(example.get("methodology") or "")
    model_kind = str(example.get("model_kind") or "")
    selected = next(
        (entry for entry in methodologies if str(entry.get("id")) == methodology_id),
        None,
    )
    if selected is None:
        return [f"methodology `{methodology_id or 'missing'}` is not in list_methodologies"]
    if not selected.get("runnable"):
        issue = str(selected.get("issue") or "its implementation issue")
        name = str(selected.get("name") or methodology_id)
        return [f"{name} ({methodology_id}) is not supported yet: {issue}"]
    model_kinds = {str(kind) for kind in selected.get("model_kinds") or []}
    if model_kind not in model_kinds:
        return [
            f"model_kind `{model_kind or 'missing'}` is not runnable under "
            f"{methodology_id}; list_methodologies allows {sorted(model_kinds)}"
        ]
    return []


def compiled_pipeline_defects(
    compiled: Any,
    methodology: str,
    model_kind: str,
) -> list[str]:
    if not isinstance(compiled, dict):
        return ["compile_intent did not return a pipeline object"]
    reported_methodology = compiled.get("methodology")
    if reported_methodology and str(reported_methodology) != methodology:
        return [
            f"compile_intent returned methodology `{reported_methodology}` instead of "
            f"`{methodology}`"
        ]
    if compiled.get("runnable") is False:
        return [f"compile_intent returned a pipeline that cannot run under {methodology}"]
    reported_kind = compiled.get("model_kind")
    if reported_kind and str(reported_kind) != model_kind:
        return [
            f"compile_intent returned model_kind `{reported_kind}` instead of `{model_kind}`"
        ]
    return []


def run_defects(run: Any) -> list[str]:
    if not isinstance(run, dict):
        return ["run did not return a trainer result object"]
    if run.get("engine") == "structural":
        return ["run was structural and trained no methodology"]
    status = str(run.get("status") or "").lower()
    if status in {"failed", "cancelled", "canceled"}:
        return [f"the methodology run ended with status `{status}`"]
    return []


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

    methodology = str(example.get("methodology") or "")
    model_kind = str(example.get("model_kind") or "")
    pipeline_model_kind = str(pipeline.get("model_kind") or "")
    if not methodology:
        problems.append("the example does not name its methodology")
    if not model_kind:
        problems.append("the example does not name its model_kind")
    if pipeline_model_kind != model_kind:
        problems.append(
            "the pipeline model_kind does not match the example's model_kind"
        )
    compile_steps = [
        step for step in trajectory if step.get("call") == "compile_intent"
    ]
    if len(compile_steps) != 1:
        problems.append("the trajectory must compile exactly one pipeline with compile_intent")
    elif str((compile_steps[0].get("args") or {}).get("methodology") or "") != methodology:
        problems.append("compile_intent does not carry the example's methodology")
    elif compile_steps[0] is not trajectory[-1]:
        problems.append("compile_intent must be the final generated call before replay runs it")

    if not str(example.get("reply", "")).strip():
        problems.append("no reply — the user is told nothing about what was built")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate project creation/mutation examples.")
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--model", default=os.environ.get("PROJECT_CORPUS_MODEL", "gpt-4o"))
    parser.add_argument("--out", type=Path, default=Path("corpus"))
    args = parser.parse_args()

    if not (os.environ.get("ZETTA_BASE_URL") and os.environ.get("ZETTA_TOKEN")):
        print(
            "no ZETTA_BASE_URL/ZETTA_TOKEN — refusing to record examples whose "
            "methodology cannot be checked or compiled"
        )
        return 2
    client = OpenAI()
    node = Node()
    system = (PROMPTS / f"{PROMPT_VERSION}.md").read_text()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"project-sft-{PROMPT_VERSION}.jsonl"

    seen: list[str] = []
    kept = rejected = mutations = 0
    for index in range(args.examples):
        methodologies, legacy = discover_methodologies(node)
        # Alternate so mutations are half the corpus rather than an afterthought — changing a
        # Pipeline is the harder half of the product and the easier half to under-represent.
        want = "mutate" if index % 2 else "create"
        avoid = ("\n\nAlready generated, pick something further away:\n"
                 + "\n".join(f"- {s}" for s in seen)) if seen else ""
        response = client.chat.completions.create(
            model=args.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Produce one `{want}` example.\n\n"
                        + methodology_context(methodologies, legacy)
                        + avoid
                    ),
                },
            ],
        )

        example = _parse(response.choices[0].message.content)
        if example is None:
            print(f"[{index+1}/{args.examples}] unparseable — skipped")
            rejected += 1
            continue

        problems = methodology_defects(example, methodologies) + defects(example)
        if problems:
            print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · {problems[0]}")
            rejected += 1
            continue

        # Make the observations REAL (#989). The generating model writes observations that are
        # coherent by construction — one author wrote both the observation and the call that
        # responded to it — which is exactly the property a live node does not have. Land the
        # profile, replay the read calls, and keep what the node actually returned.
        try:
            land_profile(node, example.get("profile") or {}, Path("/tmp/apc-staging"))
            example["trajectory"], replay_problems = replay(
                node,
                example["trajectory"],
                str(example["methodology"]),
            )
            example["observations_real"] = not replay_problems
        except Exception as error:  # noqa: BLE001
            replay_problems = [f"could not land or replay: {str(error)[:120]}"]
            example["observations_real"] = False
        if replay_problems:
            print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · "
                  f"{replay_problems[0]}")
            rejected += 1
            continue

        example["compiled_pipeline"] = next(
            step["observation"]
            for step in example["trajectory"]
            if step.get("call") == "compile_intent"
        )
        compile_problems = compiled_pipeline_defects(
            example["compiled_pipeline"],
            str(example["methodology"]),
            str(example["model_kind"]),
        )
        if compile_problems:
            print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · "
                  f"{compile_problems[0]}")
            rejected += 1
            continue
        example["pipeline"] = example["compiled_pipeline"]
        example["run"] = next(
            step["observation"]
            for step in example["trajectory"]
            if step.get("call") == "run"
        )
        run_problems = run_defects(example["run"])
        if run_problems:
            print(f"[{index+1}/{args.examples}] {example['example_id']} REJECTED · "
                  f"{run_problems[0]}")
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

    node.close()
    print(f"kept={kept} ({mutations} mutations) rejected={rejected} -> {path}")
    return 0
