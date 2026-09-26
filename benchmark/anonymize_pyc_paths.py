"""Remove local build paths from tracked Python bytecode without executing it.

Run with the Python version used to build the .pyc files. By default this
checks tracked files; pass --write to replace paths, or --include-ignored to
check local ignored ablation bytecode too.
"""

import argparse
import importlib.util
import marshal
from pathlib import Path
import subprocess
import types


ROOT = Path(__file__).resolve().parents[1]
REPO_MARKER = "archipelago"


def rewrite_code(code: types.CodeType) -> tuple[types.CodeType, int]:
    count = 0
    constants = []
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            value, nested_count = rewrite_code(value)
            count += nested_count
        constants.append(value)
    filename = code.co_filename
    parts = Path(filename).parts
    if Path(filename).is_absolute() and REPO_MARKER in parts:
        filename = Path(*parts[parts.index(REPO_MARKER) + 1 :]).as_posix()
        count += 1
    return code.replace(co_filename=filename, co_consts=tuple(constants)), count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite affected .pyc files")
    parser.add_argument("--include-ignored", action="store_true", help="also scan ignored ablation .pyc files")
    args = parser.parse_args()

    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.pyc"], cwd=ROOT
    ).split(b"\0")
    tracked_paths = {ROOT / raw.decode() for raw in filter(None, tracked)}
    paths = set(tracked_paths)
    if args.include_ignored:
        paths.update(
            path for path in (ROOT / "benchmark/final_benchmark/ablation").rglob("*.pyc")
            if "__pycache__" not in path.parts
        )
    affected = 0
    for path in sorted(paths):
        original = path.read_bytes()
        if f"/{REPO_MARKER}/".encode() not in original:
            continue
        if original[:4] != importlib.util.MAGIC_NUMBER:
            if path not in tracked_paths:
                continue
            raise RuntimeError(f"Different Python bytecode version: {path}")
        code = marshal.loads(original[16:])
        if not isinstance(code, types.CodeType):
            raise RuntimeError(f"Not a code object: {path}")
        revised, count = rewrite_code(code)
        if not count:
            continue
        affected += 1
        if args.write:
            updated = original[:16] + marshal.dumps(revised)
            path.write_bytes(updated)
        print(f"{path.relative_to(ROOT)}: {count} filename(s)")
    print(f"{affected} .pyc file(s) {'rewritten' if args.write else 'need rewriting'}")


if __name__ == "__main__":
    main()
