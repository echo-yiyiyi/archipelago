# Final benchmark

The task bundle contains 180 tasks across eight batches. Run it from the repository root with the [top-level guide](../../README.md). For example:

```bash
python3 benchmark/run_models_parallel.py --models deepseek_v4_flash --dry-run
python3 benchmark/run_models_parallel.py --models deepseek_v4_flash --concurrency 8
```

The launcher accepts JSON configurations in `benchmark/orchestrator_config_<name>.json` or `litellm_configs/<name>.json`. See [RUN.md](RUN.md) for runner options. Use the generation scripts in this directory only when rebuilding the task bundle; see [GENERATE.md](GENERATE.md).
