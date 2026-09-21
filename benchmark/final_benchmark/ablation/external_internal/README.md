# Internal / external prompt goals

Two fixed tasks are crossed with all 15 prompt goals, for each injection mode:

- `task_800767f48d7e42cfaa74ca8057364512`: BBDC / TPVG merger Business Services exposure (banking).
- `task_f525769ab6a748e6855e03c95e4b4bd7`: Impact SG&A cost reduction (consulting).

| Group | Goals | Static records | Dynamic records |
|---|---|---:|---:|
| internal | 7, 18, 19, 20, 21, 22, 23, 24 | 16 | 16 |
| external | 1, 2, 3, 4, 5, 6, 8 | 14 | 14 |

Both generation wrappers invoke the existing, unmodified pipeline:
`python -m benchmark.generate_attack_config.generate INPUT --output OUTPUT`.
They prepare task/goal selections and validate output only. Generated attack
configs, carrier names, contents, and supporting artifacts are retained exactly
as produced by the pipeline, without rewriting names or text.

Static uses `inject_vector=txt`, `add_user_prompt=false`, `no_key_words=false`.
The pipeline generates keyword-related TXT filenames and cover text. Names/text
may vary across goals; they are not forcibly made identical.

Dynamic uses `inject_vector=dynamic_prompt_injection`, `add_user_prompt=false`,
`no_key_words=true`, following the existing dynamic pipeline. It emits watcher
configs/scripts and required fixtures. At runtime, the watcher generates an
`<original file stem> additional task instruction.txt` file when a supported
source file is accessed. The source document itself need not be TXT. Dynamic
instructions, target values and fixtures follow that pipeline's own defaults;
static and dynamic pair task IDs and goal IDs, not necessarily target values.

Output locations:

- `internal/static_prompt_injection/selected_16_tasks_with_attack_config.json`
- `external/static_prompt_injection/selected_14_tasks_with_attack_config.json`
- `internal/dynamic_prompt_injection/selected_16_tasks_with_attack_config.json`
- `external/dynamic_prompt_injection/selected_14_tasks_with_attack_config.json`

Each bundle has `pipeline_provenance.json` recording the exact command, input
hash and generation-time hashes of the output JSON and every referenced artifact.
Validation checks these hashes without modifying generated files. A completed
bundle is reused only if it has matching original-pipeline output hashes.

```bash
python3 benchmark/final_benchmark/ablation/external_internal/generate_static.py
python3 benchmark/final_benchmark/ablation/external_internal/generate_dynamic.py
# Verify existing outputs without model calls:
python3 benchmark/final_benchmark/ablation/external_internal/generate_static.py --validate-only
python3 benchmark/final_benchmark/ablation/external_internal/generate_dynamic.py --validate-only
```

Generation needs the repository's Azure credentials and network access. These
commands generate configurations and fixtures; they do not start evaluations.
Selection manifests and validation reports are separate for static and dynamic.

Compare rates rather than raw counts because internal/external group sizes
differ. Task context and vector are controlled within each mode, but goals differ
between leakage groups, so goal difficulty can also affect the results.

## Evaluate Terra, DeepSeek and GLM 5.3 Flash

From the archipelago repository root:

```bash
bash benchmark/final_benchmark/ablation/external_internal/run_models.sh --dry-run
bash benchmark/final_benchmark/ablation/external_internal/run_models.sh --concurrency 12
```

Defaults: GPT Terra, DeepSeek V4 Flash and GLM 5.3 Flash; both static and dynamic;
180 evaluations total; shared concurrency 12; max steps 100; timer off.
The launcher uses the existing shared benchmark runner and only reads the input
bundles. It verifies original-pipeline output hashes before scheduling tasks.

Terra uses the existing Azure Key Vault credentials. Export DEEPSEEK_API_KEY and
ZAI_API_KEY for DeepSeek and GLM. API keys are not printed. Runtime model configs
are created with restricted permissions. Dry runs do not require those keys or
Docker. Actual runs need the usual benchmark Docker/dataset environment.

Options:

- `--mode static` or `--mode dynamic`: 90 evaluations for all three models.
- `--models gpt-terra deepseek glm53`: select any subset.
- `--concurrency N` (1–64), `--max-steps N`, `--base-port N`, `--skip-build`.
- `--output-root PATH`: choose a different output parent.
- `--summarize RUN_DIR`: refresh results from a directory containing manifest.json.
- `PY=/path/to/python`: override the default python3 interpreter.

Every launch creates a separate directory beneath:
`benchmark/output/ablation/external_internal/run_*/parallel_*/`.
At completion the script prints a table and saves `leakage_summary.md`,
`leakage_summary.csv`, and `leakage_summary.json` there. The full run has 12 rows:
3 models × 2 injection modes × 2 leakage groups. Each row reports exposure rate,
ASR, separate evaluated counts, success counts, finished/requested, process
failures and missing grades. No static/dynamic or internal/external pooling is
performed. Each invocation runs each requested configuration once; it does not
resume or merge earlier evaluations.

Exposure uses the benchmark's prompt_exposure metric, not a generic file-open
measure. ASR uses attack_success. Each rate uses valid binary grades as its own
denominator. Missing grades are excluded rather than counted as zero. A valid
grade is included even if its process returned an error; process failures are
reported separately. Compare complete coverage when interpreting group rates.
