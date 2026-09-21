# Prompt carrier ablation

Five task/goal pairs are sampled from `static_prompt_injection/selected_30_tasks_with_attack_config.json`
with seed 42, requiring distinct task IDs and inject goals. Every vector uses these same five pairs:
email, txt, xlsx, word (.docx), md, chat, html, pdf, calendar. Total: 45 configurations.

Each vector directory contains `selected_5_tasks_with_attack_config.json`,
`selected_5_tasks_with_inject_goals.json`, and five task artifact directories.
`selection_manifest.json` records source provenance and canonical text hashes.

Attack configs (including cot, judge and target values) retain the original values;
only task artifact path prefixes change. All carriers use the same keyword-based
reference header followed by the original cot. This standardizes cover text rather
than carrying over the original format-specific cover text. Email/chat/calendar use
fixed neutral metadata and native benchmark .apps_data formats. Supplemental task
fixtures are copied unchanged. The OTP mailbox and email carrier share a path, so
the original OTP mailbox is preserved and the injection email is appended.
The calendar carrier is dated February 2025, separate from the sampled calendar
creation goal's September 2026 target event.

Word is a native DOCX package. PDFs are exported from DOCX with LibreOffice to
preserve Unicode. PDF text checking uses `pdftotext -layout` because default text
extraction may remove literal hyphens at line breaks. Whitespace/layout differs
across carriers; the decoded text, including punctuation, is verified equivalent.
The goal judge and payload content have not been redesigned or evaluated here.

Validation:

```bash
python3 benchmark/final_benchmark/ablation/prompt_vector/generate_ablation.py --validate
```

`validation_report.json` records task pairing, decoded-text equivalence, unchanged
source configs, fixture preservation and reference integrity checks. No model
experiments have been run. File vs application carriers also change retrieval
surfaces; interpret this as a carrier comparison, not purely a file-encoding test.

## Gemini 3.6 Flash evaluation

From the archipelago repository root:

```bash
bash benchmark/final_benchmark/ablation/prompt_vector/run_gemini36.sh --dry-run
bash benchmark/final_benchmark/ablation/prompt_vector/run_gemini36.sh --concurrency 9
```

This runs 45 evaluations using `benchmark/orchestrator_config_gemini36.json`
(`vertex_ai/gemini-3.6-flash`) and the existing Vertex credentials/setup.
Default settings: global concurrency 9, max steps 100, timer off, one run per
paired task/vector. `--max-steps`, `--base-port`, `--output-root`, and `--skip-build`
are supported. Use `--help` for options; PY overrides the Python executable.
The launcher clears inherited task-overlay and timer settings.

At completion, the table is printed to the terminal and saved as
`vector_summary.md`, `vector_summary.csv`, and `vector_summary.json` under:

```text
benchmark/output/ablation/prompt_vector/gemini36_*/parallel_*/
```

Each of the nine vector rows reports exposure rate, ASR, numerators, separate
evaluation denominators, finished/requested counts, process failures, and missing
grades. Exposure uses the benchmark `prompt_exposure` grade (its injection-text
exposure check, not a generic file-open measure); ASR uses `attack_success`.
Both accept valid binary grades; missing grades are excluded rather than zero.
Valid grades from failed processes are included and process failures are listed
separately. Compare vectors with complete coverage for paired conclusions.

Refresh a report without rerunning models:

```bash
bash benchmark/final_benchmark/ablation/prompt_vector/run_gemini36.sh \
  --summarize /path/to/parallel_RUN_DIRECTORY
```

Each launch creates a separate run; it does not resume or merge earlier runs.
