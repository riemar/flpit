"""Finished tasks and what they reference are freed promptly, without the cyclic GC.

* A task's context holds the task as the current task. A finished task drops its
  context, so reference counting frees it as soon as the last reference goes.
* A failed task's exception keeps its traceback, and with it the frames it passed
  through, including the runtime's own and, through each frame's caller, the frames below
  them. The runtime's frames on those paths drop the task before they return or raise,
  so a failed task and the objects in its frames are freed by reference counting too,
  however its failure was observed. (Frames of user code that keep the task in a
  variable still tie it into a cycle, as with any stored exception in Python.)
* The timer thread keeps no task in its variables while it waits.
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
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task
from flpit.threading import AsyncLocal

FREE_THREADED = not getattr(sys, "_is_gil_enabled", lambda: True)()
# Generous for slow CI machines, yet far below the 20 s idle timeout that used to keep objects alive.
TIMEOUT = 5.0


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


def failing_sync_work() -> None:
    payload = Payload()
    raise RuntimeError(f"failed with {payload!r}")


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
    wait_until_dead(task_ref, timeout=TIMEOUT)
    wait_until_dead(result_ref, timeout=TIMEOUT)


async def failing_after_await() -> None:
    payload = Payload()
    await Task.yield_now()
    raise RuntimeError(f"failed with {payload!r}")


FAILING = {
    "Task.run(sync)": lambda: Task.run(failing_sync_work),
    "Task.run(async)": lambda: Task.run(failing_work),
    "Task.run(async, after an await)": lambda: Task.run(failing_after_await),
    "run_inline(sync)": lambda: Task.run_inline(failing_sync_work),
    "run_inline(async)": lambda: Task.run_inline(failing_work),
    "run_inline(async, after an await)": lambda: Task.run_inline(failing_after_await),
}


def observe_nothing(start: Any) -> weakref.ref[Any]:
    t = start()
    while not t.done():
        time.sleep(0.001)
    ref = weakref.ref(t)
    del t  # a variable of this frame would tie the task into the traceback's cycle
    return ref


def observe_result(start: Any) -> weakref.ref[Any]:
    t = start()
    with pytest.raises(RuntimeError):
        t.result()
    ref = weakref.ref(t)
    del t
    return ref


def observe_await(start: Any) -> weakref.ref[Any]:
    refs: list[weakref.ref[Any]] = []

    async def waiter() -> None:
        inner = start()
        refs.append(weakref.ref(inner))
        try:
            await inner
        except RuntimeError:
            pass
        del inner

    Task.run(waiter).result()
    return refs[0]


@pytest.mark.parametrize("start", list(FAILING.values()), ids=list(FAILING))
@pytest.mark.parametrize("observe", [observe_nothing, observe_result, observe_await], ids=["unobserved", "result", "awaited"])
def test_a_failed_task_and_its_frames_are_freed_without_the_cyclic_gc(
        no_cyclic_gc: None, several_workers: None, start: Any, observe: Any
) -> None:
    payloads: list[weakref.ref[Payload]] = []
    original = Payload.__init__

    def track(self: Payload) -> None:
        original(self)
        payloads.append(weakref.ref(self))

    Payload.__init__ = track  # type: ignore[method-assign]
    try:
        task_ref = Task.run(observe, start).result()  # started on a worker, like a framework does
    finally:
        Payload.__init__ = original  # type: ignore[method-assign]
    wait_until_dead(task_ref, timeout=TIMEOUT)
    wait_until_dead(payloads[0], timeout=TIMEOUT)  # a local of the failed frame


@pytest.mark.parametrize("inline", [False, True], ids=["Task.run", "run_inline"])
def test_a_cancelled_task_and_its_frames_are_freed_without_the_cyclic_gc(
        no_cyclic_gc: None, several_workers: None, inline: bool
) -> None:
    refs: list[weakref.ref[Any]] = []

    async def waits(token: CancellationToken) -> None:
        payload = Payload()
        refs.append(weakref.ref(payload))
        await Task.delay(60, token=token)  # still pending in the timer when cancelled

    def scenario() -> weakref.ref[Any]:
        cts = CancellationTokenSource()
        t = (Task.run_inline if inline else Task.run)(waits, cts.token)
        while not refs:
            time.sleep(0.001)
        cts.cancel()
        with pytest.raises(OperationCanceledError):
            t.result()
        ref = weakref.ref(t)
        del t, cts
        return ref

    task_ref = Task.run(scenario).result()
    wait_until_dead(task_ref, timeout=TIMEOUT)
    wait_until_dead(refs[0], timeout=TIMEOUT)


def test_a_failed_task_is_collected_at_the_latest_by_the_cyclic_gc(several_workers: None) -> None:
    """Even when user code ties it into a cycle (here: the variable ``t``)."""
    t = Task.run(failing_work)
    with pytest.raises(RuntimeError):
        t.result()
    task_ref = weakref.ref(t)
    del t
    deadline = time.perf_counter() + TIMEOUT
    while task_ref() is not None:
        assert time.perf_counter() < deadline, "a failed task leaked"
        gc.collect()
        time.sleep(0.01)


def test_the_timer_thread_keeps_no_task_while_it_waits(no_cyclic_gc: None) -> None:
    pending = Task.delay(60)  # keeps the timer thread waiting with an entry in its heap
    fired = Task.delay(0.01)
    fired.wait()
    ref = weakref.ref(fired)
    del fired
    wait_until_dead(ref, timeout=TIMEOUT)
    cts = CancellationTokenSource()
    cancelled = Task.delay(60, token=cts.token)
    cts.cancel()
    ref = weakref.ref(cancelled)
    del cancelled
    wait_until_dead(ref, timeout=TIMEOUT)
    del pending


def test_async_local_values_set_in_a_task_are_freed_with_it(no_cyclic_gc: None, several_workers: None) -> None:
    request: AsyncLocal[Payload] = AsyncLocal()
    refs: list[weakref.ref[Payload]] = []

    async def handler() -> None:
        payload = Payload()
        refs.append(weakref.ref(payload))
        request.value = payload
        await Task.yield_now()

    Task.run(handler).wait()
    wait_until_dead(refs[0], timeout=TIMEOUT)


def test_inline_tasks_are_freed_without_the_cyclic_gc(no_cyclic_gc: None) -> None:
    async def done() -> Payload:
        return Payload()

    t = Task.run_inline(done)
    task_ref, result_ref = weakref.ref(t), weakref.ref(t.result())
    del t
    wait_until_dead(task_ref, timeout=TIMEOUT)
    wait_until_dead(result_ref, timeout=TIMEOUT)


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
    elapsed = wait_until_dead(ref, timeout=TIMEOUT)
    assert elapsed < TIMEOUT
    assert created_on[0].is_alive()  # freed by the idle wake-up, not by the worker retiring
