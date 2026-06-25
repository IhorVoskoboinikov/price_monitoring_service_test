"""
Запуск тестов с покрытием.

Usage (из корня проекта):
    uv run python tests/run.py            # все тесты + coverage
    uv run python tests/run.py -k alerts  # доп. аргументы пробрасываются в pytest

Отчёт о покрытии: в терминале (term-missing) и HTML в tests/htmlcov/index.html.
Требуется доступный Docker — тесты поднимают Postgres через testcontainers.
"""

import sys

import pytest

DEFAULT_ARGS = [
    "tests",
    "-v",
    "--cov=app",
    "--cov-report=term-missing",
    "--cov-report=html:tests/htmlcov",
]

if __name__ == "__main__":
    extra = sys.argv[1:]
    raise SystemExit(pytest.main(DEFAULT_ARGS + extra))
