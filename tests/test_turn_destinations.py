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


def test_lakes_workspace_route_is_used_with_the_turns_credential(monkeypatch, sent):
    monkeypatch.setenv("LAKE_URL", LAKE)
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": ROUTE, "zetta_token": "lat.task.secret",
         "lake_token": "lat.task.secret"}
    )
    # The empty workspace ends the turn before the model, after reading through Lake.
    assert not answer["ok"] and "no datasets" in answer["error"]
    assert sent, "the workspace was never read"
    assert all(
        request.url.host == "lake-prod.lake.svc.cluster.local"
        and request.url.port in (None, 80)
        and request.url.path.startswith("/w/ws-1/workspaces/cust-1/zetta/v1/")
        for request in sent
    )
    assert all(request.headers["authorization"] == "Bearer lat.task.secret" for request in sent)


def test_the_default_port_is_the_same_origin(monkeypatch, sent):
    monkeypatch.setenv("LAKE_URL", LAKE)
    route = "http://LAKE-PROD.lake.svc.cluster.local/w/ws-1/workspaces/cust-1/zetta"
    answer = service.run_turn(
        {"request": "x", "zetta_base_url": route, "zetta_token": "t", "lake_token": "t"}
    )
    assert "no datasets" in answer["error"]
    assert sent


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
