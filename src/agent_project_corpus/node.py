"""Walk a trajectory against a REAL node, so the observations were actually observed.

The corpus previously carried observations written by the generating model. They were coherent by
construction — one author wrote both the observation and the call that responded to it — which is
exactly the property a real node does not have. #989.

This lands the generated profile's records, replays the trajectory's calls against `/v1`, and
records what came back. An observation no call returned is then *detectable* rather than merely
implausible.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import httpx


class NodeError(RuntimeError):
    """A capability failure with the engine's stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Node:
    """Read/act against a live Zetta node. Raises rather than returning a plausible empty result."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 read_only: bool = False) -> None:
        # A read-only node (a Lake turn's) never sends an action: Lake grants the turn's
        # credential reads only, and its catalogue says this agent changes nothing (#8).
        self.read_only = read_only
        self.base = (base_url or os.environ["ZETTA_BASE_URL"]).rstrip("/")
        self.client = httpx.Client(
            base_url=self.base,
            headers={"Authorization": f"Bearer {token or os.environ['ZETTA_TOKEN']}"},
            timeout=180.0)

    def read(self, capability: str, **params: Any) -> Any:
        # get_dataset names its table `dataset` (a model also writes `table`) and takes the
        # database apart: "datasets.accounts" is database "datasets", dataset "accounts".
        if capability == "get_dataset":
            name = str(params.pop("table", "") or params.get("dataset") or "")
            if name:
                params["dataset"] = name
            if "." in name and "database" not in params:
                database, table = name.split(".", 1)
                params = {**params, "database": database, "dataset": table}
        response = self.client.get(f"/v1/{capability}", params=params)
        return self._value(response)

    def act(self, capability: str, **body: Any) -> Any:
        if self.read_only:
            raise NodeError(
                "read_only",
                f"`{capability}` changes the workspace, and this turn may only read it",
            )
        response = self.client.post(f"/v1/{capability}", json=body)
        return self._value(response)

    @staticmethod
    def _value(response: httpx.Response) -> Any:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error") or {}
            raise NodeError(
                str(error.get("code") or "engine_error"),
                str(error.get("message") or "the engine refused the capability"),
            )
        response.raise_for_status()
        if isinstance(payload, dict):
            return payload.get("value", payload)
        return payload

    def close(self) -> None:
        self.client.close()


def _value(column: dict[str, Any], rng: random.Random, row: int) -> Any:
    name, kind = column.get("name", "").lower(), str(column.get("type", "string")).lower()
    if "id" in name:
        return f"{name[:6]}_{row:06d}"
    if any(k in kind for k in ("time", "date")):
        return rng.randint(0, 1200)
    if any(k in kind for k in ("float", "double", "decimal")):
        return round(rng.lognormvariate(5.0, 1.0), 3)
    if any(k in kind for k in ("int", "long")):
        return rng.randint(0, 5000)
    if "bool" in kind:
        return rng.random() < 0.2
    return f"{name.replace('_', '-')}-{rng.randrange(500):03d}"


def land_profile(node: Node, profile: dict[str, Any], staging: Path,
                 max_rows: int = 4_000) -> list[str]:
    """Materialize the profile's tables on the node so the trajectory has something real to read.

    Null fractions are honoured: if the profile says a column is null on 11% of rows, the landed
    table really is. That is the fact a trajectory's `because` will point at, so it has to be true
    of the data rather than only of the prose.
    """
    rng = random.Random(7)
    staging.mkdir(parents=True, exist_ok=True)
    landed: list[str] = []
    for table in profile.get("tables", []):
        columns = [c if isinstance(c, dict) else {"name": c, "type": "string"}
                   for c in table.get("columns", [])]
        count = min(int(table.get("rows") or 1_000), max_rows)
        path = staging / f"{table.get('database')}.{table.get('name')}.jsonl"
        with path.open("w") as handle:
            for row in range(count):
                record = {}
                for column in columns:
                    null_fraction = float(column.get("null_fraction") or 0.0)
                    record[column["name"]] = (None if rng.random() < null_fraction
                                              else _value(column, rng, row))
                handle.write(json.dumps(record) + "\n")
        node.act("add_dataset", path=str(path.resolve()),
                 database=table["database"], table_name=table["name"])
        landed.append(f"{table['database']}.{table['name']}")
    return landed


# Reads ground the design in the workspace. Replayed actions make the engine, rather than the
# generating model, decide a methodology's pipeline shape or a solution's composed graph.
REPLAYABLE_READS = {
    "list_solutions",
    "get_solution",
    "get_policy",
    "get_experiment",
    "list_ledger",
    "get_monitor",
    "get_roi_readout",
    "list_datasets",
    "get_dataset",
    "list_models",
    "get_model",
    "list_projects",
    "get_project",
    "model_health",
    "list_connections",
    "list_indexes",
}
REPLAYABLE_ACTIONS = {"compile_intent", "create_solution", "run_solution"}
OPTIONAL_SOLUTION_READS = {
    "get_policy",
    "get_experiment",
    "list_ledger",
    "get_monitor",
    "get_roi_readout",
}


def _run_compiled_pipeline(
    node: Node,
    trajectory: list[dict[str, Any]],
    compile_step: dict[str, Any],
    compiled: Any,
) -> tuple[dict[str, Any], str | None]:
    compile_args = compile_step.get("args") or {}
    project = ""
    graph = ""
    if isinstance(compiled, dict):
        project = str(compiled.get("project") or "")
        graph = str(
            compiled.get("graph_id")
            or compiled.get("graph")
            or compiled.get("name")
            or ""
        )
    project = project or str(compile_args.get("project") or "")
    arguments = {"project": project, "graph": graph}
    dataset_step = next(
        (step for step in trajectory if step.get("call") == "get_dataset"),
        None,
    )
    if dataset_step:
        dataset_args = dataset_step.get("args") or {}
        dataset = dataset_args.get("dataset") or dataset_args.get("table")
        if dataset:
            arguments["dataset_path"] = str(dataset)
    run_step = {
        "call": "run",
        "args": arguments,
        "because": "compile_intent returned the runnable graph this call executes",
    }
    if not project or not graph:
        run_step["observation"] = {
            "error": "compile_intent did not return a project and graph reference"
        }
        run_step["observed"] = False
        return run_step, "compile_intent did not return a project and graph reference for run"
    try:
        run_step["observation"] = node.act("run", **arguments)
        run_step["observed"] = True
        return run_step, None
    except Exception as error:  # noqa: BLE001 - the failure is the observation
        run_step["observation"] = {"error": str(error)[:200]}
        run_step["observed"] = False
        return run_step, f"`run` failed against the node: {str(error)[:120]}"


def _solution_run_step(
    create_step: dict[str, Any],
    created: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build the run call from the graph returned by create_solution."""
    create_args = create_step.get("args") or {}
    project = ""
    graph = ""
    if isinstance(created, dict):
        project = str(created.get("project") or "")
        graph = str(created.get("graph") or created.get("graph_id") or "")
    project = project or str(create_args.get("project") or "")
    if not project or not graph:
        return None, "create_solution did not return a project and graph for run_solution"
    return {
        "call": "run_solution",
        "args": {"project": project, "graph": graph},
        "because": "create_solution returned the composed graph this call executes",
    }, None


def _solution_evidence_steps(project: str) -> list[dict[str, Any]]:
    """Read the operating evidence after a solution run succeeds."""
    return [
        {
            "call": "get_policy",
            "args": {"project": project},
            "because": "run_solution returned the completed solution run",
        },
        {
            "call": "get_experiment",
            "args": {"project": project},
            "because": "run_solution returned the completed solution run",
        },
        {
            "call": "list_ledger",
            "args": {"project": project},
            "because": "run_solution returned the completed solution run",
        },
        {
            "call": "get_monitor",
            "args": {"project": project},
            "because": "run_solution returned the completed solution run",
        },
        {
            "call": "get_roi_readout",
            "args": {"project": project},
            "because": "run_solution returned the completed solution run",
        },
    ]


def replay(
    node: Node,
    trajectory: list[dict[str, Any]],
    methodology: str | None = None,
    solution: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Replace written observations with what the node actually returned.

    Returns the trajectory and any problems. A call that fails is recorded as a failure rather
    than dropped — an agent that never sees its own failures cannot learn to avoid them.
    """
    problems: list[str] = []
    for step in trajectory:
        call = step.get("call")
        if call not in REPLAYABLE_READS and call not in REPLAYABLE_ACTIONS:
            continue
        try:
            arguments = dict(step.get("args") or {})
            if call in REPLAYABLE_ACTIONS:
                if methodology:
                    arguments["methodology"] = methodology
                    step["args"] = arguments
                observed = node.act(call, **arguments)
            else:
                observed = node.read(call, **arguments)
            if call in OPTIONAL_SOLUTION_READS and isinstance(observed, dict):
                error = observed.get("error")
                code = error.get("code") if isinstance(error, dict) else observed.get("code")
                if code == "unknown_capability":
                    observed = {
                        "status": "not_deployed_yet",
                        "capability": call,
                        "code": "unknown_capability",
                    }
            if isinstance(observed, dict) and isinstance(observed.get("error"), dict):
                returned_error = observed["error"]
                raise NodeError(
                    str(returned_error.get("code") or "engine_error"),
                    str(returned_error.get("message") or "the capability failed"),
                )
            step["observation"] = observed
            step["observed"] = True
            if call == "compile_intent":
                run_step, run_problem = _run_compiled_pipeline(
                    node,
                    trajectory,
                    step,
                    observed,
                )
                trajectory.append(run_step)
                if run_problem:
                    problems.append(run_problem)
            if call == "create_solution":
                run_step, run_problem = _solution_run_step(step, observed)
                if run_step:
                    trajectory.append(run_step)
                if run_problem:
                    problems.append(run_problem)
            if call == "run_solution":
                status = ""
                if isinstance(observed, dict):
                    status = str(observed.get("status") or "").lower()
                if status in {"failed", "cancelled", "canceled"}:
                    problems.append(f"`run_solution` ended with status `{status}`")
                else:
                    project = str(arguments.get("project") or "")
                    trajectory.extend(_solution_evidence_steps(project))
        except Exception as error:  # noqa: BLE001 — the failure IS the observation
            optional_missing = (
                call in OPTIONAL_SOLUTION_READS
                and getattr(error, "code", "") == "unknown_capability"
            )
            if optional_missing:
                step["observation"] = {
                    "status": "not_deployed_yet",
                    "capability": call,
                    "code": "unknown_capability",
                }
                step["observed"] = True
                continue
            step["observation"] = {"error": str(error)[:200]}
            step["observed"] = False
            problems.append(f"`{call}` failed against the node: {str(error)[:120]}")
    if not any(step.get("observed") for step in trajectory):
        problems.append("no call in this trajectory was actually executed — every observation is "
                        "still written rather than observed")
    if methodology and not any(
        step.get("call") == "compile_intent" and step.get("observed")
        for step in trajectory
    ):
        problems.append(
            "the pipeline was not compiled by `compile_intent` with its methodology"
        )
    if methodology and not any(
        step.get("call") == "run" and step.get("observed")
        for step in trajectory
    ):
        problems.append("the compiled methodology did not produce an observed run")
    if solution and not any(
        step.get("call") == "list_solutions" and step.get("observed")
        for step in trajectory
    ):
        problems.append("the solution registry was not observed with `list_solutions`")
    if solution and not any(
        step.get("call") == "get_solution" and step.get("observed")
        for step in trajectory
    ):
        problems.append(f"the selected solution `{solution}` was not observed with `get_solution`")
    if solution and not any(
        step.get("call") == "create_solution" and step.get("observed")
        for step in trajectory
    ):
        problems.append(f"the solution `{solution}` was not built with `create_solution`")
    if solution and not any(
        step.get("call") == "run_solution" and step.get("observed")
        for step in trajectory
    ):
        problems.append(f"the solution `{solution}` did not produce an observed run")
    if solution and not any(
        step.get("call") == "get_roi_readout" and step.get("observed")
        for step in trajectory
    ):
        problems.append(f"the solution `{solution}` did not read its ROI readout")
    return trajectory, problems
