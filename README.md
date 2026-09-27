# agent-project-corpus

Training corpus for **the main agent** — the one that creates and mutates projects
([zetta#986](https://github.com/oramasearch/zetta/issues/986)).

It takes a **project profile** (what Auto-Suggest proposed) plus the user's intent, and builds the
Pipeline. Then it changes it when asked. That is the product.

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

Examples record `observations_real`. Running without `ZETTA_BASE_URL` still works but leaves the
observations written, and says so.

## Status

Generating. Nothing trained on it yet.

## In lake (lake#263)

A library agent of lake: a person asks it to record how a pipeline is built (or changed, a
`mutate` example) **on their own data**. One turn reads the workspace through lake's read-only path
(`list_datasets`), asks for one example whose profile is that workspace (only its real tables and
columns), replays the example's read calls against it so every observation is what the workspace
returned (#989), and checks `defects`. `land_profile` is not used: nothing is landed or written in
the person's workspace, and the example is answered as `{reply, result: {kind: project_example,
example}}`, never added to the corpus.

- `service.py`: `run_turn`, and `agent-project-corpus-serve` (`GET /healthz`, `POST /v1/turn`).
- `lake_bus.py`: takes turns from lake's agent bus with its own `AGENT_BUS_TOKEN`.
- `Dockerfile`: private image `oramasearch/agent-project-corpus`.
- Tests: `uv run --group dev pytest`.
