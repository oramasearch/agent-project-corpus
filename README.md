# agent-project-corpus

Training corpus for **the main agent** — the one that builds and operates catalogue Solutions,
and creates or mutates projects
([zetta#986](https://github.com/oramasearch/zetta/issues/986)).

It takes a **project profile** (what Auto-Suggest proposed) plus the user's intent, and builds a
catalogue Solution or Pipeline. It changes a Pipeline when asked. That is the product.

## This is a TOOL-CALLING agent, so the corpus is trajectories

The corpus is **not** prose answers. It is sequences:

```
ask → tool call → observation → next call decided BY that observation → … → the Pipeline
```

An example whose calls are a fixed script is a lookup with extra steps. The property being taught
is that **each call after the first is conditioned on what the previous one returned** — read the
schema, discover an 11% null rate, and *therefore* add a drop step.

The quality bar is a test you can run: **perturb one fact in the profile and the correct trajectory
must change.** If it survives, the example teaches emission from the use-case name rather than
reading of the data — which is how one pipeline shape once served churn, lead scoring and
collections alike.

## SFT now, RLVR after

**SFT** teaches the shape: what a correct trajectory looks like for a situation.

**RLVR** then sharpens it against the deterministic graders — the agent proposes calls, the sandbox
runs them, the grader scores the end state, and the policy updates. That loop is wired and
verified: reward rose 0.52 → 1.00 over 16 steps
([zetta#859](https://github.com/oramasearch/zetta/issues/859)).

**The order is not a preference.** RLVR sharpens what a policy already sometimes does; it cannot
originate a capability. A campaign against a policy that never emits a pipeline returns a uniformly
zero reward, and a group with equal rewards has zero advantage — GRPO takes a null step and the run
cannot learn no matter how long it goes. That was measured, not assumed.

So this corpus has one job: **get the policy to sometimes build a correct pipeline.** RLVR does the
rest.

## Mutation is half the product, and the harder half

Creating a Pipeline from nothing is the easy case. The real work is *changing* one:

- *"add calibration to that"* — and keep every other step
- *"actually use the last 90 days"* — a cutoff change that invalidates the features built from it
- *"drop the null accounts"* — which changes what the metric means, and the agent should say so
- *"that ran too long"* — a performance ask that is really a partitioning question

A mutation example carries **the pipeline before, the ask, and the pipeline after**. What must NOT
change is as much of the lesson as what must.

## Grading

By **Zetta's deterministic graders**, never a rubric. A trajectory that produces a graph passing
its correctness profile is training data; one that merely looks plausible is not. Those graders are
the same ones RLVR will use, so an SFT example that grades well is already in the shape the reward
expects.

## The observations are real (#989)

Each example's profile is **landed on a live node** and the trajectory's read calls are **replayed
against it**, so `observation` is what `/v1` actually returned rather than what the generating
model imagined.

That matters more than it sounds. A written observation is coherent by construction — one author
wrote both the observation and the call that responded to it — which is exactly the property a real
node does not have. Replaying immediately caught trajectories calling `get_dataset` on tables their
own profile never declared: a 404 from the node, invisible in prose.

Null fractions are honoured when landing, so a `because` pointing at *"11% null ids"* is pointing
at data that really is.

Examples record `observations_real`. Batch generation requires `ZETTA_BASE_URL` and `ZETTA_TOKEN`;
without a live engine, solution or methodology support and the resulting run cannot be verified,
so no example is written.

## Runnable methodologies only (#1)

When no solution entries are available, the agent reads `list_methodologies`. Prompt v3 may select
only an entry marked `runnable`, and each methodology example names that entry's `methodology` id
and one of its `model_kind` values. Replay executes `compile_intent` with the methodology and
records the engine's compiled graph as an observation, then runs that graph and records the trainer
response. An unrunnable methodology is rejected with its tracking issue.

If `list_methodologies` returns `unknown_capability`, the workspace predates the registry. The agent
allows only legacy M-1 GBDT classification and says that it used this fallback. The runnable list is
otherwise never kept in this repository.

## Runnable solutions only (#3)

At the start of each generation turn, the agent reads `list_solutions`. Prompt v3 may select only
an entry the live response marks runnable, then `get_solution` reads that entry's current levels,
policy template, autonomy defaults, guardrails, data roles and measurement design. The solution
list is never copied into this repository. A sketch or non-runnable entry is rejected with the
engine's promotion condition or implementation issue.

The generated trajectory ends at `create_solution`. Replay executes that action, runs the exact
project and graph it returned with `run_solution`, and reads policy, experiment, ledger, monitor
and ROI readout state. Only a solution whose creation and run succeed is kept. An optional read
that returns `unknown_capability` is recorded as “not deployed yet.”

The kept example proposes policy and label definitions from the observed solution entry and marks
both for owner sign-off. A readout is measured evidence, never a promised ROI figure, price, or
odds of success. See [`docs/solutions/README.md`](docs/solutions/README.md).

An engine that returns `unknown_capability` for `list_solutions` has no catalogue solutions for
that turn. Methodology generation can still use its existing registry or legacy M-1 fallback.

Prompt versions are recorded per example. The artifact remains `project-sft-v1.jsonl`, matching
the filename copied by the consuming Project Agent image.

## Status

Current release: [v0.1.0](docs/releases/v0.1.0.md) (all releases: [`docs/releases/`](docs/releases/README.md)).

Generating. Nothing trained on it yet.

## In lake (lake#263)

A library agent of lake: a person asks it to record how a solution or pipeline is built (or how a
pipeline is changed, a `mutate` example) **on their own data**. One turn starts with
`list_solutions`; a solution turn also reads `get_solution`, while a workspace without entries uses
`list_methodologies`. It then reads `list_datasets` and asks for an example whose profile is that
workspace (only its real tables and columns), and replays the example's workspace reads and actions
so every observation is what the workspace returned (#989). `land_profile` is not used: no dataset
is landed in the person's workspace, and the example is answered as
`{reply, result: {kind: project_example,
example}}`, never added to the corpus.

**A Lake turn changes nothing in the workspace, so today it is refused** (#8). Lake grants the turn's
credential only `workspace_query`, `workspace_openapi` and `get_agent_task`, and its catalogue says
this agent changes nothing, while every example is replayed through actions (`compile_intent` and
`run`, or `create_solution` and `run_solution`). The turn's node is read-only (`Node(read_only=True)`
raises `read_only` on any action without sending it), and the service refuses the turn before the
model runs, so no model tokens are spent on an example it could never record. How a Lake turn should
record examples (a read-only replay, a sandbox workspace, or a grant) is open on #8. The batch CLI,
which runs against a node with its owner token, still replays actions.

**The model is reached through lake** (lake#248, lake `docs/api/model-gateway.md`): in lake every
call goes to `<LAKE_URL>/openai/v1` with the turn's own `lake_token` as the API key (`model.py`), so
lake counts its tokens in the turn's workspace and enforces the account's model-token limit. The
service holds no `OPENAI_API_KEY`, and a turn without a lake credential is refused. Only the batch
CLI, which runs for no workspace, calls OpenAI directly with your own key.

**A turn's credential goes only to Lake at this service's own `LAKE_URL`** (#9). The model address is
always `LAKE_URL`; a turn's `lake_url` is ignored. The workspace address, `zetta_base_url`, is Lake's
workspace route (`<LAKE_URL>/w/<workspace>/workspaces/<customer>/zetta`) and is accepted only on
`LAKE_URL`'s origin (scheme, host and port) under its path, with no user info, query or fragment;
any other address refuses the turn before a request is made. With `LAKE_URL` unset, every turn is
refused.

- `model.py`: the OpenAI client pointed at lake's model gateway with the turn's credential.
- `service.py`: `run_turn`, and `agent-project-corpus-serve` (`GET /healthz`, `POST /v1/turn`).
  `POST /v1/turn` requires `Authorization: Bearer <AGENT_SERVICE_TOKEN>`, compared in constant time (`401` otherwise), and fails closed: with `AGENT_SERVICE_TOKEN` unset or empty it refuses every turn with `503`. The operator always sets it; set it yourself for a hand-run service. Turns from lake's bus do not use it.
- `lake_bus.py`: takes turns from lake's agent bus with its own `AGENT_BUS_TOKEN`.
- `Dockerfile`: private image `oramasearch/agent-project-corpus`.
- `docs/solutions/`, `docs/methodologies/`: the solution and methodology checks.
- `docs/releases/`: one page per release.
- Tests: `uv run --group dev pytest`.
