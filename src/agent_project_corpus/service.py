"""The Project Corpus Generator as a lake library agent (lake#263): a worked example on your data.

A person asks it to record how a pipeline is built (or changed) on their own data. One turn reads
the person's workspace through lake's read-only path, asks for one `create` (or `mutate`) example
whose profile IS that workspace — only its real tables and columns — then replays the example's
read calls against the workspace so every observation is what the workspace returned (#989), and
checks it as the batch CLI does. Nothing is landed or written: the CLI's `land_profile` stays the
CLI's, and the example is answered, never added to the corpus.

Turns arrive on lake's agent bus (lake_bus.py); `POST /v1/turn` answers the same for a direct call.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from openai import OpenAI

from agent_project_corpus import lake_bus
from agent_project_corpus.agent import PROMPT_VERSION, PROMPTS, _parse, defects
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
        tables = workspace_tables(node)
        if not tables:
            return {"ok": False, "error": "your workspace has no datasets yet: load data first, "
                                          "and the example is built on it"}
        want = "mutate" if any(word in request.lower() for word in CHANGE_WORDS) else "create"
        model = model or os.environ.get("PROJECT_CORPUS_MODEL", os.environ.get("AGENT_MODEL", "gpt-4o"))
        response = (client or OpenAI()).chat.completions.create(model=model, messages=[
            {"role": "system", "content": (PROMPTS / f"{PROMPT_VERSION}.md").read_text()},
            {"role": "user", "content":
                f"Produce one `{want}` example. Its profile is THIS workspace, not an invented one: "
                "use only these tables and columns, by these names, in every call:\n"
                + json.dumps(tables[:12]) + (f"\n\nThe person asking wants: {request}" if request
                                             else "")}])
        example = _parse(response.choices[0].message.content)
        if example is None:
            return {"ok": False, "error": "no example came back from the model"}
        example["trajectory"], problems = replay(node, example.get("trajectory") or [])
        example["observations_real"] = not problems
        problems += defects(example)
    finally:
        if owned:
            node.close()
    if problems:
        return {"ok": False, "error": "the example did not hold up against your workspace: "
                                      + "; ".join(problems[:3])}
    example["prompt_version"] = PROMPT_VERSION
    calls = example.get("trajectory") or []
    reply = (f"I recorded a worked example on your data, **{example.get('example_id')}**: a "
             f"`{example.get('kind', want)}` of {len(calls)} calls. Every observation in it is what "
             "your workspace returned, not what the model expected. It was not added to the "
             "Project Agent's corpus.")
    return {"ok": True, "reply": reply,
            "result": {"kind": "project_example", "example": example}}


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
                self._send(200, {"ok": True, "agent": "agent-project-corpus",
                                 "prompt_version": PROMPT_VERSION})
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
