"""The Project Corpus Generator as a lake library agent (lake#263): a worked example on your data,
its observations replayed against your workspace, nothing written."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from agent_project_corpus import service

EXAMPLE = json.loads(Path("tests/fixtures/project-example-v2.json").read_text())
SOLUTION_EXAMPLE = json.loads(
    Path("tests/fixtures/project-solution-v3.json").read_text()
)
M1 = {
    "id": "M-1",
    "name": "Tabular supervised learning",
    "model_kinds": ["gbdt", "classifier"],
    "runnable": True,
    "issue": "",
}
M3 = {
    "id": "M-3",
    "name": "Segmentation / clustering",
    "model_kinds": ["segmentation", "clustering"],
    "runnable": False,
    "issue": "zetta#1042",
}
SOLUTION = {
    "id": "S-live",
    "name": "Retention actions",
    "composition": [{"methodology": "M-1", "minimum_level": 1}],
    "levels": [{"level": 1, "name": "Assist"}],
    "autonomy": [{"action_class": "task", "autonomy": "A1"}],
    "data_roles": [
        {
            "role": "outcome",
            "required": True,
            "description": "Observed retention outcome",
        }
    ],
    "policy": "Act above an owner-approved threshold",
    "measurement": "Compare treatment with the holdout",
    "guardrails": ["contact cap"],
    "runnable": True,
    "status": "available",
    "issue": "",
}


class Scripted:
    def __init__(self, content: str) -> None:
        self.sent = []
        message = SimpleNamespace(content=content)
        reply = SimpleNamespace(choices=[SimpleNamespace(message=message)])

        def create(**kwargs):
            self.sent.append(kwargs)
            return reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


class Workspace:
    """The person's workspace through lake, with every capability recorded."""

    def __init__(
        self,
        datasets,
        methodologies=None,
        legacy=False,
        solution_entries=None,
        missing_optional=None,
    ):
        self.datasets = datasets
        self.methodologies = methodologies or [M1, M3]
        self.legacy = legacy
        self.solution_entries = solution_entries
        self.missing_optional = set(missing_optional or [])
        self.reads = []
        self.acts = []

    def read(self, capability, **params):
        self.reads.append(capability)
        if capability == "list_solutions":
            if self.solution_entries is None:
                error = RuntimeError("unknown_capability: list_solutions")
                error.code = "unknown_capability"
                raise error
            return {"solutions": self.solution_entries}
        if capability == "get_solution":
            entry = next(
                item
                for item in self.solution_entries
                if item["id"] == params["solution"]
            )
            return {"solution": entry}
        if capability == "list_methodologies":
            if self.legacy:
                error = RuntimeError("unknown_capability: list_methodologies")
                error.code = "unknown_capability"
                raise error
            return {"methodologies": self.methodologies}
        if capability == "list_datasets":
            return {"datasets": self.datasets}
        if capability in self.missing_optional:
            error = RuntimeError(f"unknown_capability: {capability}")
            error.code = "unknown_capability"
            raise error
        if capability == "get_policy":
            return {"policy": {"version": 2, "autonomy": "A1"}}
        if capability == "get_experiment":
            return {"experiment": {"holdout": "configured"}}
        if capability == "list_ledger":
            return {"entries": [{"kind": "action"}]}
        if capability == "get_monitor":
            return {"monitor": {"status": "within_bounds"}}
        if capability == "get_roi_readout":
            return {"readout": {"incrementality": "measured against holdout"}}
        return {"columns": ["account_id", "churned"], "rows": 200}

    def act(self, capability, **body):
        self.acts.append((capability, body))
        if capability == "create_solution":
            return {
                "project": body["project"],
                "solution": body["solution"],
                "level": body["level"],
                "graph": "S-live CL-1",
            }
        if capability == "run_solution":
            return {"run_id": "solution-run-1", "status": "succeeded"}
        if capability == "run":
            return {
                "run_id": "run-1",
                "engine": "M-1",
                "status": "succeeded",
                "metrics": {"held_out_auc": 0.82},
            }
        return {
            "project": body["project"],
            "graph": "workspace churn",
            "methodology": body["methodology"],
            "runnable": True,
        }

    def close(self):
        pass


def test_a_runnable_methodology_is_compiled_and_recorded():
    workspace = Workspace([{"database": "datasets", "name": "ux_review_churn",
                            "columns": ["account_id", "churned"], "rows": 200}])
    client = Scripted(json.dumps(EXAMPLE))
    answer = service.run_turn({"request": "a churn pipeline"}, client, workspace, "m")
    prompt = client.sent[0]["messages"][1]["content"]
    assert "datasets.ux_review_churn" in prompt and "`create`" in prompt
    assert answer["ok"], answer
    assert answer["result"]["example"]["observations_real"]
    assert answer["result"]["example"]["methodology"] == "M-1"
    assert answer["result"]["example"]["model_kind"] == "gbdt"
    assert answer["result"]["example"]["compiled_pipeline"]["methodology"] == "M-1"
    assert answer["result"]["example"]["pipeline"]["methodology"] == "M-1"
    assert answer["result"]["example"]["run"]["metrics"]["held_out_auc"] == 0.82
    assert workspace.reads[:2] == ["list_solutions", "list_methodologies"]
    assert workspace.reads.count("list_datasets") >= 2, "listed, then replayed"
    assert [capability for capability, _ in workspace.acts] == ["compile_intent", "run"]
    assert workspace.acts[0][1]["methodology"] == "M-1"
    assert workspace.acts[1][1]["dataset_path"] == "datasets.ux_review_churn"


def test_an_unsupported_methodology_is_rejected_with_its_issue():
    example = deepcopy(EXAMPLE)
    example["methodology"] = "M-3"
    example["model_kind"] = "segmentation"
    example["pipeline"]["model_kind"] = "segmentation"
    example["trajectory"][-1]["args"]["methodology"] = "M-3"
    workspace = Workspace([{"name": "accounts"}])
    answer = service.run_turn(
        {"request": "segment customers"},
        Scripted(json.dumps(example)),
        workspace,
        "m",
    )
    assert not answer["ok"]
    assert "Segmentation / clustering (M-3)" in answer["error"]
    assert "zetta#1042" in answer["error"]
    assert workspace.acts == []


def test_an_old_engine_allows_only_m1_and_says_it_used_the_fallback():
    workspace = Workspace([{"name": "accounts"}], legacy=True)
    answer = service.run_turn(
        {"request": "predict churn"},
        Scripted(json.dumps(EXAMPLE)),
        workspace,
        "m",
    )
    assert answer["ok"], answer
    assert "predates the methodology registry" in answer["reply"]
    prompt = answer["result"]["example"]
    assert prompt["methodology"] == "M-1"
    assert workspace.reads[:2] == ["list_solutions", "list_methodologies"]


def test_a_runnable_solution_is_created_run_and_recorded_from_live_state():
    workspace = Workspace(
        [
            {
                "database": "datasets",
                "name": "customers",
                "columns": ["account_id", "retained"],
                "rows": 200,
            }
        ],
        solution_entries=[SOLUTION],
    )
    client = Scripted(json.dumps(SOLUTION_EXAMPLE))

    answer = service.run_turn(
        {"request": "build retention actions"},
        client,
        workspace,
        "m",
    )

    assert answer["ok"], answer
    example = answer["result"]["example"]
    assert example["solution"] == "S-live"
    assert example["pipeline"]["graph"] == "S-live CL-1"
    assert example["run"]["status"] == "succeeded"
    assert example["policy_proposal"]["approval_required"] is True
    assert example["label_definitions"][0]["role"] == "outcome"
    assert example["readout"]["status"] == "available"
    assert example["readout"]["value"]["readout"]
    assert example["owner_signoff"]["required"] is True
    assert workspace.reads[0] == "list_solutions"
    assert workspace.reads.count("list_solutions") == 2
    assert workspace.reads.count("get_solution") == 2
    assert [capability for capability, _ in workspace.acts] == [
        "create_solution",
        "run_solution",
    ]


def test_unknown_optional_solution_reads_are_recorded_as_not_deployed():
    workspace = Workspace(
        [{"database": "datasets", "name": "customers"}],
        solution_entries=[SOLUTION],
        missing_optional={"get_monitor", "get_roi_readout"},
    )

    answer = service.run_turn(
        {"request": "build retention actions"},
        Scripted(json.dumps(SOLUTION_EXAMPLE)),
        workspace,
        "m",
    )

    assert answer["ok"], answer
    example = answer["result"]["example"]
    assert example["readout"]["status"] == "not_deployed_yet"
    assert "not deployed yet" in example["reply"]


def test_a_solution_not_marked_runnable_is_never_created():
    unavailable = {**SOLUTION, "runnable": False, "issue": "zetta#1110"}
    workspace = Workspace(
        [{"database": "datasets", "name": "customers"}],
        solution_entries=[unavailable],
    )

    answer = service.run_turn(
        {"request": "build retention actions"},
        Scripted(json.dumps(SOLUTION_EXAMPLE)),
        workspace,
        "m",
    )

    assert not answer["ok"]
    assert "zetta#1110" in answer["error"]
    assert workspace.reads[:3] == ["list_solutions", "list_datasets", "get_solution"]
    assert workspace.acts == []


def test_a_solution_whose_run_fails_is_not_recorded():
    class FailedRunWorkspace(Workspace):
        def act(self, capability, **body):
            result = super().act(capability, **body)
            if capability == "run_solution":
                return {"run_id": "solution-run-1", "status": "failed"}
            return result

    workspace = FailedRunWorkspace(
        [{"database": "datasets", "name": "customers"}],
        solution_entries=[SOLUTION],
    )

    answer = service.run_turn(
        {"request": "build retention actions"},
        Scripted(json.dumps(SOLUTION_EXAMPLE)),
        workspace,
        "m",
    )

    assert not answer["ok"]
    assert "run_solution" in answer["error"]
    assert "failed" in answer["error"]


def test_a_change_request_asks_for_a_mutation():
    client = Scripted("nothing")
    service.run_turn({"request": "change my existing pipeline"}, client,
                     Workspace([{"name": "a"}]), "m")
    assert "`mutate`" in client.sent[0]["messages"][1]["content"]


def test_an_empty_workspace_is_told_to_load_data():
    answer = service.run_turn({"request": "x"}, Scripted("{}"), Workspace([]), "m")
    assert not answer["ok"] and "load data" in answer["error"]


def test_a_qualified_dataset_name_is_taken_apart_for_get_dataset():
    from agent_project_corpus.node import Node
    sent = {}

    class Client:
        def get(self, path, params):
            sent.update(params)
            return type("R", (), {"raise_for_status": lambda self: None,
                                  "json": lambda self: {"ok": True, "value": {}}})()

    node = Node.__new__(Node)
    node.client = Client()
    node.read("get_dataset", table="datasets.ux_review_churn")
    assert sent == {"dataset": "ux_review_churn", "database": "datasets"}


def test_node_preserves_a_capability_error_code():
    from agent_project_corpus.node import Node, NodeError

    class Client:
        def get(self, path, params):
            return type(
                "R",
                (),
                {
                    "json": lambda self: {
                        "ok": False,
                        "error": {
                            "code": "not_supported",
                            "message": "Segmentation is not supported: zetta#1042",
                        },
                    }
                },
            )()

    node = Node.__new__(Node)
    node.client = Client()
    try:
        node.read("list_methodologies")
        raise AssertionError("the capability failure was not raised")
    except NodeError as error:
        assert error.code == "not_supported"
        assert "zetta#1042" in str(error)


def test_a_turn_calls_its_model_through_lakes_gateway_with_the_turns_key(monkeypatch):
    """lake#248: the model is lake's `/openai/v1`, with the turn's own key, never a provider key."""
    import httpx

    from agent_project_corpus import model

    seen: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(EXAMPLE)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(service, "gateway_client", lambda url, token: model.gateway_client(
        url, token, http_client=httpx.Client(transport=httpx.MockTransport(gateway))))
    workspace = Workspace([{"database": "datasets", "name": "ux_review_churn",
                            "columns": ["account_id", "churned"], "rows": 200}])
    monkeypatch.setenv("LAKE_URL", "http://lake:8080")
    # The turn's own lake_url is never used: the key goes to this service's LAKE_URL (#9).
    answer = service.run_turn({"request": "a churn pipeline", "lake_url": "http://elsewhere:9",
                               "lake_token": "lat.task.secret"}, None, workspace, "m")
    assert answer["ok"], answer
    assert [str(request.url) for request in seen] == ["http://lake:8080/openai/v1/chat/completions"]
    assert seen[0].headers["authorization"] == "Bearer lat.task.secret"

    refused = service.run_turn({"request": "a churn pipeline"}, None, workspace, "m")
    assert not refused["ok"] and "lake_token" in refused["error"]
    assert len(seen) == 1

    monkeypatch.delenv("LAKE_URL", raising=False)
    refused = service.run_turn({"request": "a churn pipeline", "lake_url": "http://lake:8080",
                                "lake_token": "lat.task.secret"}, None, workspace, "m")
    assert not refused["ok"] and "LAKE_URL is not set" in refused["error"]
    assert len(seen) == 1
