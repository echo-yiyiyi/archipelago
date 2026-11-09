# Scheme-like task: oracle verification

This directory contains an unmodified copy of Terminal-Bench 2's
`schemelike-metacircular-eval` task, including its Docker environment,
instructions, reference solution, and verifier. The original task contains
139 files. Its benchmark canary strings are preserved.

## Run on another machine

Install Docker and `uv`, start Docker, and make sure your user can run
`docker info`. No LLM API key is needed: the oracle agent runs the supplied
reference solution rather than calling a model. Do not copy a `.venv` from
another computer; `uvx` prepares the runner environment locally.

From the `archipelago` repository root:

```bash
git switch anony
git pull --ff-only origin anony
docker info
bash benchmark/rebuttal/terminal_bench/run_oracle.sh
```

The wrapper uses Harbor 0.24.0 and Python 3.13, evaluates only this local
task with `--agent oracle --env docker`, and builds the copied Dockerfile
with `--force-build`. The task requests 1 CPU and 2 GiB memory. The first
run needs network access to download Python/Harbor, the Docker base image,
and verifier dependencies. It may take longer than subsequent runs.

Harbor options can be appended, for example:

```bash
bash benchmark/rebuttal/terminal_bench/run_oracle.sh --job-name scheme-oracle-1
```

Use a new job name for each run, or omit it for Harbor's generated name.
Logs and results are written to `oracle_runs/` and are excluded from Git.
Inspect the job's `result.json`, the trial exception/logs, and
`verifier/reward.txt`. A reward of `1` means the verifier passed; `0` means
it failed. An environment failure without a reward is not a task pass/fail.

The source machine could not complete the official oracle trial because
its current user lacked Docker socket access. No passing official oracle
result is included in this directory.
