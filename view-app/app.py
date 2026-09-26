from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, render_template, request, send_file


APP_DIR = Path(__file__).resolve().parent
ARCHIPELAGO_ROOT = APP_DIR.parent
SCRIPTS_DIR = APP_DIR / "scripts"
DEFAULT_RUNS_DIRS = (
    ARCHIPELAGO_ROOT / "benchmark" / "output" / "concurrent",
    ARCHIPELAGO_ROOT / "benchmark" / "output" / "final_benchmark",
    ARCHIPELAGO_ROOT / "benchmark" / "output" / "all_category_test",
)
_configured_runs_dir = os.environ.get("ARCHIPELAGO_RUNS_DIR")
RUNS_DIRS = (
    (Path(_configured_runs_dir).resolve(),)
    if _configured_runs_dir
    else tuple(path.resolve() for path in DEFAULT_RUNS_DIRS)
)

app = Flask(__name__)


def json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        abort(500, description=f"Could not read {path.name}: {exc}")


def safe_child(parent: Path, name: str) -> Path:
    """Resolve one existing direct child directory without restricting its name."""
    if not name or Path(name).name != name:
        abort(400, description="Invalid directory name")
    path = (parent / name).resolve()
    if path.parent != parent.resolve() or not path.is_dir():
        abort(404)
    return path


def discover_runs():
    """Keep legacy IDs and discover nested final-benchmark batches.

    Stop at each run so task snapshots and input bundles are never traversed.
    Nested IDs remain a single URL segment and include their parent directories.
    """
    seen = set()
    for root in RUNS_DIRS:
        if not root.is_dir():
            continue
        pending = list(sorted(root.iterdir()))
        while pending:
            path = pending.pop()
            resolved = path.resolve()
            if (not path.is_dir() or path.is_symlink()
                    or not resolved.is_relative_to(root.resolve())):
                continue
            relative = path.relative_to(root)
            is_run = (path / "tasks").is_dir() or (path / "variants").is_dir()
            if is_run:
                run_id = (path.name if len(relative.parts) == 1
                          else "::".join((root.name, *relative.parts)))
                if run_id not in seen:
                    seen.add(run_id)
                    yield run_id, resolved
                continue
            if path.name not in {"input", "logs", "environments", "summaries", "__pycache__"}:
                pending.extend(sorted(path.iterdir()))


def run_dir(run_id: str) -> Path:
    if not run_id or Path(run_id).name != run_id:
        abort(400, description="Invalid directory name")
    for identifier, path in discover_runs():
        if identifier == run_id:
            return path
    abort(404)


def variant_task_dirs(selected: Path):
    """Yield (label, task_path) for cotbatch-style runs that nest each replay
    under variants/<label>/tasks/<task_id>/ instead of a flat tasks/."""
    variants = selected / "variants"
    if not variants.is_dir():
        return
    for label_dir in sorted(variants.iterdir()):
        if not label_dir.is_dir():
            continue
        tasks_base = label_dir / "tasks"
        if not tasks_base.is_dir():
            continue
        for task_path in sorted(tasks_base.iterdir()):
            if task_path.is_dir():
                yield label_dir.name, task_path


def task_dir(run_id: str, task_id: str) -> Path:
    selected = run_dir(run_id)
    if Path(task_id).name != task_id:
        abort(400, description="Invalid directory name")
    direct = (selected / "tasks" / task_id).resolve()
    if direct.parent == (selected / "tasks").resolve() and direct.is_dir():
        return direct
    # cotbatch fallback: task_id is a variant label under variants/<label>/tasks/*
    variants = selected / "variants"
    if variants.is_dir():
        label_dir = (variants / task_id).resolve()
        if label_dir.parent == variants.resolve() and label_dir.is_dir():
            tasks_base = label_dir / "tasks"
            if tasks_base.is_dir():
                inner = [p for p in sorted(tasks_base.iterdir()) if p.is_dir()]
                if inner:
                    return inner[0]
    abort(404)


def run_model_info(selected: Path) -> dict[str, str | None]:
    model = None
    logs_dir = selected / "logs"
    model_re = re.compile(r"Running model (?P<model>\S+)")
    if logs_dir.is_dir():
        for log_path in sorted(logs_dir.glob("*.log"))[:5]:
            try:
                with log_path.open(errors="replace") as log_file:
                    for line_number, line in enumerate(log_file):
                        match = model_re.search(line)
                        if match:
                            model = match.group("model").split("/")[-1]
                            break
                        if line_number >= 200:
                            break
            except OSError:
                continue
            if model:
                break

    reasoning_effort = None
    tasks_dir = selected / "tasks"
    if tasks_dir.is_dir():
        extra_path = next(tasks_dir.glob("*/orchestrator_extra_args.json"), None)
        if extra_path is not None:
            try:
                extra = json.loads(extra_path.read_text(encoding="utf-8", errors="replace"))
                reasoning_effort = extra.get("reasoning_effort")
            except (OSError, json.JSONDecodeError):
                pass
    return {"model": model, "reasoning_effort": reasoning_effort}


def run_timing(selected: Path) -> dict[str, object] | None:
    events_path = selected / "events.jsonl"
    if not events_path.is_file():
        return None
    started_at = None
    ended_at = None
    status = "running"
    try:
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
                timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if started_at is None:
                started_at = timestamp
            if event.get("event") in {"run_finished", "run_interrupted"}:
                ended_at = timestamp
                status = "finished" if event["event"] == "run_finished" else "interrupted"
    except OSError:
        return None
    if started_at is None:
        return None
    effective_end = ended_at or datetime.now(timezone.utc)
    return {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_seconds": max(0, round((effective_end - started_at).total_seconds())),
        "status": status,
    }


def task_status(path: Path) -> str:
    if (path / "trajectory.json").is_file():
        return "ready"
    if (path / "trajectory.jsonl").is_file():
        return "ready"
    if (path / "grades.json").is_file():
        return "finished"
    return "pending"


def task_results(path: Path) -> dict[str, object]:
    """Return score/security fields without failing the whole task listing."""
    result: dict[str, object] = {
        "score": None,
        "attack_success": None,
        "prompt_exposure": None,
        "prompt_exposure_match_count": 0,
        "prompt_exposure_message_indices": [],
        "prompt_exposure_message_numbers": [],
        "attack_rules": {},
        "attack_observation": None,
        "attack_observation_kind": None,
        "attack_observation_message_indices": [],
        "attack_observation_message_numbers": [],
    }
    grades_path = path / "grades.json"
    if not grades_path.is_file():
        return result
    try:
        grades = json.loads(grades_path.read_text(encoding="utf-8", errors="replace"))
        score = grades.get("scoring_results", {}).get("final_score")
    except (AttributeError, OSError, json.JSONDecodeError):
        return result
    if not isinstance(score, bool) and isinstance(score, (int, float)):
        result["score"] = float(score)
    attack_success = grades.get("attack_success")
    if not isinstance(attack_success, bool) and isinstance(attack_success, (int, float)):
        result["attack_success"] = int(attack_success)
    prompt_exposure = grades.get("prompt_exposure")
    if not isinstance(prompt_exposure, bool) and isinstance(prompt_exposure, (int, float)):
        result["prompt_exposure"] = int(prompt_exposure)
    indices = grades.get("prompt_exposure_message_indices")
    if isinstance(indices, list):
        result["prompt_exposure_message_indices"] = [
            int(index) for index in indices
            if not isinstance(index, bool) and isinstance(index, (int, float)) and index >= 0
        ]
    numbers = grades.get("prompt_exposure_message_numbers")
    if isinstance(numbers, list):
        result["prompt_exposure_message_numbers"] = [
            int(number) for number in numbers
            if not isinstance(number, bool) and isinstance(number, (int, float)) and number >= 1
        ]
    rules = grades.get("attack_rules")
    if isinstance(rules, dict):
        result["attack_rules"] = {
            str(name): {
                key: value for key, value in rule.items()
                if key in {"passed", "description", "rationale"}
            }
            for name, rule in rules.items()
            if isinstance(rule, dict)
        }
    match_count = grades.get("prompt_exposure_match_count")
    if not isinstance(match_count, bool) and isinstance(match_count, (int, float)):
        result["prompt_exposure_match_count"] = int(match_count)
    observation = grades.get("attack_observation")
    if not isinstance(observation, bool) and isinstance(observation, (int, float)):
        result["attack_observation"] = int(observation)
    kind = grades.get("attack_observation_kind")
    if isinstance(kind, str):
        result["attack_observation_kind"] = kind
    for field, minimum in (
        ("attack_observation_message_indices", 0),
        ("attack_observation_message_numbers", 1),
    ):
        values = grades.get(field)
        if isinstance(values, list):
            result[field] = [
                int(value) for value in values
                if not isinstance(value, bool)
                and isinstance(value, (int, float))
                and value >= minimum
            ]
    return result


@app.get("/")
def index():
    return render_template("index.html", runs_dir=", ".join(map(str, RUNS_DIRS)))


@app.get("/api/runs")
def runs():
    items = [{"id": identifier} for identifier, _ in discover_runs()]
    return jsonify({"runs": items, "roots": [str(root) for root in RUNS_DIRS]})


@app.get("/api/runs/<run_id>/tasks")
def tasks(run_id: str):
    selected = run_dir(run_id)
    base = selected / "tasks"
    items = []
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if not path.is_dir():
                continue
            items.append({
                "id": path.name,
                "status": task_status(path),
                **task_results(path),
            })
    else:
        for label, task_path in variant_task_dirs(selected):
            items.append({
                "id": label,
                "status": task_status(task_path),
                **task_results(task_path),
            })
    summary_path = selected / "score_summary.json"
    score_summary = None
    if summary_path.is_file():
        raw_summary = json_file(summary_path)
        keys = (
            "completed_task_count",
            "average_mean_score",
            "average_pass_at_1_percent",
            "pass_at_1_count",
            "average_attack_success",
            "attack_success_count",
            "attack_evaluated_count",
            "prompt_exposure_count",
            "prompt_exposure_task_count",
        )
        score_summary = {key: raw_summary.get(key) for key in keys}
    return jsonify({
        "run_id": run_id,
        "tasks": items,
        "score_summary": score_summary,
        "model_info": run_model_info(selected),
        "job_timing": run_timing(selected),
    })


def slim_message(message: object) -> dict[str, object]:
    """Keep only fields used by the UI, avoiding large provider metadata payloads."""
    if not isinstance(message, dict):
        return {"role": "unknown", "content": message}
    slim: dict[str, object] = {"role": message.get("role", "unknown")}
    if "content" in message:
        slim["content"] = message["content"]
    if message.get("reasoning_content"):
        slim["reasoning_content"] = message["reasoning_content"]
    calls = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        calls.append({
            "name": function.get("name") or call.get("name") or "tool",
            "arguments": function.get("arguments", call.get("arguments", {})),
        })
    if calls:
        slim["tool_calls"] = calls
    return slim


@app.get("/api/runs/<run_id>/tasks/<task_id>/trajectory")
def trajectory(run_id: str, task_id: str):
    selected_task = task_dir(run_id, task_id)
    path = selected_task / "trajectory.json"
    if path.is_file():
        payload = json_file(path)
        messages = payload.get("messages", payload if isinstance(payload, list) else [])
    else:
        jsonl_path = selected_task / "trajectory.jsonl"
        if not jsonl_path.is_file():
            abort(404, description="This task does not have a trajectory yet")
        messages = []
        try:
            for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError as exc:
            abort(500, description=f"Could not read {jsonl_path.name}: {exc}")
    if not isinstance(messages, list):
        abort(500, description="The messages field in trajectory.json is not an array")
    seen_initial: set[str] = set()
    cleaned_messages = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") in {"system", "user"}:
            key = json.dumps(message, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen_initial:
                continue
            seen_initial.add(key)
        cleaned_messages.append(message)
    messages = cleaned_messages
    return jsonify({
        "run_id": run_id,
        "task_id": task_id,
        "messages": [slim_message(message) for message in messages],
        "results": task_results(selected_task),
    })


@app.post("/api/runs/<run_id>/analytics")
def generate_analytics(run_id: str):
    selected = run_dir(run_id)
    scripts = [SCRIPTS_DIR / "count_completed_rounds.py", SCRIPTS_DIR / "plot_completed_durations.py"]
    outputs = []
    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(script), str(selected)],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )
        outputs.append({
            "script": script.name,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        })
    summary_path = selected / "completed_round_summary.json"
    summary = json_file(summary_path) if summary_path.is_file() else None
    return jsonify({
        "run_id": run_id,
        "commands": outputs,
        "round_summary": summary,
        "has_duration_plot": (selected / "completed_task_durations.png").is_file(),
        "has_round_plot": (selected / "completed_round_distribution.png").is_file(),
    })


@app.get("/api/runs/<run_id>/round-plot")
def round_plot(run_id: str):
    path = run_dir(run_id) / "completed_round_distribution.png"
    if not path.is_file():
        abort(404, description="Generate analytics first")
    return send_file(path, mimetype="image/png", max_age=0)


@app.get("/api/runs/<run_id>/duration-plot")
def duration_plot(run_id: str):
    path = run_dir(run_id) / "completed_task_durations.png"
    if not path.is_file():
        abort(404, description="Generate analytics first")
    return send_file(path, mimetype="image/png", max_age=0)


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def api_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": getattr(error, "description", str(error))}), error.code
    return error


def main() -> None:
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), debug=False)


from judge_blind import register_blind_review
register_blind_review(app)


if __name__ == "__main__":
    main()
