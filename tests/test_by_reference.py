"""Task credentials by reference (lake#871, lake docs/api/agent-bus.md).

A claim asks Lake for `credentials: by_reference`: the body arrives with no credential, and every
call made for the task carries this agent's bus credential and `X-Lake-Agent-Task: <task id>`. A
Lake from before lake#871 refuses the field; the claim is asked again and the body's own credential
is used, as before.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from typing import Any

import httpx

from agent_project_corpus import lake_bus, model, service
from agent_project_corpus.node import Node
from test_service import EXAMPLE, Workspace

TASK = {"task_id": "t1", "customer_id": "cust-1", "workspace_id": "ws-1", "kind": "api"}


class BusLake:
    """lake's bus in memory. `supports_by_reference` False is a Lake from before lake#871."""

    def __init__(self, supports_by_reference: bool) -> None:
        self.supports_by_reference = supports_by_reference
        self.claims: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.stop = threading.Event()
        self.received = False

    def send(self, method: str, url: str, headers: dict[str, str],
             body: bytes | None) -> tuple[int, str]:
        self.headers.append(headers)
        capability = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        if capability == "receive_agent_tasks":
            tasks = [] if self.received else [{"sequence": 1, **TASK}]
            self.received = True
            if not tasks:
                self.stop.set()
            return 200, json.dumps({"ok": True, "value": {"tasks": tasks, "next_sequence": 2}})
        arguments = json.loads(body or b"{}")
        if capability == "claim_agent_task":
            self.claims.append(arguments)
            if "credentials" in arguments and not self.supports_by_reference:
                return 400, json.dumps({"ok": False, "error": {
                    "code": "invalid_input", "message": "unexpected field credentials",
                    "path": "/credentials"}})
            by_reference = arguments.get("credentials") == "by_reference"
            credential = "" if by_reference else "lat.t1.secret"
            value = {**TASK, "body": {"request": "hi", "lake_token": credential,
                                      "zetta_token": credential}}
            if by_reference:
                value["credentials"] = "by_reference"
            return 200, json.dumps({"ok": True, "value": value})
        return 200, json.dumps({"ok": True, "value": {}})


def handed_body(lake: BusLake) -> dict[str, Any]:
    handed: list[dict[str, Any]] = []
    bus = lake_bus.LakeBus("http://lake", "bus-token", "agent-project-corpus", send=lake.send)
    lake_bus.work(bus, lambda body: handed.append(body) or {"ok": True}, lake.stop, workers=1)
    assert len(handed) == 1, handed
    return handed[0]


def test_a_claim_asks_by_reference_and_the_turn_holds_no_task_credential():
    lake = BusLake(supports_by_reference=True)
    body = handed_body(lake)
    assert lake.claims == [{"task_id": "t1", "agent": "agent-project-corpus", "credentials": "by_reference"}]
    assert body["lake_token"] == body["zetta_token"] == "bus-token", \
        "the turn calls Lake with the bus credential"
    assert body["lake_headers"] == {"X-Lake-Agent-Task": "t1"}
    assert lake_bus.task_headers(body) == {"X-Lake-Agent-Task": "t1"}
    # Bus calls themselves never name a task: Lake would answer them as the task.
    assert all(lake_bus.TASK_HEADER not in headers for headers in lake.headers)


def test_a_lake_from_before_by_reference_is_claimed_again_with_the_credential_in_the_body():
    lake = BusLake(supports_by_reference=False)
    body = handed_body(lake)
    assert lake.claims == [
        {"task_id": "t1", "agent": "agent-project-corpus", "credentials": "by_reference"},
        {"task_id": "t1", "agent": "agent-project-corpus"},
    ]
    assert body["lake_token"] == "lat.t1.secret", "the body's own credential is used, as before"
    assert "lake_headers" not in body
    assert lake_bus.task_headers(body) == {}


def test_a_claim_refused_for_another_reason_is_not_asked_again():
    assert not lake_bus.refuses_by_reference(
        lake_bus.BusError("invalid_input", "task_id is required"))
    assert not lake_bus.refuses_by_reference(lake_bus.BusError("forbidden", "credentials"))
    assert lake_bus.refuses_by_reference(
        lake_bus.BusError("invalid_input", "unexpected field credentials"))


def test_task_headers_take_only_the_task_header():
    assert lake_bus.task_headers({"lake_headers": {"X-Lake-Agent-Task": "t1",
                                                   "Authorization": "Bearer other"}}) == {
        "X-Lake-Agent-Task": "t1"}
    assert lake_bus.task_headers({"lake_headers": "t1"}) == {}
    assert lake_bus.task_headers({}) == {}


ROUTE = "http://lake/w/ws-1/workspaces/cust-1/zetta"


def by_reference_turn() -> dict[str, Any]:
    """A turn as `lake_bus` hands it after a claim by reference."""
    claimed = {**TASK, "credentials": "by_reference",
               "body": {"request": "a churn pipeline", "lake_url": "http://lake",
                        "lake_token": "", "zetta_base_url": ROUTE, "zetta_token": ""}}
    return lake_bus.task_credentials("bus-token", claimed)


def test_the_workspace_node_of_a_by_reference_turn_names_its_task(monkeypatch):
    built: list[Node] = []
    real = service.Node

    def node(*args, **kwargs):
        built.append(real(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(service, "Node", node)
    monkeypatch.setenv("LAKE_URL", "http://lake")
    answer = service.run_turn(by_reference_turn())
    assert answer == {"ok": False, "error": service.READ_ONLY_REFUSAL}
    assert len(built) == 1
    headers = built[0].client.headers
    assert headers["authorization"] == "Bearer bus-token"
    assert headers["x-lake-agent-task"] == "t1"


def test_the_model_call_of_a_by_reference_turn_names_its_task(monkeypatch):
    seen: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(EXAMPLE)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(service, "gateway_client", lambda url, token, **kw: model.gateway_client(
        url, token, http_client=httpx.Client(transport=httpx.MockTransport(gateway)), **kw))
    workspace = Workspace([{"database": "datasets", "name": "ux_review_churn",
                            "columns": ["account_id", "churned"], "rows": 200}])
    monkeypatch.setenv("LAKE_URL", "http://lake:8080")
    service.run_turn(by_reference_turn(), None, workspace, "m")
    assert seen, "the model was never called"
    assert all(request.headers["authorization"] == "Bearer bus-token" for request in seen)
    assert all(request.headers["x-lake-agent-task"] == "t1" for request in seen)


def test_an_in_body_turn_and_the_environments_token_send_no_task_header(monkeypatch):
    in_body = Node(base_url=ROUTE, token="lat.t1.secret", read_only=True)
    monkeypatch.setenv("ZETTA_TOKEN", "env-token")
    from_env = Node(base_url="http://zetta", token=None, headers={"X-Lake-Agent-Task": "t1"})
    try:
        assert "x-lake-agent-task" not in in_body.client.headers
        assert from_env.client.headers["authorization"] == "Bearer env-token"
        assert "x-lake-agent-task" not in from_env.client.headers
    finally:
        in_body.client.close()
        from_env.client.close()
