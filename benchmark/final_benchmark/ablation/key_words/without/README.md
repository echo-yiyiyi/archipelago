# Without task keywords

This bundle contains the same 20 task/goal/vector combinations as `../with`: 10 static prompt injections and 10 static script injections. The script sample is stratified as 3 py, 3 pyc, and 4 ELF tasks; both settings use the same sampled task IDs (see `../script_sampling_334.json`). Both configurations and artifacts were freshly generated, rather than copied from the `with` attack configs.

Each category contains:

- `selected_10_tasks_with_inject_goals.json`: generation input, with `no_key_words: true`, no `keywords`, and no previous attack config.
- `selected_10_tasks_with_attack_config.json`: complete experiment input; artifact paths are relative to this JSON.
- The 10 corresponding task directories.

No-keyword generation uses generic COT wording, instruction text, carrier context, recipient addresses, and URLs. Executables are named `calculate_final_answer.py`, `calculate_final_answer.pyc`, or `calculate_final_answer`; script instructions are named `Additional_Task_Instructions.txt`. Auxiliary mail, calendar, and chat contexts are generic too.

Original user prompts remain unchanged for execution and judging. Required operational values such as real source-file paths may contain task names. `Task_Brief.txt` deliberately retains the original prompt for the send-prompt goal. Source-file selection still uses the dataset and original request to select a valid target; this is a wording/identifier ablation, not removal of task data from the benchmark world. Fixed or task-ID-derived values can remain identical across regenerations.

Regenerate from the repository root:

```bash
/data/ziyi/.venv/bin/python -m benchmark.generate_attack_config.generate \
  benchmark/final_benchmark/ablation/key_words/without/static_prompt_injection/selected_10_tasks_with_inject_goals.json \
  --output benchmark/final_benchmark/ablation/key_words/without/static_prompt_injection/selected_10_tasks_with_attack_config.json \
  --no-keywords

/data/ziyi/.venv/bin/python -m benchmark.generate_attack_config.generate \
  benchmark/final_benchmark/ablation/key_words/without/static_script_injection/selected_10_tasks_with_inject_goals.json \
  --output benchmark/final_benchmark/ablation/key_words/without/static_script_injection/selected_10_tasks_with_attack_config.json \
  --no-keywords
```

The generator requires its configured Azure credentials and dataset; pyc/ELF rendering uses the existing Docker build image. `--no-key-words` is also accepted. The per-record `no_key_words` setting works without a CLI flag.
