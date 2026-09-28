# agent-project-corpus — Claude rules

Training corpus for **the main agent**: the one that builds and operates catalogue Solutions, and
creates or mutates Pipelines
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

So this corpus has one job: **get the policy to sometimes build a correct solution or pipeline.**
The loop does the rest — and it works: reward 0.52 → 1.00 over 16 steps against the deterministic
graders.

## Mutations are half the corpus, deliberately

Methodology generation alternates `create` and `mutate`, because changing a Pipeline is the harder
half of that product path and the easier half to under-represent. A mutation carries `before`, and
**what must not change is as much of the lesson as what must** — a mutation that silently rebuilds
has lost the user's work. Solution generation records a build only after its live run succeeds.

## The solution and methodology checks

Read `list_solutions` at the start of each generation turn. When it returns entries, select only a
live entry marked runnable, read it again with `get_solution`, replay `create_solution`, run the
returned graph, and read the operating evidence. Derive policy and label proposals from the live
definition and require owner sign-off. Treat optional `unknown_capability` responses as “not
deployed yet.” An engine where `list_solutions` itself is unknown has no catalogue solutions; never
substitute a remembered list.

When no solutions are available, read `list_methodologies`. Record only an entry marked
`runnable`, require its `model_kinds` to contain the example's `model_kind`, and replay
`compile_intent` with the selected methodology followed by `run`. The compiled graph and trainer
response are the proof; do not maintain a runnable-methodology list here.

Only `unknown_capability` activates the pre-registry fallback, where M-1 GBDT classification is the
only runnable methodology. Name this fallback in the answer.

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
