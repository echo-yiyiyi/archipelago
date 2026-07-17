# Archipelago Run Viewer

A fast local viewer for runs stored under
`archipelago/examples/hugging_face_task/output/concurrent`.

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

The installed command is also available:

```bash
archipelago-view
```

## Configuration

- `PORT`: change the listening port; the default is `8765`.
- `ARCHIPELAGO_RUNS_DIR`: point the viewer at another concurrent output directory.

The Analytics tab runs `scripts/count_completed_rounds.py` and
`scripts/plot_completed_durations.py` for the selected run. Those scripts create or update
their CSV, JSON, and PNG output files inside that run directory.
