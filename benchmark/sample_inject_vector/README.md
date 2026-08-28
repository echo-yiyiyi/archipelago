# Sample injection vectors

Assign exactly five tasks to each of the `py`, `pyc`, and `elf` injection
vectors while preserving every field in the input JSON. Each output task gains
only `inject_vector` and `harmful_task_id`; the latter is formatted as
`<task_id>_<inject_vector>`.

Run with the default input and output paths:

```bash
python3 archipelago/benchmark/sample_inject_vector/sample_inject_vector.py
```

Assignments are reproducible with the default seed of `42`. Pass `--seed` to
produce a different balanced assignment.

## Rank likely source file types with GPT-5.4

For each of the same 15 tasks, send its `keywords` to GPT-5.4 and rank all seven
file types from most likely to least likely to contain the associated information:

```bash
python3 archipelago/benchmark/sample_inject_vector/rank_file_types.py
```

The script uses the shared `benchmark/utils/azure_openai.py` Responses API
helper with strict structured output. It preserves every input field and adds
`file_type_ranking`, an ordered array containing all of `md`, `xlsx`, `html`,
`txt`, `chat`, `email`, and `calendar` exactly once. Completed
rankings are reused when the script is restarted; pass `--fresh` to regenerate
all rankings.

Analyze the first-choice distribution, top-three inclusion distribution, and
the distribution at each individual rank:

```bash
python3 archipelago/benchmark/sample_inject_vector/analyze_file_type_rankings.py
```

The aggregate and per-task results are written to
`output/file_type_ranking_stats.json`.

Create an exact balanced assignment from the seven-type rankings:

```bash
python3 archipelago/benchmark/sample_inject_vector/assign_balanced_file_types.py
```

The algorithm and objective are documented in
[`BALANCED_FILE_TYPE_ASSIGNMENT.md`](BALANCED_FILE_TYPE_ASSIGNMENT.md).

Merge the balanced file-type tasks with the `py`, `pyc`, and `elf` tasks, sort
by `easy`, `medium`, then `hard`, and keep both variants of each `task_id`
adjacent:

```bash
python3 archipelago/benchmark/sample_inject_vector/merge_inject_vector_tasks.py
```
