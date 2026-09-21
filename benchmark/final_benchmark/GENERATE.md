# Regenerating final benchmark tasks

Run from the repository root after installing the benchmark generator dependencies. Full generation requires the source task dataset and model credentials. Add `--sample-only` to inspect sampling without calling a model.

| Script | Default request | Output |
| --- | ---: | --- |
| `generate_static_prompt_injection_tasks.py` | 30 | `static_prompt_injection/` |
| `generate_static_script_injection_tasks.py` | 30 | `static_script_injection/` |
| `generate_script_swap_tasks.py` | 15 args + 15 no args | `user_prompt_script_swap/{args,no_args}/` |
| `generate_suffix_plant_tasks.py` | 30 | `user_prompt_suffix_plant/` |
| `generate_dynamic_prompt_injection_tasks.py` | 30 | `dynamic_prompt_injection/` |
| `generate_dynamic_script_injection.py` | 30 total, split equally | `dynamic_script_injection/allow_additional_instruction_{true,false}/` |

```bash
python3 benchmark/final_benchmark/generate_static_prompt_injection_tasks.py --sample-only
python3 benchmark/final_benchmark/generate_dynamic_script_injection.py --sample-only
```

The scripts also accept `--input`, `--output-dir`, `--dataset-dir`, `--seed`, `--inject-goals`, `--model`, and `--reasoning-effort`. Static generators accept `--goal-ids`; check each script's `--help` for its quantity limits. A full run emits `selected_N_tasks_with_attack_config.json` and task assets. Regeneration calls the model again and can produce different content. Validate the resulting bundle with `python3 benchmark/run_models_parallel.py --models gemini36 --dry-run`.
