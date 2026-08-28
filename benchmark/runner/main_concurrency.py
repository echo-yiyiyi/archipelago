"""Compatibility entry point for the concurrent end-to-end runner."""

from ..main_concurrency import main


if __name__ == "__main__":
    raise SystemExit(main())
