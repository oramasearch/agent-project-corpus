# Runnable methodology examples

Worked examples are accepted only when the current workspace engine says their methodology runs.
The generator reads `list_methodologies` at the start of every generation turn and gives that exact
result to prompt v2. The list is not copied into this repository.

Each example records top-level `methodology` and `model_kind` fields. The selected registry entry
must be runnable, and its `model_kinds` must contain the example's model kind. An unsupported entry
is rejected with its name, id, and `issue` value.

Replay executes workspace reads and the example's final `compile_intent` action. The replay forces
the selected methodology into the action arguments and stores the engine response as the call
observation, `compiled_pipeline`, and the final `pipeline`. This makes the engine's
methodology-specific graph, rather than a shape imagined by the generating model, part of the
recorded example.

Replay then calls `run` with the compiled graph and the dataset inspected by `get_dataset`. The run
response is stored as a trajectory observation and as `run`, so a kept example contains what the
methodology runner returned. A compile or run failure rejects the example.

An engine that returns `unknown_capability` for `list_methodologies` predates the registry. Only in
that case, the generator treats M-1 GBDT classification as runnable and says that it used the legacy
fallback. Other discovery failures are errors and do not relax the check.

Batch generation requires `ZETTA_BASE_URL` and `ZETTA_TOKEN`. Without a live engine the generator
cannot discover or compile a methodology, so it does not write an example.
