"""A Lake turn changes nothing in the person's workspace (#8).

Lake grants this agent's task credential only `workspace_query`, `workspace_openapi` and
`get_agent_task`, and its catalogue says the agent changes nothing. So a turn's node never sends
an action, and a turn is refused before the model runs rather than failing at replay.
"""

from __future__ import annotations

import httpx
import pytest

from agent_project_corpus import node as node_module
from agent_project_corpus import service
from agent_project_corpus.node import Node, NodeError, replay


@pytest.fixture
def sent(monkeypatch):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "value": {"datasets": []}})

    real = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(answer)
        return real(*args, **kwargs)

    monkeypatch.setattr(node_module.httpx, "Client", client)
    return requests


@pytest.mark.parametrize("action", ["compile_intent", "run", "create_solution", "run_solution",
                                    "add_dataset"])
def test_a_read_only_node_never_sends_an_action(sent, action):
    node = Node(base_url="http://lake/w/1/workspaces/c/zetta", token="t", read_only=True)
    with pytest.raises(NodeError) as raised:
        node.act(action, project="p")
    assert raised.value.code == "read_only"
    assert sent == []
    node.read("list_datasets")
    assert [request.method for request in sent] == ["GET"]


def test_an_owner_node_still_acts(sent):
    node = Node(base_url="http://zetta:4800", token="owner")
    node.act("compile_intent", project="p")
    assert [request.method for request in sent] == ["POST"]


def test_replay_on_a_read_only_node_records_every_action_as_refused(sent):
    node = Node(base_url="http://lake/w/1/workspaces/c/zetta", token="t", read_only=True)
    trajectory = [
        {"call": "list_datasets", "args": {}},
        {"call": "compile_intent", "args": {"project": "p", "intent": "churn"}},
        {"call": "create_solution", "args": {"project": "p", "solution": "S-1"}},
        {"call": "run_solution", "args": {"project": "p", "graph": "g"}},
    ]
    steps, problems = replay(node, trajectory, "M-1")
    assert all(request.method == "GET" for request in sent)
    refused = [step for step in steps if step["call"] != "list_datasets"]
    assert refused and all(step["observed"] is False for step in refused)
    assert all("may only read" in step["observation"]["error"] for step in refused)
    assert any("compile_intent" in problem for problem in problems)


def test_a_lake_turn_is_refused_before_the_model_and_sends_no_action(monkeypatch, sent):
    monkeypatch.setattr(
        service, "gateway_client", lambda url, token: pytest.fail("the model was called")
    )
    monkeypatch.setenv("LAKE_URL", "http://lake")
    answer = service.run_turn(
        {"request": "a churn pipeline", "lake_url": "http://lake", "lake_token": "t",
         "zetta_base_url": "http://lake/w/1/workspaces/c/zetta", "zetta_token": "t"}
    )
    assert answer == {"ok": False, "error": service.READ_ONLY_REFUSAL}
    assert all(request.method != "POST" for request in sent)
