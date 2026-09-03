#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
IMAGE="${1:-archipelago-hf-environment:concurrency}"
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" -w /work "$IMAGE" bash -lc '
    set -e
    for source in py/*.py; do
      goal=$(basename "$source" .py)
      python3 -c "import py_compile; py_compile.compile(\"/work/$source\", cfile=\"/work/pyc/$goal.pyc\", doraise=True)"
      gcc -O2 -s -o "/work/elf/$goal" "/work/elf/_sources/$goal.c"
    done
  '
echo "Rebuilt existing args/py scripts as pyc and ELF using Docker image: $IMAGE"
