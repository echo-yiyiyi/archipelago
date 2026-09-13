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

## Re-rank final-benchmark task/goal pairs with PDF and Word

`rerank_task_goal_vectors.py` ranks nine vectors using the full task prompt,
keywords, and the goal description. It treats `(task_id, inject_goal)` as the
identity, so multiple goals for one original task receive independent rankings.
The old seven-vector ranking entry point is unchanged.

```bash
python -m benchmark.sample_inject_vector.rerank_task_goal_vectors \
  --input benchmark/final_benchmark/static_prompt_injection/selected_30_tasks_with_inject_goals.json \
  --output-dir benchmark/final_benchmark/static_prompt_injection_regenerated
```

The default balanced assignment uses exact min-cost flow, prioritizing balanced
counts, then top-three inclusion, then rank costs. Thirty rows across nine
vectors yield six counts of three and three counts of four. `--strategy first`
selects the first choice without balancing. `--rank-only` saves just rankings;
`--assign-only` reuses complete rankings without API calls. Rankings are cached
with an input hash. Generated inputs retain original task IDs and goals, rebuild
harmful task IDs for the assigned vector, and omit old attack configs/artifacts.

Generate the new bundle (PDF requires LibreOffice):

```bash
python -m benchmark.generate_attack_config.generate \
  benchmark/final_benchmark/static_prompt_injection_regenerated/selected_30_tasks_with_inject_goals.json \
  --output benchmark/final_benchmark/static_prompt_injection_regenerated/selected_30_tasks_with_attack_config.json
```

For an authorized OpenAI project, export `OPENAI_API_KEY` in the launching
terminal and run:

```bash
bash benchmark/final_benchmark/regenerate_static_prompt_openai.sh
```

This uses the public OpenAI Responses endpoint for both ranking and generation,
with `gpt-5.6-sol` by default (`OPENAI_GENERATION_MODEL` overrides it). Results go
to `final_benchmark/static_prompt_injection_openai`; Azure partial rankings are
not mixed into this run. Both Python entry points accept `--provider openai`
and `--model MODEL`. No API key is written into generated configuration files.
