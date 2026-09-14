# Archipelago Run Viewer

A fast local viewer for runs stored under
`archipelago/benchmark/output/concurrent` and the legacy
`archipelago/examples/hugging_face_task/output/concurrent`, plus nested batches in
`archipelago/benchmark/output/final_benchmark`.

Nested batches appear as `final_benchmark::<experiment>::<batch>`. Discovery stops
at directories containing `tasks/` or `variants/`, so prepared inputs without
executed tasks do not appear.

It provides run and task selection, searchable task lists, numbered and collapsible
trajectory messages, focused tool-call arguments/results, and output from the
existing completion-round and duration analytics scripts.

## Install

Create an environment and install the dependencies declared in `pyproject.toml`:

```bash
cd archipelago/view-app
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Start

Once installed, start the viewer with one command from this directory:

```bash
python3 app.py
```

Open <http://127.0.0.1:8765>.

## Judge review

Open <http://127.0.0.1:8765/judges> or select **Judge Review** in the viewer.
Search and filter exposure and security judgments, inspect the judge instructions,
reference text, numbered tool results, and structured output, then save a human
verdict with message numbers and notes. The page supports disagreement filtering,
save-and-next, and JSON export of annotations.

Human annotations and edit history live in `data/judge_review/annotations.sqlite3`;
they do not modify benchmark grades. Changed reference text or tool results make prior
annotations stale; changes to the judge prompt or verdict preserve the human label.
Refresh the index to discover newly completed runs.

Future exposure and security judgments retain their exact requests in grades.
Historical security judgments without saved requests are excluded. For the exposure
rejudge campaign, saved inputs are shown with a clearly labeled reconstructed system
prompt when the original system prompt was not retained.

Optional environment variables:

- `ARCHIPELAGO_JUDGE_RUNS_DIR`: output tree to index; defaults to benchmark and legacy output trees.
- `ARCHIPELAGO_JUDGE_AUDIT_DIR`: campaign directory containing saved requests and judgments.
- `ARCHIPELAGO_JUDGE_DATA_DIR`: location for the annotation database.

The installed command is also available:

```bash
archipelago-view
```

## Configuration

- `PORT`: change the listening port; the default is `8765`.
- `ARCHIPELAGO_RUNS_DIR`: replace the default run roots with one output directory, including nested batches.

The Analytics tab runs `scripts/count_completed_rounds.py` and
`scripts/plot_completed_durations.py` for the selected run. Those scripts create or update
their CSV, JSON, and PNG output files inside that run directory.
