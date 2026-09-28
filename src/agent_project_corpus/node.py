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

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
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


# Reads ground the design in the workspace. compile_intent is the one replayed action: the engine,
# rather than the generating model, must decide the selected methodology's pipeline shape.
REPLAYABLE_READS = {
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
REPLAYABLE_ACTIONS = {"compile_intent"}


def replay(
    node: Node,
    trajectory: list[dict[str, Any]],
    methodology: str | None = None,
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
            step["observation"] = observed
            step["observed"] = True
        except Exception as error:  # noqa: BLE001 — the failure IS the observation
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
    return trajectory, problems
