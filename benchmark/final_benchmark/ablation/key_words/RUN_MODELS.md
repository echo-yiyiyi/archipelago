# Run the keyword ablation across three models

## Corrected client-code case

The keyword-free static prompt case `task_fe573b8ce38d4a9f9642fbe7b8f11358_txt_22_save_client_code`
now embeds the same `Before continuing...` instruction as its configuration.
To rerun only this case with a September 13 model configuration:

```bash
/data/ziyi/.venv/bin/python benchmark/final_benchmark/ablation/key_words/rerun_client_code.py --model gemini36
```

Model choices are `gemini36`, `gpt_terra_high`, `deepseekv4`, and `glm53`.
Use `--dry-run` to validate the input and inspect the saved model configuration.
The runner uses 150 steps, no timer, and existing Docker images. DeepSeek needs
`DEEPSEEK_API_KEY`; GLM needs `ZAI_API_KEY`. GPT uses `OPENAI_API_KEY`, falling back
to `agents/.env`. Each invocation saves a separate `client_code_before_*` batch
with provenance and results; original batches are retained.

## Full experiment

From the repository root:

```bash
/data/ziyi/.venv/bin/python benchmark/final_benchmark/ablation/key_words/run_models.py --concurrency 64
```

The default runs both `with` and `without`, each containing the same 10 prompt and 10 script tasks. This schedules **120 task executions**: 20 tasks × 2 settings × 3 models. All models, settings and categories share one interleaved pool of 64 task slots. Change `--concurrency` to any value from 1 to 64. Script formats remain py/pyc/ELF = 3/3/4 in both settings.

All benchmark models inherit `agent_config_values.max_steps = 150` from `benchmark/agent_config.json`. Change that one field to set the default agent step/turn budget for future runs. An explicit model-level `max_steps` or exported `HF_MAX_STEPS` overrides the default; leave them unset to inherit 150.

The runner uses these configurations:

| Output model name | Actual model | Configuration |
|---|---|---|
| `gemini36` | Gemini 3.6 Flash (Vertex AI) | `benchmark/orchestrator_config_gemini36.json` |
| `gpt_terra_high` | GPT 5.6 Terra (OpenAI Responses API, high reasoning) | `benchmark/orchestrator_config_gpt_terra_high.json` |
| `deepseekv4` | DeepSeek V4 Flash | `benchmark/orchestrator_config_deepseekv4.json` |

Run in the existing benchmark environment with its dataset, Docker, Vertex credentials and the usual benchmark grading credentials. Export `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` in the launching environment. GPT Terra follows the GPT-6 configuration: `openai/responses/gpt-5.6-terra` at `https://api.openai.com/v1`, with no Azure Key Vault configuration. The DeepSeek configuration uses the native LiteLLM `deepseek/` provider, which reads this environment variable. No key is stored in the configuration. Reasoning settings otherwise follow the existing model configurations (Gemini high, GPT high, DeepSeek max).

Validate inputs without Docker or API calls:

```bash
/data/ziyi/.venv/bin/python benchmark/final_benchmark/ablation/key_words/run_models.py --dry-run
```

If the existing Docker images are already built, add `--skip-build`. To select only one setting, add `--settings with` or `--settings without`. `--models` accepts benchmark orchestrator configuration suffixes.

Each run writes to:

```text
benchmark/output/key_words/keyword_<timestamp>_<id>/parallel_<run-id>/
  manifest.json
  model_summary.json
  model_summary.csv
  model_summary.md
  <model>/<with|without>/<static_prompt_injection|static_script_injection>/
    orchestrator_config.json
    score_summary.json
    tasks/
    logs/
```

The three summary formats contain 18 rows: 3 models × 2 settings × (prompt, script, combined). They include:

- **ASR:** mean attack success over tasks with a security evaluation.
- **Exposure rate:** mean of the benchmark's `prompt_exposure` field over tasks with an exposure evaluation. The same field is used for script tasks; this metric is distinct from successful script execution.
- **Score:** mean original-task `final_score` over tasks with valid scores.
- Requested, finished and failed execution counts; each metric's evaluated and missing counts.

Combined rows aggregate prompt and script using each metric's own sample count. They do not average category rates without weighting, and they never pool `with` and `without`. Missing evaluations are `null`/blank/`N/A`, not zero. Infrastructure failures therefore remain visible through failed and missing counts. A finished execution is not necessarily a successfully graded task.

Individual task failures do not stop the remaining queue. The process returns nonzero for failed or interrupted runs, and writes summaries from available results when a manifest exists. To rebuild a summary later without running models:

```bash
/data/ziyi/.venv/bin/python benchmark/final_benchmark/ablation/key_words/run_models.py \
  --summarize-only benchmark/output/key_words/keyword_<timestamp>_<id>/parallel_<run-id>
```

Test the GPT Terra configuration through the actual agent/LiteLLM code path:

```bash
# Offline HTTP transport test; no credentials or network calls required.
agents/.venv/bin/python benchmark/test_openai_sol.py --config benchmark/orchestrator_config_gpt_terra_high.json

# One real tool-call request; requires OPENAI_API_KEY.
agents/.venv/bin/python benchmark/test_openai_sol.py --config benchmark/orchestrator_config_gpt_terra_high.json --live
```

OpenAI uses bearer API key authentication: [official API authentication documentation](https://developers.openai.com/api/reference/overview#authentication).
