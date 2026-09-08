# Generate static prompt injection tasks

From the repository root:

```bash
python3 benchmark/generate_static_prompt_injection_tasks.py --output-task-number 30
```

The script reads `sample_inject_vector/output/selected_15_tasks_with_balanced_inject_vectors.json`, preserves the selected static vectors, and samples distinct goals per task. The output count must be a positive multiple of the input count and cannot exceed the input count times the number of allowed goals. Default goals are 1–8 and 18–24 (15 goals). A seed of 42 makes sampling reproducible. Goal counts differ by at most one globally and within each vector. With 30 outputs, each task gets two goals and each default goal occurs twice.

Custom IDs accept numeric prefixes or full IDs, separated by spaces or commas:

```bash
python3 benchmark/generate_static_prompt_injection_tasks.py --output-task-number 30 --goal-ids 1,2,7,18,24 --seed 123
```

Outputs default to `benchmark/final_benchmark/static_prompt_injection/`:

- `selected_30_tasks_with_inject_goals.json`: sampled input to the existing generator.
- `selected_30_tasks_with_attack_config.json`: complete task records.
- One directory per harmful task containing the injected artifact and supporting files, referenced relative to the final JSON.

Top-level and nested `attack_config.leakage_type` are `external` for goals 1, 2, 3, 4, 5, 6, 8 and `internal` for all others.

`--sample-only` runs without API calls. Full generation invokes `benchmark.generate_attack_config.generate` using the same Python interpreter and requires that generator's dependencies, Azure OpenAI configuration, and source dataset. `--dataset-dir`, `--inject-goals`, `--model`, `--reasoning-effort`, and `--add-user-prompt` are forwarded. Use `--output-dir` for a separate bundle. Generator failures propagate; the sampled JSON remains available for diagnosis. The script verifies generated IDs, configs, and artifact paths before finalizing leakage labels.
