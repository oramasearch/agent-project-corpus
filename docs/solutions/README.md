# Runnable solution examples

Worked solution examples come from the current workspace engine. At the start of each generation
turn, the generator reads `list_solutions` and gives that exact response to prompt v3. It keeps no
local S-1 through S-12 or B-1 through B-8 table.

After an example selects an id present in that response, the generator reads the same id with
`get_solution`. The detailed response is authoritative for its runnable state, capability levels,
policy template, autonomy defaults, guardrails, data roles and measurement design. A sketch is
rejected with its promotion condition. A non-runnable entry is rejected with its implementation
issue.

Only `unknown_capability` from `list_solutions` means the workspace predates the solution
registry. That engine has no catalogue solutions for the turn. Other discovery failures remain
failures instead of being converted into an empty registry. The existing methodology path remains
available when there are no solution entries.

## Generated and replayed calls

A generated solution trajectory has these required boundaries:

1. `list_solutions` is the first call.
2. `get_solution` reads the selected live id.
3. Workspace reads establish a real captured source for the entry's required data roles.
4. `create_solution {project, solution, level, sources}` is the final generated call. Its level is
   offered by the live entry, and `sources` names `source` and `table`.

Replay replaces every written observation with the workspace response. After `create_solution`
returns a composed graph, replay constructs `run_solution` from that returned project and graph;
the generating model does not guess either value. A failed creation or run rejects the example.

After a successful run, replay reads `get_policy`, `get_experiment`, `list_ledger`, `get_monitor`
and `get_roi_readout`. These are operating evidence, not invented example fields. If an optional
read returns `unknown_capability`, the recorded observation and reply say that operation is “not
deployed yet.”

## Recorded result

The kept example stores the `create_solution` result as `pipeline`, the execution result as `run`,
and the five operating reads under `operations`. Its `readout` distinguishes `available` from
`not_deployed_yet`.

The example derives `policy_proposal` and `label_definitions` from the observed `get_solution`
entry. The policy includes the live template, autonomy defaults and guardrails. Label definitions
include the live data-role descriptions and measurement design. `owner_signoff.required` is true
for both; the corpus does not teach an unreviewed policy mutation.

Replies describe readouts as measured evidence. They do not promise ROI figures, pricing, or odds
of success.

## Versions

Prompt v3 adds the solution trajectory shape. The corpus artifact remains
`corpus/project-sft-v1.jsonl`, matching the consuming `agent-project` image. Each record carries
its own `prompt_version`, so prompt provenance does not require renaming the corpus artifact.
