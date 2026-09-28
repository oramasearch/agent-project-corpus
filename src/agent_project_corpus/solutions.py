"""Live solution discovery and checks for solution worked examples."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_project_corpus.node import NodeError

EVIDENCE_READS = (
    "get_policy",
    "get_experiment",
    "list_ledger",
    "get_monitor",
    "get_roi_readout",
)


def _error_code(value: Any) -> str:
    if isinstance(value, NodeError):
        return value.code
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            return str(error.get("code") or "")
        return str(value.get("code") or "")
    return str(getattr(value, "code", "") or "")


def discover(node: Any) -> tuple[list[dict[str, Any]], bool]:
    """Return this turn's live entries, or no entries for a pre-registry engine."""
    try:
        listed = node.read("list_solutions") or {}
    except Exception as error:  # noqa: BLE001 - the capability code defines compatibility
        if _error_code(error) == "unknown_capability" or "unknown_capability" in str(error):
            return [], True
        raise
    if _error_code(listed) == "unknown_capability":
        return [], True
    entries = listed.get("solutions")
    if not isinstance(entries, list):
        raise ValueError("list_solutions did not return a solutions list")
    return [entry for entry in entries if isinstance(entry, dict)], False


def context(entries: list[dict[str, Any]], unavailable: bool) -> str:
    """Format only the registry observed for this generation turn."""
    if unavailable:
        return (
            "This workspace has no solution registry (unknown_capability), so it has no "
            "catalogue solutions for this turn.\n"
        )
    return "Solution registry for this turn:\n" + json.dumps(entries)


def _entry(entries: list[dict[str, Any]], identifier: str) -> dict[str, Any] | None:
    return next(
        (entry for entry in entries if str(entry.get("id") or "") == identifier),
        None,
    )


def listed_entry(
    entries: list[dict[str, Any]],
    identifier: str,
) -> dict[str, Any] | None:
    """Find an id only in the list observed for this turn."""
    return _entry(entries, identifier)


def read_definition(node: Any, identifier: str) -> dict[str, Any]:
    """Read the selected entry again before deciding whether it can be built."""
    observed = node.read("get_solution", solution=identifier) or {}
    if not isinstance(observed, dict):
        raise ValueError("get_solution did not return an object")
    detailed = observed.get("solution")
    if isinstance(detailed, dict):
        observed = detailed
    if str(observed.get("id") or "") != identifier:
        raise ValueError(f"get_solution did not return `{identifier}`")
    return observed


def _levels(entry: dict[str, Any]) -> set[int]:
    levels = entry.get("levels") or entry.get("capability_levels") or []
    result = set()
    for item in levels:
        value = item.get("level") if isinstance(item, dict) else item
        if isinstance(value, int) and not isinstance(value, bool):
            result.add(value)
    return result


def generated_defects(
    example: dict[str, Any],
    entries: list[dict[str, Any]],
    definition: dict[str, Any] | None = None,
) -> list[str]:
    """Check a proposed solution trajectory before any action is replayed."""
    problems: list[str] = []
    if example.get("kind") != "solution":
        problems.append("a solution generation turn did not return kind `solution`")
    identifier = str(example.get("solution") or "")
    entry = _entry(entries, identifier)
    if entry is None:
        return [f"solution `{identifier or 'missing'}` is not in list_solutions"]
    entry = definition or entry
    if entry.get("status") == "sketch":
        condition = str(entry.get("promotion_condition") or entry.get("issue") or "not promoted")
        return [f"solution `{identifier}` is still a sketch: {condition}"]
    if entry.get("runnable") is not True:
        issue = str(entry.get("issue") or "its implementation issue")
        return [f"solution `{identifier}` is not runnable: {issue}"]

    trajectory = example.get("trajectory") or []
    list_steps = [step for step in trajectory if step.get("call") == "list_solutions"]
    detail_steps = [step for step in trajectory if step.get("call") == "get_solution"]
    create_steps = [step for step in trajectory if step.get("call") == "create_solution"]
    if len(list_steps) != 1 or (trajectory and list_steps[0] is not trajectory[0]):
        problems.append("the solution trajectory must start with one list_solutions call")
    if len(detail_steps) != 1:
        problems.append("the solution trajectory must read one entry with get_solution")
    elif str((detail_steps[0].get("args") or {}).get("solution") or "") != identifier:
        problems.append("get_solution does not read the selected solution")
    if len(create_steps) != 1:
        problems.append("the solution trajectory must build once with create_solution")
        return problems

    create_step = create_steps[0]
    arguments = create_step.get("args") or {}
    if create_step is not trajectory[-1]:
        problems.append("create_solution must be the final generated call before replay runs it")
    if str(arguments.get("solution") or "") != identifier:
        problems.append("create_solution does not carry the selected solution")
    if not str(arguments.get("project") or ""):
        problems.append("create_solution names no project")
    level = arguments.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or level not in range(1, 5):
        problems.append("create_solution level must be an integer from 1 through 4")
    allowed_levels = _levels(entry)
    if allowed_levels and level not in allowed_levels:
        problems.append(f"level `{level}` is not offered by solution `{identifier}`")
    sources = arguments.get("sources")
    if not isinstance(sources, dict) or not sources.get("source") or not sources.get("table"):
        problems.append("create_solution sources must name source and table")
    return problems


def _detailed_entry(example: dict[str, Any]) -> dict[str, Any]:
    for step in example.get("trajectory") or []:
        if step.get("call") != "get_solution":
            continue
        observed = step.get("observation")
        if not isinstance(observed, dict):
            continue
        detailed = observed.get("solution")
        if isinstance(detailed, dict):
            return detailed
        if observed.get("id"):
            return observed
    return {}


def _policy(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "proposed",
        "approval_required": True,
        "definition": entry.get("policy") or entry.get("decision_policy_template"),
        "autonomy": entry.get("autonomy") or entry.get("autonomy_defaults") or [],
        "guardrails": entry.get("guardrails") or [],
    }


def _labels(entry: dict[str, Any]) -> list[dict[str, Any]]:
    roles = entry.get("data_roles") or entry.get("required_data_roles") or []
    definitions = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        definitions.append(
            {
                "role": role.get("role"),
                "required": role.get("required") is True,
                "definition": role.get("description") or "",
            }
        )
    measurement = entry.get("measurement") or entry.get("measurement_design")
    if measurement:
        definitions.append(
            {
                "role": "measured_outcome",
                "required": True,
                "definition": measurement,
            }
        )
    return definitions


def _observed(example: dict[str, Any], call: str) -> Any:
    return next(
        (
            step.get("observation")
            for step in example.get("trajectory") or []
            if step.get("call") == call
        ),
        None,
    )


def record_operating_result(example: dict[str, Any]) -> None:
    """Attach engine-owned definitions and operating evidence to a replayed example."""
    entry = _detailed_entry(example)
    example["solution_definition"] = entry
    example["pipeline"] = _observed(example, "create_solution")
    example["run"] = _observed(example, "run_solution")
    example["policy_proposal"] = _policy(entry)
    example["label_definitions"] = _labels(entry)
    example["owner_signoff"] = {
        "required": True,
        "items": ["policy_proposal", "label_definitions"],
    }
    operations = {}
    unavailable = []
    for call in EVIDENCE_READS:
        value = _observed(example, call)
        operations[call] = value
        if isinstance(value, dict) and value.get("status") == "not_deployed_yet":
            unavailable.append(call)
    example["operations"] = operations
    readout_value = operations["get_roi_readout"]
    readout_status = "available"
    if isinstance(readout_value, dict) and readout_value.get("status") == "not_deployed_yet":
        readout_status = "not_deployed_yet"
        readout_value = None

    reply = str(example.get("reply") or "").strip()
    if unavailable and "not deployed yet" not in reply.lower():
        reply += (
            " The workspace reports these operations as not deployed yet: "
            + ", ".join(unavailable)
            + "."
        )
    if "owner sign-off" not in reply.lower():
        reply += " The proposed policy and label definitions require owner sign-off."
    example["reply"] = reply.strip()
    example["readout"] = {
        "status": readout_status,
        "value": readout_value,
        "explanation": example["reply"],
    }


def recorded_defects(example: dict[str, Any]) -> list[str]:
    """Check that a kept solution example contains a successful operation."""
    problems: list[str] = []
    definition = example.get("solution_definition") or {}
    identifier = str(example.get("solution") or "")
    if str(definition.get("id") or "") != identifier:
        problems.append("get_solution did not return the selected solution definition")
    if definition.get("runnable") is not True:
        problems.append(f"get_solution did not report `{identifier}` as runnable")
    if definition.get("status") == "sketch":
        problems.append(f"get_solution reported `{identifier}` as a sketch")
    create_step = next(
        (
            step
            for step in example.get("trajectory") or []
            if step.get("call") == "create_solution"
        ),
        {},
    )
    level = (create_step.get("args") or {}).get("level")
    allowed_levels = _levels(definition)
    if allowed_levels and level not in allowed_levels:
        problems.append(f"get_solution did not offer level `{level}` for `{identifier}`")
    created = example.get("pipeline")
    if not isinstance(created, dict) or not (
        created.get("graph") or created.get("graph_id")
    ):
        problems.append("create_solution did not return a composed graph")
    run = example.get("run")
    if not isinstance(run, dict):
        problems.append("run_solution did not return a run result")
    else:
        status = str(run.get("status") or "").lower()
        if status in {"failed", "cancelled", "canceled"}:
            problems.append(f"run_solution ended with status `{status}`")
    proposal = example.get("policy_proposal") or {}
    if proposal.get("approval_required") is not True:
        problems.append("the proposed policy does not require owner approval")
    if not isinstance(example.get("label_definitions"), list):
        problems.append("the solution has no label definitions")
    signoff = example.get("owner_signoff") or {}
    if signoff.get("required") is not True:
        problems.append("the policy and label definitions do not require owner sign-off")
    readout = example.get("readout") or {}
    if readout.get("status") not in {"available", "not_deployed_yet"}:
        problems.append("the solution has no observed readout status")

    reply = str(example.get("reply") or "")
    lowered = reply.lower()
    if any(word in lowered for word in ("guaranteed", "guarantees", "odds of success", "pricing")):
        problems.append("the reply promises a result, pricing, or odds of success")
    roi_figure = re.search(
        r"(?:roi|return).{0,40}(?:\$\s*\d|\d+(?:\.\d+)?\s*%)",
        reply,
        re.IGNORECASE,
    )
    if roi_figure:
        problems.append("the reply promises an ROI figure")
    return problems
