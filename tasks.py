#!/usr/bin/env python
"""One-command entry points for the tasks a contributor runs day to day.

    python tasks.py install    pip install -r requirements.txt, then the package itself
    python tasks.py lint       ruff check + ruff format --check
    python tasks.py test       pytest [args...]
    python tasks.py refresh    scripts/refresh_data.py [args...]
    python tasks.py charts     scripts/build_charts.py [args...]
    python tasks.py app        streamlit run app/streamlit_app.py

A Makefile would work everywhere else, but the primary dev machine for this
project is Windows/PowerShell without `make` on PATH, so this is a plain
Python script instead -- it runs identically on every platform.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(*command: str) -> int:
    return subprocess.run(command, cwd=ROOT).returncode


def install(args: list[str]) -> int:
    code = _run(sys.executable, "-m", "pip", "install", "-r", "requirements.txt")
    if code:
        return code
    return _run(sys.executable, "-m", "pip", "install", "-e", ".")


def lint(args: list[str]) -> int:
    code = _run(sys.executable, "-m", "ruff", "check", ".", *args)
    if code:
        return code
    return _run(sys.executable, "-m", "ruff", "format", "--check", ".")


def test(args: list[str]) -> int:
    return _run(sys.executable, "-m", "pytest", *args)


def refresh(args: list[str]) -> int:
    return _run(sys.executable, "scripts/refresh_data.py", *args)


def charts(args: list[str]) -> int:
    return _run(sys.executable, "scripts/build_charts.py", *args)


def app(args: list[str]) -> int:
    return _run(sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py", *args)


TASKS = {
    "install": install,
    "lint": lint,
    "test": test,
    "refresh": refresh,
    "charts": charts,
    "app": app,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TASKS:
        names = ", ".join(sorted(TASKS))
        print(f"usage: python tasks.py <{names}> [args...]", file=sys.stderr)
        return 2
    return TASKS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
