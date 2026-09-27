"""The Project Corpus Generator as a lake library agent (lake#263): a worked example on your data,
its observations replayed against your workspace, nothing written."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_project_corpus import service

EXAMPLE = json.loads(Path("corpus/project-sft-v1.jsonl").read_text().splitlines()[0])


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
    """The person's workspace through lake: reads only, recorded."""

    def __init__(self, datasets):
        self.datasets, self.reads, self.acts = datasets, [], []

    def read(self, capability, **params):
        self.reads.append(capability)
        if capability == "list_datasets":
            return {"datasets": self.datasets}
        return {"columns": ["account_id", "churned"], "rows": 200}

    def act(self, capability, **body):
        self.acts.append(capability)

    def close(self):
        pass


def test_an_example_on_the_persons_data_is_replayed_and_nothing_is_written():
    workspace = Workspace([{"database": "datasets", "name": "ux_review_churn",
                            "columns": ["account_id", "churned"], "rows": 200}])
    client = Scripted(json.dumps(EXAMPLE))
    answer = service.run_turn({"request": "a churn pipeline"}, client, workspace, "m")
    prompt = client.sent[0]["messages"][1]["content"]
    assert "datasets.ux_review_churn" in prompt and "`create`" in prompt
    assert answer["ok"], answer
    assert answer["result"]["example"]["observations_real"]
    assert workspace.reads.count("list_datasets") >= 2, "listed, then replayed"
    assert workspace.acts == [], "nothing is landed in the person's workspace"


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
