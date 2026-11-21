"""Wall-clock budgets for ``order_by``.

Moved out of ``tests/nettests/linq/test_order_by.py``: this assertion was not part
of the original .NET test and is machine-dependent, so it must not gate normal runs.

To keep it from flaking when other processes (IDE backends, etc.) compete for the
CPU, it measures process CPU time (not wall-clock) and takes the best of a few runs.
"""
from __future__ import annotations

import gc
import random
import time

import pytest

# Pure sort time budget in seconds (hardware dependent; tune per machine).
SORT_BUDGET_S = 0.75
ATTEMPTS = 3


@pytest.mark.parametrize("items", [0, 1, 2, 3, 8, 16, 1024, 4096, 1_000_000])
def test_sorts_randomized_enumerable_within_budget(flp_type, items):
    random.seed(42)
    randomized = [random.randint(0, 2147483647) for _ in range(items)]
    randomized.append(None)

    best = float("inf")
    ordered: list = []
    for _ in range(ATTEMPTS):
        gc.collect()
        gc.disable()
        try:
            start = time.process_time()
            ordered = list(flp_type(x for x in randomized).order_by(lambda i: i))
            best = min(best, time.process_time() - start)
        finally:
            gc.enable()

    assert len(ordered) == len(randomized)
    assert best < SORT_BUDGET_S
