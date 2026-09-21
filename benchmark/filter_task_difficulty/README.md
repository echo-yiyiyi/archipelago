# Stable task difficulty filter

The script first filters the merged Gemini run to strict `30 < turns < 100`,
where a turn is one `assistant` message in `trajectory.json`. It keeps the
three requested score buckets and sorts each bucket by turns ascending.

Preview the candidate inventory without running models:

```bash
python3 archipelago/benchmark/filter_task_difficulty/filter_task_difficulty.py \
  --prepare-only
```

Run the complete selection. The environment and proxy images are shared (not
task-specific), so they are built once; GPT 5.6 Sol and Opus then run each task
in parallel with `--skip-build` and separate ports/run IDs:

```bash
python3 archipelago/benchmark/filter_task_difficulty/filter_task_difficulty.py
```

If either model finishes with a score outside the Gemini bucket, the other
model run is interrupted and cleaned up immediately because the task can no
longer be retained.

The parallel launchers also use separate Docker address pools to prevent
network overlap: GPT defaults to `172.30.0.0/16` and Opus defaults to
`172.31.0.0/16`. These defaults avoid the `10.255.0.0/16` corporate/private
endpoint range used by the Azure OpenAI resource. Override them with
`--gpt-runtime-cidr` and `--opus-runtime-cidr` when those ranges are already
in use on the host.

If the images already exist, add `--skip-build`. A stopped run resumes from
`output/attempts.json` by default. Add `--retry-attempted` to start a new report
and rerun previously attempted tasks.

Outputs:

- `output/candidates.json`: all eligible candidates, grouped by score bucket.
- `output/attempts.json`: detailed model runs, scores, bucket matches and paths.
- `output/attempts.csv`: compact attempted-task result table.
- `output/driver_logs/`: stdout/stderr from each benchmark launcher.

The default quotas are two score-1 tasks and one task from each lower bucket
for each of `law`, `banking`, and `consulting`. Once a domain quota is full in
a bucket, remaining candidates for that domain/bucket are skipped.

## Compare all models on the selected 15 tasks

From the repository parent directory:

```bash
python3 archipelago/benchmark/filter_task_difficulty/run_selected_models.py --dry-run
python3 archipelago/benchmark/filter_task_difficulty/run_selected_models.py
```

The default is a single global pool of 32 tasks across 10 models (150 runs):
`gpt_astra_low`, `gemini36`, `gemini37`, `gemini38`, `luna`, `gpt_terra`,
`glm53`, `deepseekv4`, `opus`, and `sonnet5`. Each uses its existing
`benchmark/orchestrator_config_<name>.json`, including its reasoning settings
and step limit. Task IDs come from `output/selected_15_tasks.json`; original
baseline tasks are loaded from the dataset. The launcher clears inherited
attack configuration and step-limit overrides.

Requires the same Docker, uv, credentials and agent/grading dependencies as
`benchmark/run_concurrency.sh`. Images are built once; use `--skip-build` if
already built. Use `--models gemini36 opus` for a subset, or `--concurrency 8`
for a smaller pool. Every invocation creates a new run (no automatic resume).

Results are saved beneath `output/model_comparison/selected15_<timestamp>_<id>/`:

- `model_scores.csv` / `model_scores.json`: per-model arithmetic mean of
  `scoring_results.final_score`. `mean_score` is populated only when all 15
  runs succeed and have finite numeric grades. `completed_mean_score` is the
  partial mean; `scored_tasks` and `failed_tasks` expose incomplete runs.
- `task_scores.json`: individual scores and paths to grades.
- `manifest.json`: model mapping, task list, and process results.
- `<model>/tasks/<task_id>/`: trajectories, grades, and task artifacts.
- `<model>/logs/`: task logs.

Reports update as tasks finish. Ctrl-C/SIGTERM stops active processes and
cleans up runtime resources. Missing/failed grades produce a nonzero exit.
Regenerate reports without running models:

```bash
python3 archipelago/benchmark/filter_task_difficulty/run_selected_models.py \
  --summarize /path/to/selected15_run
```

Retry missing or failed baseline evaluations in place (existing successes are
preserved and original artifacts are backed up under `retry_backups/`):

```bash
python3 archipelago/benchmark/filter_task_difficulty/run_selected_models.py \
  --retry-run /path/to/selected15_run --models glm53 luna --skip-build
```

Retries read current `benchmark/orchestrator_config_<model>.json`, so correct
expired credentials there before retrying. The model ID must match the original
run. Selection checks grades as well as exit codes, since an agent API failure
can leave the launcher exit code at zero. Reports in the original directory
update after each task. Separate retries for the same directory must run
sequentially; combining model names runs them together under one worker pool.
The retry exit code reflects only the requested tasks, so other incomplete
models do not make a successful subset retry fail.
