# Extract task keywords

This utility reads `tasks_and_rubrics.json`, sends each task prompt to the
Azure OpenAI Responses API, and stores exactly 3–4 concise keyword phrases per
task. It supports retries, parallel workers, checkpointing, CSV export, and a
dry-run inventory mode.

Preview the first three tasks without making API calls:

```bash
python3 archipelago/benchmark/extract_key_words/extract_key_words.py \
  --dry-run --limit 3
```

For one manually supplied prompt, use either a quoted string:

```bash
python3 archipelago/benchmark/extract_key_words/extract_key_words.py \
  --prompt "Analyze ACME's revenue workbook and summarize the EBITDA bridge." \
  --output /tmp/acme_keywords.json
```

or a UTF-8 file:

```bash
python3 archipelago/benchmark/extract_key_words/extract_key_words.py \
  --prompt-file ./my_task_prompt.txt
```

Run extraction with two concurrent requests:

```bash
python3 archipelago/benchmark/extract_key_words/extract_key_words.py \
  --workers 2
```

Results are written to `output/keywords.json` and `output/keywords.csv`.
Completed records are reused on restart; failed records are retried. The
shared Azure client lives in `benchmark/utils/azure_openai.py` and is usable by
other benchmark API scripts.
