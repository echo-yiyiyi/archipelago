# Stable task difficulty filter

The script first filters the merged Gemini run to strict `30 < turns < 100`,
where a turn is one `assistant` message in `trajectory.json`. It keeps the
three requested score buckets and sorts each bucket by turns ascending.

Preview the candidate inventory without running models:

```bash
python3 archipelago/benchmark/filter_task_difficulty/filter_task_difficulty.py \
  --prepare-only
```

Run the complete selection. The environment and proxy images are shared (not
task-specific), so they are built once; GPT 5.6 Sol and Opus then run each task
in parallel with `--skip-build` and separate ports/run IDs:

```bash
python3 archipelago/benchmark/filter_task_difficulty/filter_task_difficulty.py
```

If either model finishes with a score outside the Gemini bucket, the other
model run is interrupted and cleaned up immediately because the task can no
longer be retained.

The parallel launchers also use separate Docker address pools to prevent
network overlap: GPT defaults to `172.30.0.0/16` and Opus defaults to
`172.31.0.0/16`. These defaults avoid the `10.255.0.0/16` corporate/private
endpoint range used by the Azure OpenAI resource. Override them with
`--gpt-runtime-cidr` and `--opus-runtime-cidr` when those ranges are already
in use on the host.

If the images already exist, add `--skip-build`. A stopped run resumes from
`output/attempts.json` by default. Add `--retry-attempted` to start a new report
and rerun previously attempted tasks.

Outputs:

- `output/candidates.json`: all eligible candidates, grouped by score bucket.
- `output/attempts.json`: detailed model runs, scores, bucket matches and paths.
- `output/attempts.csv`: compact attempted-task result table.
- `output/driver_logs/`: stdout/stderr from each benchmark launcher.

The default quotas are two score-1 tasks and one task from each lower bucket
for each of `law`, `banking`, and `consulting`. Once a domain quota is full in
a bucket, remaining candidates for that domain/bucket are skipped.
