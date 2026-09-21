# Gemini 3.6 Flash watcher script ablation

The `with` and `direct_arg` groups contain the same ten task/goal pairs. Both use `benchmark/orchestrator_config_gemini36.json`, a 100-step limit, and no timer. Run from the repository root:

```bash
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_smoke.sh
bash benchmark/final_benchmark/ablation/watcher_script/run_gemini36_all.sh
```

The smoke test runs one pair (two evaluations) with concurrency 2. The full test runs all 20 evaluations with shared concurrency 12; pass `--concurrency 20` to change it. `--dry-run` prints the plan. Output is under `benchmark/output/ablation/watcher_script/`, including `setting_summary.{md,csv,json}`. Scores use only evaluated tasks in their denominators. Use `--summarize /path/to/parallel_run` to summarize an existing run.
