"""The Project Corpus Generator as a lake library agent (lake#263): a worked example on your data,
its observations replayed against your workspace, nothing written."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from agent_project_corpus import service

EXAMPLE = json.loads(Path("tests/fixtures/project-example-v2.json").read_text())
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

    def __init__(self, datasets, methodologies=None, legacy=False):
        self.datasets = datasets
        self.methodologies = methodologies or [M1, M3]
        self.legacy = legacy
        self.reads = []
        self.acts = []

    def read(self, capability, **params):
        self.reads.append(capability)
        if capability == "list_methodologies":
            if self.legacy:
                error = RuntimeError("unknown_capability: list_methodologies")
                error.code = "unknown_capability"
                raise error
            return {"methodologies": self.methodologies}
        if capability == "list_datasets":
            return {"datasets": self.datasets}
        return {"columns": ["account_id", "churned"], "rows": 200}

    def act(self, capability, **body):
        self.acts.append((capability, body))
        return {
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
    assert workspace.reads[0] == "list_methodologies"
    assert workspace.reads.count("list_datasets") >= 2, "listed, then replayed"
    assert [capability for capability, _ in workspace.acts] == ["compile_intent"]
    assert workspace.acts[0][1]["methodology"] == "M-1"


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
    assert workspace.reads[0] == "list_methodologies"


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
