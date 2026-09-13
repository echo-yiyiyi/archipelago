# Gemini 3.6 Flash watcher ablations

From the archipelago repository root:

```bash
# Same one task/goal in all four settings; four concurrent evaluations.
bash benchmark/final_benchmark/ablation/watcher_prompt/run_gemini36_smoke.sh

# All 10 pairs in all four settings; 40 evaluations, shared concurrency 12.
bash benchmark/final_benchmark/ablation/watcher_prompt/run_gemini36_all.sh

# Optional: launch all 40 concurrently if resources allow.
bash benchmark/final_benchmark/ablation/watcher_prompt/run_gemini36_all.sh --concurrency 40
```

Settings: with, without_corrupt, without_restore_other_txt, without_txt.
The model uses benchmark/orchestrator_config_gemini36.json and the existing
Vertex authentication setup. Max steps defaults to 100; timer is off.
Both launchers use the existing shared benchmark scheduling/evaluation pipeline.
They validate inputs without changing any task configs or watcher files.

Smoke uses goal 1_email_send_file and
`task_583c24a9cc6d432c9159b6e4380fe428` by default. Override with `--goal 18` or a
full goal ID. The selected pair is identical across settings. Smoke and all runs
write independent result directories; smoke is not reused by a later full run.
The frozen source JSON may contain 10 records, but smoke schedules only the one
selected task in each setting. Summaries use manifest-requested jobs only.

Common options: --dry-run, --concurrency N (1–64), --max-steps N, --base-port N,
--skip-build, --output-root PATH, --summarize RUN_DIR. The PY environment variable
overrides the default /data/ziyi/.venv/bin/python interpreter.

Results are stored under:
`benchmark/output/ablation/watcher_prompt/{smoke|all}_*/parallel_*/`.
Each completed run prints a four-setting table and writes setting_summary.md,
setting_summary.csv and setting_summary.json. Each row reports exposure rate,
ASR, success/evaluation counts, finished/requested, process failures and missing
grades. Exposure uses prompt_exposure, and ASR uses attack_success. Each metric
has its own valid binary-grade denominator. Missing grades are excluded rather
than counted as zero; valid grades are included even if the process failed.

Refresh reports without model calls:

```bash
bash benchmark/final_benchmark/ablation/watcher_prompt/run_gemini36_all.sh \
  --summarize /path/to/parallel_RUN_DIRECTORY
```

without_txt is PDF-only; other settings retain their existing supported file
formats. For behavior details, see the README in each variant directory.
No evaluation is started by generating or dry-running these launchers.
