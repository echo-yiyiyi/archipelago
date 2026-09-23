# APEX-Harm

This repository contains the Archipelago agent environment and prompt injection benchmark. The final benchmark has 180 tasks across eight batches. Run the commands below from the repository root.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/). The task runner uses `uv run` for the agent and grader, and the Docker build installs the environment dependencies. You do not need to run `uv sync` manually.
- To execute experiments: Docker with Compose, credentials for the selected model and judge, and a separate data volume for the runner's temporary files. The dry-run commands only need the Python setup.

Set API keys as environment variables or in a local `.env` file that is never committed. Do not put key values in model JSON files.

Model configurations live in `benchmark/orchestrator_config_<name>.json` and `litellm_configs/<name>.json`. Both locations are accepted by the parallel and sequential runners. Pass the filename stem as the model name; for example, `gemini36`, `deepseekv4`, `deepseek_v4_flash`, `glm_5_3_flash`, or `kimi_k3_max`. A name must resolve to exactly one JSON file. The LiteLLM configs use `api_key_env` to name the required environment variable, rather than storing its value.

```bash
# Example: supply only the credentials for the models you run.
export DEEPSEEK_API_KEY=...
export ZAI_API_KEY=...
export KIMI_API_KEY=...
```

The grader may require separate credentials, including Vertex AI credentials for the Gemini judge. Check the selected model JSON and your local grading configuration for provider details.

## Check a small run first

`benchmark/all_category_test` contains 24 tasks covering the eight benchmark batches. Run the sample with:

```bash
python3 benchmark/run_models_parallel.py \
  --models deepseek_v4_flash \
  --input-root benchmark/all_category_test \
  --output-root benchmark/output/all_category_test \
  --concurrency 2
```

To test just one four-task category, add `--categories static_prompt_injection`. The output is under `benchmark/output/all_category_test/parallel_<timestamp>_<id>/`.

## Run all 180 final tasks

The parallel runner interleaves the eight batches in one queue. Each named model runs all 180 tasks; two models request 360 task runs. `--concurrency` is the global limit across all models.

```bash
# One existing orchestrator config; 180 tasks.
python3 benchmark/run_models_parallel.py --models gemini36 --concurrency 8 --dry-run
python3 benchmark/run_models_parallel.py --models gemini36 --concurrency 8

# One LiteLLM config; 180 tasks.
python3 benchmark/run_models_parallel.py --models deepseek_v4_flash --concurrency 8

# Two LiteLLM configs; 360 task runs sharing eight slots.
python3 benchmark/run_models_parallel.py \
  --models glm_5_3_flash kimi_k3_max --concurrency 8
```

The default input is `benchmark/final_benchmark`; output goes to `benchmark/output/final_benchmark/parallel_<timestamp>_<id>/`. The root `manifest.json` records every job and its status, and each model/category directory has a `score_summary.json`. `--skip-build` reuses existing Docker images. `--categories CATEGORY` selects a batch; `--dry-run` checks inputs only. Each invocation creates a new run rather than resuming an old one.

The eight batches contain 30 static prompt, 30 static script, 15 script swap args, 15 script swap no args, 30 suffix plant, 30 dynamic prompt, 15 dynamic script with additional instructions, and 15 dynamic script without them.

## View results locally

The optional `view-app` displays completed runs and trajectories. Start it from the repository root, then open `http://127.0.0.1:8765`:

```bash
uv run --project view-app python view-app/app.py
```

It discovers runs under `benchmark/output/final_benchmark` and `benchmark/output/all_category_test`. Set `ARCHIPELAGO_RUNS_DIR` to another output directory if needed.

For runs with exposure grading, the task list marks tasks where the reference prompt was exposed and gives the corresponding one-based message numbers. Opening a trajectory highlights those messages with a `Prompt exposure` badge. The run-level `Prompt exposure` metric is shown as `exposed tasks / tasks with an exposure result`; it counts affected tasks, not the number of exposed messages.

For a sequential category runner, use `python3 benchmark/final_benchmark/run_experiments.py all --model deepseek_v4_flash --concurrency 3`. Run either launcher with `--help` for category selection and storage options. To retry failed tasks from a parallel run, use `python3 benchmark/run_models_parallel.py --retry-failed <run-directory> --concurrency 4`.

## Credentials and reproducibility

`.gitignore` excludes `.env` files and common credential JSON filenames. Keep provider keys in your shell environment or a local ignored file, and check `git status` before publishing. The checked-in SSH keys and certificates are benchmark fixtures used inside the task/Docker environment; they are not model API credentials.

Use paths relative to the repository root in commands and configurations. Historical run manifests may contain machine-specific paths and are not portable inputs for a new run.
