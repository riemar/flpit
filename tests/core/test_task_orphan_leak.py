"""The Task runtime must not keep unreachable tasks alive.

In .NET an uncompleted ``TaskCompletionSource`` (and any continuation parked on
it) is garbage once nobody references it. The runtime keeps a registry of
pending tasks so that ``Task.shutdown()`` can cancel them; that registry must
therefore not be what keeps an abandoned task, or an awaiting coroutine, alive.

The second half guards the other direction: tasks that can still make progress
(queued, running, or parked on something reachable) must survive a collection
even when the caller dropped every reference to them, and shutdown must still
find and cancel the pending ones.
"""

from __future__ import annotations

import gc
import threading
import time
import weakref
from typing import Any

import pytest

import flpit.task as task_module
from flpit.task import Task, TaskCompletionSource


@pytest.fixture(autouse=True)
def isolated_runtime():
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    yield
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)  # the limits outlive shutdown: restore them for later modules


def _collect() -> None:
    # Parked tasks sit in reference cycles (task <-> operation).
    for _ in range(3):
        gc.collect()


def _wait_until(predicate: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        time.sleep(0.001)


# ---------------------------------------------------------------------------
# Abandoned work is collectable
# ---------------------------------------------------------------------------


def test_dropped_task_completion_source_is_collectable() -> None:
    sources = [TaskCompletionSource() for _ in range(1000)]
    refs = [weakref.ref(source.task) for source in sources]
    del sources

    _collect()

    assert sum(ref() is not None for ref in refs) == 0


def test_coroutine_parked_on_dropped_source_is_collectable() -> None:
    async def waiter(target: Task[Any]) -> None:
        await target

    pairs = []
    for _ in range(200):
        source = TaskCompletionSource()
        awaiting = Task.run(waiter(source.task))
        pairs.append((weakref.ref(source.task), weakref.ref(awaiting), awaiting))
    # Every waiter has to be parked before its references go away.
    _wait_until(lambda: all(a._waiting_on is not None for _, _, a in pairs))
    refs = [(source_ref, awaiting_ref) for source_ref, awaiting_ref, _ in pairs]
    del pairs, source, awaiting

    _collect()

    assert sum(source_ref() is not None for source_ref, _ in refs) == 0
    assert sum(awaiting_ref() is not None for _, awaiting_ref in refs) == 0


def test_completed_tasks_are_not_retained() -> None:
    tasks = [Task.run(lambda i=i: i) for i in range(100)]
    assert [t.result() for t in tasks] == list(range(100))
    refs = [weakref.ref(t) for t in tasks]
    del tasks

    _collect()

    assert sum(ref() is not None for ref in refs) == 0


# ---------------------------------------------------------------------------
# Work that can still progress is never collected
# ---------------------------------------------------------------------------


def test_parked_on_delay_survives_collection_without_references() -> None:
    finished = threading.Event()

    async def sleeper() -> None:
        await Task.delay(0.15)
        finished.set()

    Task.run(sleeper())  # the returned Task is dropped on purpose
    time.sleep(0.05)  # let it reach the delay
    _collect()

    assert finished.wait(5.0)


def test_waiter_survives_collection_while_its_source_is_reachable() -> None:
    outcome: list[int] = []
    finished = threading.Event()

    async def waiter(target: Task[int]) -> None:
        outcome.append(await target)
        finished.set()

    source: TaskCompletionSource[int] = TaskCompletionSource()
    Task.run(waiter(source.task))  # waiter Task dropped; only the source is kept
    time.sleep(0.05)
    _collect()

    source.set_result(41)

    assert finished.wait(5.0)
    assert outcome == [41]


def test_queued_task_survives_collection_without_references() -> None:
    ran = threading.Event()
    gate = threading.Event()

    def block() -> None:
        gate.wait(5.0)

    Task.configure(min_workers=1, max_workers=1)
    Task.run(block)
    Task.run(ran.set)  # queued behind the blocked worker, reference dropped
    _collect()
    gate.set()

    assert ran.wait(5.0)


# ---------------------------------------------------------------------------
# Shutdown still finds pending work
# ---------------------------------------------------------------------------


def test_shutdown_cancels_pending_tasks_that_are_still_referenced() -> None:
    async def waiter(target: Task[Any]) -> None:
        await target

    source = TaskCompletionSource()
    awaiting = Task.run(waiter(source.task))
    _wait_until(lambda: awaiting._waiting_on is not None)

    report = Task.shutdown(grace_timeout=1.0, worker_timeout=1.0)

    assert awaiting.cancelled()
    assert source.task.cancelled()
    assert report.tasks_cancelled >= 2
