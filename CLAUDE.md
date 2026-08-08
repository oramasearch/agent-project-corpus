# agent-project-corpus — Claude rules

Training corpus for **the main agent**: the one that creates and mutates Pipelines
([zetta#986](https://github.com/oramasearch/zetta/issues/986)). Read
[`zetta-bridge/docs/agent-scaffold.md`](../../docs/agent-scaffold.md) first.

## It is a tool-calling agent, so the corpus is trajectories

Not prose answers. `ask → call → observation → next call decided BY that observation → Pipeline`.

**Every call after the first carries a `because` naming a previous observation.** A call justified
by the user's ask is a scripted step, and a scripted trajectory is a lookup with extra steps. This
is checked, and it rejects most first attempts — which is the point.

**The quality bar:** perturb one fact in the profile and the correct trajectory must change. If it
survives, the example teaches emission from the use-case *name* rather than reading of the data —
the defect that made one pipeline shape serve churn, lead scoring and collections alike.

## SFT now, RLVR after — and the order is measured

RLVR sharpens what a policy already sometimes does; it cannot originate a capability. A campaign
against a policy that never emits a pipeline returns a uniformly zero reward, and a group with
equal rewards has **zero advantage** — GRPO takes a null step and the run cannot learn however long
it goes. That was measured
([zetta#859](https://github.com/oramasearch/zetta/issues/859)), not assumed.

So this corpus has one job: **get the policy to sometimes build a correct pipeline.** The loop does
the rest — and it works: reward 0.52 → 1.00 over 16 steps against the deterministic graders.

## Mutations are half the corpus, deliberately

Generation alternates `create` and `mutate`, because changing a Pipeline is the harder half of the
product and the easier half to under-represent. A mutation carries `before`, and **what must not
change is as much of the lesson as what must** — a mutation that silently rebuilds has lost the
user's work.

## The methodology check

`REQUIRED` and `FORBIDDEN` mirror the correctness cores in zetta's `plan_templates.cpp`, so an SFT
example grades the same way the engine does. The forbidden entries are the ones that get guessed
wrong: a **forecast is never calibrated** (no probability to calibrate, and a calibrator fit on
content-held-out rows re-introduces the leak temporal validation prevents); **anomaly and retrieval
have no label** to leak or calibrate.

## Running

```sh
uv sync
export OPENAI_API_KEY=...      # or: source ~/.zshrc
uv run agent-project-corpus --examples 20
```

uv, never pip. Prompts versioned — a prompt change is a model change.

## When a check rejects most generations

**Teach the prompt; do not loosen the check.** That was learned on the Auto-Suggest corpus, where
tightening the constraint rule rejected 6 of 6 and explaining what a real constraint looks like
brought it to 50% with every remaining rejection genuine.
