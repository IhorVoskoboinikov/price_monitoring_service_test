"""
Запуск тестов с покрытием.

Usage (из корня проекта):
    uv run python tests/run.py               # все тесты + coverage
    uv run python tests/run.py unit          # только unit — БЕЗ Docker, доли секунды
    uv run python tests/run.py integration   # только integration (testcontainers)
    uv run python tests/run.py -k alerts     # доп. аргументы пробрасываются в pytest

Отчёт о покрытии: в терминале (term-missing) и HTML в tests/htmlcov/index.html.

Раскладка: tests/unit — чистые тесты без БД/сети (Docker не нужен);
tests/integration — поднимают Postgres через testcontainers.
"""

import sys

import pytest

# Пресеты выбора набора → каталог. Всё остальное считаем аргументами pytest.
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
