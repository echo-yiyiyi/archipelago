# Running the final benchmark

Run from the repository root. The [top-level guide](../../README.md) gives a quick start and credential setup.

```bash
# Validate all 180 task runs without Docker or model calls.
python3 benchmark/run_models_parallel.py --models gemini36 --dry-run

# Run one model across all 180 tasks.
python3 benchmark/run_models_parallel.py --models deepseek_v4_flash --concurrency 8

# Run a 24-task sample, or just one category.
python3 benchmark/run_models_parallel.py --models glm_5_3_flash \
  --input-root benchmark/all_category_test --concurrency 4
python3 benchmark/run_models_parallel.py --models kimi_k3_max \
  --input-root benchmark/all_category_test \
  --categories static_prompt_injection --concurrency 2
```

The eight batches are `static_prompt_injection`, `static_script_injection`, `user_prompt_script_swap/args`, `user_prompt_script_swap/no_args`, `user_prompt_suffix_plant`, `dynamic_prompt_injection`, and both `dynamic_script_injection/allow_additional_instruction_{true,false}` batches. `--models` accepts a JSON filename stem from `benchmark/orchestrator_config_<name>.json` or `litellm_configs/<name>.json`. Multiple models share the global `--concurrency` limit (1–64). Use `--skip-build` to reuse Docker images.

Results are written to `benchmark/output/final_benchmark/parallel_<timestamp>_<id>/`. The root `manifest.json` records job status; each model/category has a `score_summary.json`. Runs do not resume automatically. To rerun tasks with nonzero process exit status:

```bash
python3 benchmark/run_models_parallel.py --retry-failed <run-directory> --concurrency 4
```

Add `--dry-run` to inspect the retry set. `--include-unstarted` also includes queued tasks from an interrupted batch. `--merge-into-original` updates the original results after retaining a backup. The storage supervisor uses `benchmark/output/tmp/full_benchmark` by default; `--temp-root`, `--min-free-gb`, and `--min-system-free-gb` control storage.

For sequential category runs, use `python3 benchmark/final_benchmark/run_experiments.py all --model gemini36 --concurrency 3`. Replace `all` with one category or leaf batch.

In summaries, ASR uses `attack_evaluated_count`, average score uses `completed_task_count`, and exposure rate uses `prompt_exposure_task_count`. Missing values have no denominator and should not be read as zero.
