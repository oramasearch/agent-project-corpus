# SPDX-License-Identifier: MIT

"""A turn's credential goes only to Lake at LAKE_URL, never to an address the request names (#9)."""

from __future__ import annotations

import httpx
import pytest

from agent_project_corpus import node as node_module
from agent_project_corpus import service

LAKE = "http://lake-prod.lake.svc.cluster.local:80"
ROUTE = LAKE + "/w/ws-1/workspaces/cust-1/zetta"


@pytest.fixture
def sent(monkeypatch):
    """Every request any Node or model client makes, answered with an empty workspace."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"ok": True, "value": {"solutions": [], "methodologies": [], "datasets": []}}
        )

    real = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(answer)
        return real(*args, **kwargs)

    monkeypatch.setattr(node_module.httpx, "Client", client)
    monkeypatch.setattr(
        service, "gateway_client", lambda url, token: pytest.fail(f"model called at {url}")
    )
    return requests


@pytest.mark.parametrize(
    "zetta_base_url",
    [
        "http://attacker.example/w/ws-1/workspaces/cust-1/zetta",
        "https://lake-prod.lake.svc.cluster.local/w/ws-1/workspaces/cust-1/zetta",
        "http://lake-prod.lake.svc.cluster.local:8080/w/ws-1/workspaces/cust-1/zetta",
        "http://lake-prod.lake.svc.cluster.local.attacker.example/w/ws-1/zetta",
        "http://user@lake-prod.lake.svc.cluster.local/w/ws-1/zetta",
        "http://lake-prod.lake.svc.cluster.local:80@attacker.example/zetta",
        "http://lake-prod.lake.svc.cluster.local/w/ws-1/zetta?next=http://attacker.example",
        "file:///etc/passwd",
        "lake-prod.lake.svc.cluster.local/w/ws-1/zetta",
        "http://lake-prod.lake.svc.cluster.local:notaport/zetta",
    ],
)
def test_a_workspace_address_off_lakes_origin_is_refused_before_any_request(
    monkeypatch, sent, zetta_base_url
):
    monkeypatch.setenv("LAKE_URL", LAKE)
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": zetta_base_url, "zetta_token": "lat.task.secret",
         "lake_token": "lat.task.secret"}
    )
    assert not answer["ok"]
    assert "zetta_base_url is not Lake's workspace route" in answer["error"]
    assert sent == []


@pytest.fixture
def built(monkeypatch):
    """The arguments of every Node a turn builds."""
    nodes: list[dict] = []
    real = service.Node

    def node(**kwargs):
        nodes.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(service, "Node", node)
    return nodes


def test_lakes_workspace_route_is_used_with_the_turns_credential(monkeypatch, sent, built):
    monkeypatch.setenv("LAKE_URL", LAKE)
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": ROUTE, "zetta_token": "lat.task.secret",
         "lake_token": "lat.task.secret"}
    )
    # The route is accepted; the turn then stops because a Lake turn changes nothing (#8).
    assert answer == {"ok": False, "error": service.READ_ONLY_REFUSAL}
    assert built == [{"base_url": ROUTE, "token": "lat.task.secret", "read_only": True}]
    assert sent == []


def test_the_default_port_is_the_same_origin(monkeypatch, sent, built):
    monkeypatch.setenv("LAKE_URL", LAKE)
    route = "http://LAKE-PROD.lake.svc.cluster.local/w/ws-1/workspaces/cust-1/zetta"
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": route, "zetta_token": "t", "lake_token": "t"}
    )
    assert answer["error"] == service.READ_ONLY_REFUSAL
    assert [node["base_url"] for node in built] == [route]


def test_without_lake_url_no_turn_sends_its_credential(monkeypatch, sent):
    monkeypatch.delenv("LAKE_URL", raising=False)
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": ROUTE, "zetta_token": "t", "lake_token": "t",
         "lake_url": LAKE}
    )
    assert not answer["ok"] and "LAKE_URL is not set" in answer["error"]
    assert sent == []


def test_a_workspace_route_must_be_under_lake_urls_path():
    lake = "http://lake:80/base"
    assert service.workspace_url("http://lake/base/w/1/zetta", lake) == "http://lake/base/w/1/zetta"
    assert service.workspace_url("http://lake/basement/w/1/zetta", lake) is None
    assert service.workspace_url("http://lake/other/w/1/zetta", lake) is None
    assert service.workspace_url("http://lake/base/../admin", lake) is None
