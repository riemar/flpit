"""Smoke run of ``scripts/task_start_bench.py`` (Task start, resume and completion costs).

    pytest -s benchmarks/test_task_start_benchmark.py -m benchmark

For real numbers run the script itself, which takes ``--ops``, ``--repeats`` and ``--threads``.
"""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "scripts" / "task_start_bench.py"


def test_task_start_benchmark_runs(capsys: pytest.CaptureFixture[str]) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    namespace["main"](["--quick"])
    output = capsys.readouterr().out
    with capsys.disabled():
        print(output)
    assert "Task.run_inline" in output
    assert "building block" in output
