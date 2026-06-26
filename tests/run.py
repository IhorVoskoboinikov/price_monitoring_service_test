"""
Run the tests with coverage.

Usage (from the project root):
    uv run python tests/run.py               # all tests + coverage
    uv run python tests/run.py unit          # unit only — NO Docker, sub-second
    uv run python tests/run.py integration   # integration only (testcontainers)
    uv run python tests/run.py -k alerts     # extra args are passed to pytest

Coverage report: in the terminal (term-missing) and HTML in tests/htmlcov/index.html.

Layout: tests/unit — pure tests with no DB/network (no Docker needed);
tests/integration — start Postgres via testcontainers.
"""

import sys

import pytest

# Suite presets -> directory. Everything else is treated as pytest args.
SUITES = {"unit": "tests/unit", "integration": "tests/integration"}

COV_ARGS = [
    "-v",
    "--cov=app",
    "--cov-report=term-missing",
    "--cov-report=html:tests/htmlcov",
]

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in SUITES:
        target, extra = SUITES[args[0]], args[1:]
    else:
        target, extra = "tests", args
    raise SystemExit(pytest.main([target, *COV_ARGS, *extra]))
