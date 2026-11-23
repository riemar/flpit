"""Finished tasks and what they reference are freed promptly, without the cyclic GC.

* A task's context holds the task as the current task. A finished task drops its
  context, so reference counting frees it as soon as the last reference goes.
* On free-threaded builds an object is freed by the thread that created it; when another
  thread drops the last reference, the creator frees it the next time it runs Python
  code. Idle runtime threads therefore wake up regularly instead of blocking for the
  whole idle timeout (20 s), which kept such objects alive that long.
"""
from __future__ import annotations

import gc
import sys
import threading
import time
import weakref
from collections.abc import Iterator
from typing import Any

import pytest

import flpit.task as task_module
from flpit.task import Task
from flpit.threading import AsyncLocal

FREE_THREADED = not getattr(sys, "_is_gil_enabled", lambda: True)()


@pytest.fixture
def no_cyclic_gc() -> Iterator[None]:
    """Anything freed in these tests must be freed by reference counting."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


@pytest.fixture
def several_workers() -> Iterator[None]:
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(min_workers=4, max_workers=16)
    yield
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


def wait_until_dead(ref: weakref.ref[Any], timeout: float) -> float:
    """Seconds until ``ref`` is dead; fails after ``timeout``."""
    start = time.perf_counter()
    while ref() is not None:
        elapsed = time.perf_counter() - start
        assert elapsed < timeout, f"still alive after {elapsed:.1f} s"
        time.sleep(0.005)
    return time.perf_counter() - start


class Payload:
    pass


def sync_work() -> Payload:
    return Payload()


async def async_work() -> Payload:
    await Task.yield_now()
    return Payload()


async def failing_work() -> None:
    payload = Payload()  # referenced from the traceback's frame
    raise RuntimeError(f"failed with {payload!r}")


@pytest.mark.parametrize("work", [sync_work, async_work], ids=["sync", "async"])
def test_a_finished_task_and_its_result_are_freed_without_the_cyclic_gc(
        no_cyclic_gc: None, several_workers: None, work: Any
) -> None:
    t = Task.run(work)
    task_ref = weakref.ref(t)
    result_ref = weakref.ref(t.result())
    del t
    wait_until_dead(task_ref, timeout=2.0)
    wait_until_dead(result_ref, timeout=2.0)


def test_a_failed_task_and_its_traceback_are_freed_without_the_cyclic_gc(
        no_cyclic_gc: None, several_workers: None
) -> None:
    t = Task.run(failing_work)
    error = t.exception()
    assert isinstance(error, RuntimeError)
    task_ref = weakref.ref(t)
    del t, error
    wait_until_dead(task_ref, timeout=2.0)


def test_async_local_values_set_in_a_task_are_freed_with_it(no_cyclic_gc: None, several_workers: None) -> None:
    request: AsyncLocal[Payload] = AsyncLocal()
    refs: list[weakref.ref[Payload]] = []

    async def handler() -> None:
        payload = Payload()
        refs.append(weakref.ref(payload))
        request.value = payload
        await Task.yield_now()

    Task.run(handler).wait()
    wait_until_dead(refs[0], timeout=2.0)


def test_inline_tasks_are_freed_without_the_cyclic_gc(no_cyclic_gc: None) -> None:
    async def done() -> Payload:
        return Payload()

    t = Task.run_inline(done)
    task_ref, result_ref = weakref.ref(t), weakref.ref(t.result())
    del t
    wait_until_dead(task_ref, timeout=2.0)
    wait_until_dead(result_ref, timeout=2.0)


@pytest.mark.skipif(not FREE_THREADED, reason="objects are freed at once with the GIL")
def test_objects_created_on_an_idle_worker_are_freed_while_it_stays_idle(
        no_cyclic_gc: None, several_workers: None
) -> None:
    created_on: list[threading.Thread] = []

    def create() -> list[Payload]:
        created_on.append(threading.current_thread())
        return [Payload()]

    holder = Task.run(create).result()
    ref = weakref.ref(holder[0])
    holder.clear()  # the last reference goes on this thread, not on the creator
    # The creator parks with nothing to do; it used to free the object only when its
    # 20 s idle timeout expired.
    elapsed = wait_until_dead(ref, timeout=3.0)
    assert elapsed < 3.0
    assert created_on[0].is_alive()  # freed by the idle wake-up, not by the worker retiring
