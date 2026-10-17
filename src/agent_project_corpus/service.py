"""The Project Corpus Generator as a lake library agent (lake#263): live worked examples.

A person asks it to record how a solution or pipeline is built (or how a pipeline is changed) on
their own data. One turn reads the person's workspace through lake, asks for one example whose
profile IS that workspace — only its real tables and columns — then replays the reads and actions
so every observation is what the workspace returned (#989), and checks it as the batch CLI does.
No dataset is landed, and the example is answered but never added to the corpus.

Turns arrive on lake's agent bus (lake_bus.py); `POST /v1/turn` answers the same for a direct call.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_project_corpus import lake_bus, solutions
from agent_project_corpus.agent import (
    PROMPT_VERSION,
    PROMPTS,
    _parse,
    compiled_pipeline_defects,
    defects,
    discover_methodologies,
    methodology_context,
    methodology_defects,
    run_defects,
)
from agent_project_corpus.model import gateway_client
from agent_project_corpus.node import Node, replay

CHANGE_WORDS = ("change", "mutat", "modify", "edit", "update", "existing")


def workspace_tables(node: Any) -> list[dict[str, Any]]:
    listed = node.read("list_datasets") or {}
    tables = []
    for dataset in listed.get("datasets") or []:
        if isinstance(dataset, dict) and dataset.get("name"):
            tables.append({"table": f"{dataset.get('database', 'datasets')}.{dataset['name']}",
                           "columns": dataset.get("columns") or [], "rows": dataset.get("rows")})
    return tables


def run_turn(turn: dict[str, Any], client: Any = None, node: Any = None,
             model: str | None = None) -> dict[str, Any]:
    request = (turn.get("request") or turn.get("message") or "").strip()
    owned = node is None
    if owned:
        base, token = turn.get("zetta_base_url"), turn.get("zetta_token")
        if not base or not token:
            return {"ok": False, "error": "no workspace: the turn needs zetta_base_url and "
                                          "zetta_token"}
        node = Node(base_url=base, token=token)
    try:
        solution_entries, solution_registry_unavailable = solutions.discover(node)
        solution_turn = bool(solution_entries)
        methodologies: list[dict[str, Any]] = []
        legacy = False
        if not solution_turn:
            methodologies, legacy = discover_methodologies(node)
        tables = workspace_tables(node)
        if not tables:
            return {"ok": False, "error": "your workspace has no datasets yet: load data first, "
                                          "and the example is built on it"}
        want = "solution" if solution_turn else (
            "mutate" if any(word in request.lower() for word in CHANGE_WORDS) else "create"
        )
        model = model or os.environ.get("PROJECT_CORPUS_MODEL", os.environ.get("AGENT_MODEL", "gpt-4o"))
        registry_context = solutions.context(
            solution_entries,
            solution_registry_unavailable,
        )
        if not solution_turn:
            registry_context += "\n" + methodology_context(methodologies, legacy)
        if client is None:
            # The model is reached through lake with the turn's own key, which counts its tokens
            # in the turn's workspace (lake#248); this agent holds no provider key.
            model_url = turn.get("lake_url") or os.environ.get("LAKE_URL", "")
            model_key = turn.get("lake_token") or turn.get("zetta_token") or ""
            if not model_url or not model_key:
                return {"ok": False, "error": "a turn needs lake_url and its lake_token to reach "
                                              "the model through lake"}
            client = gateway_client(model_url, model_key)
        response = client.chat.completions.create(model=model, messages=[
            {"role": "system", "content": (PROMPTS / f"{PROMPT_VERSION}.md").read_text()},
            {"role": "user", "content":
                f"Produce one `{want}` example. Its profile is THIS workspace, not an invented one: "
                "use only these tables and columns, by these names, in every call:\n"
                + json.dumps(tables[:12]) + (f"\n\nThe person asking wants: {request}" if request
                                             else "")
                + "\n\n" + registry_context}])
        example = _parse(response.choices[0].message.content)
        if example is None:
            return {"ok": False, "error": "no example came back from the model"}
        if solution_turn:
            definition = None
            definition_problems = []
            identifier = str(example.get("solution") or "")
            if solutions.listed_entry(solution_entries, identifier):
                try:
                    definition = solutions.read_definition(node, identifier)
                except Exception as error:  # noqa: BLE001 - the failed read rejects the example
                    definition_problems.append(
                        f"get_solution failed for `{identifier}`: {str(error)[:120]}"
                    )
            problems = (
                definition_problems
                + solutions.generated_defects(example, solution_entries, definition)
                + defects(example)
            )
        else:
            problems = methodology_defects(example, methodologies) + defects(example)
        if problems:
            return {"ok": False, "error": "the example was rejected: " + "; ".join(problems[:3])}
        if solution_turn:
            example["trajectory"], problems = replay(
                node,
                example.get("trajectory") or [],
                solution=str(example["solution"]),
            )
        else:
            example["trajectory"], problems = replay(
                node,
                example.get("trajectory") or [],
                str(example["methodology"]),
            )
        example["observations_real"] = not problems
        if not problems:
            if solution_turn:
                solutions.record_operating_result(example)
                problems = solutions.recorded_defects(example)
            else:
                example["compiled_pipeline"] = next(
                    step["observation"]
                    for step in example["trajectory"]
                    if step.get("call") == "compile_intent"
                )
                problems = compiled_pipeline_defects(
                    example["compiled_pipeline"],
                    str(example["methodology"]),
                    str(example["model_kind"]),
                )
                example["pipeline"] = example["compiled_pipeline"]
                example["run"] = next(
                    step["observation"]
                    for step in example["trajectory"]
                    if step.get("call") == "run"
                )
                problems += run_defects(example["run"])
    finally:
        if owned:
            node.close()
    if problems:
        return {"ok": False, "error": "the example did not hold up against your workspace: "
                                      + "; ".join(problems[:3])}
    example["prompt_version"] = PROMPT_VERSION
    calls = example.get("trajectory") or []
    if solution_turn:
        reply = (
            f"I recorded a worked example on your data, **{example.get('example_id')}**: "
            f"solution `{example.get('solution')}` built and ran in {len(calls)} calls. Every "
            "observation is what your workspace returned, including its policy, label "
            "definitions, and measured readout. It was not added to the Project Agent's corpus."
        )
    else:
        reply = (f"I recorded a worked example on your data, **{example.get('example_id')}**: a "
                 f"`{example.get('kind', want)}` of {len(calls)} calls. Every observation in it is "
                 "what your workspace returned, including the pipeline compiled for "
                 f"{example.get('methodology')}. It was not added to the "
                 "Project Agent's corpus.")
    if legacy:
        reply += " This workspace predates the methodology registry, so only M-1 was allowed."
    if solution_registry_unavailable:
        reply += " Its engine has no solution registry, so this turn had no catalogue solutions."
    return {"ok": True, "reply": reply,
            "result": {"kind": "project_example", "example": example}}


def health() -> dict[str, Any]:
    """The `GET /healthz` answer: the agent, its installed version and its prompt version."""
    return {"ok": True, "agent": "agent-project-corpus",
            "version": importlib.metadata.version("agent-project-corpus"),
            "prompt_version": PROMPT_VERSION}


def serve() -> int:
    token = os.environ.get("AGENT_SERVICE_TOKEN", "")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 (the stdlib's name)
            if self.path == "/healthz":
                self._send(200, health())
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/turn":
                self._send(404, {"ok": False, "error": "not found"})
                return
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                turn = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            except (json.JSONDecodeError, ValueError):
                self._send(400, {"ok": False, "error": "the body is not JSON"})
                return
            try:
                answer = run_turn(turn if isinstance(turn, dict) else {})
            except Exception as error:  # a failed turn is an answer, not a dead worker
                answer = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            self._send(200 if answer.get("ok") else 422, answer)

        def log_message(self, format: str, *args: Any) -> None:
            print(json.dumps({"agent": "agent-project-corpus", "request": format % args}),
                  flush=True)

    port = int(os.environ.get("PORT", "8080"))
    print(json.dumps({"agent": "agent-project-corpus", "listening": port}), flush=True)
    lake_bus.start_from_env(run_turn, "agent-project-corpus")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    return 0
