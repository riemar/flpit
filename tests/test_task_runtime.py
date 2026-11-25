"""Behaviour of the thread-pool based Task runtime.

These tests pin down the execution model (coroutines run on pool threads, the
pool grows like the .NET thread pool, nothing is funnelled through a scheduler
thread) and the races that model has to get right. They run unchanged on GIL
and free-threaded interpreters.
"""

from __future__ import annotations

import gc
import inspect
import os
import socket
import threading
import time
import warnings
from typing import Any

import pytest

import flpit.task as task_module
from flpit.task import (
    CancellationTokenSource,
    IO,
    OperationCanceledError,
    RuntimeShutdownError,
    Task,
    TaskCompletionSource,
)
from flpit.threading import AsyncLocal


@pytest.fixture
def pool():
    """Give a test its own runtime with the worker limits it asks for."""
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)

    def configure(**limits: int) -> None:
        Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
        Task.configure(**limits)

    yield configure

    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


def _worker_names() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith("Task-worker")]


# ---------------------------------------------------------------------------
# Execution model
# ---------------------------------------------------------------------------

def test_coroutines_run_in_parallel_on_pool_threads(pool) -> None:
    """Two coroutine bodies can be inside blocking code at the same time."""
    pool(min_workers=2, max_workers=2)
    rendezvous = threading.Barrier(2)

    async def body() -> str:
        rendezvous.wait(timeout=5)  # only passes if both bodies run concurrently
        return threading.current_thread().name

    names = Task.when_all(Task.run(body), Task.run(body)).result()

    assert len(set(names)) == 2
    assert all(name.startswith("Task-worker") for name in names)


def test_no_scheduler_thread_and_workers_are_daemons(pool) -> None:
    pool(max_workers=3)

    async def work() -> int:
        await Task.yield_now()
        return await Task.run(lambda: 1)

    assert Task.run(work).result() == 1

    threads = {t.name: t for t in threading.enumerate()}
    assert "Task-runtime" not in threads
    workers = [t for name, t in threads.items() if name.startswith("Task-worker")]
    assert workers and all(t.daemon for t in workers)
    # No socket was awaited, so no selector thread was needed either.
    assert "Task-io" not in threads


def test_awaiting_completed_task_continues_inline(pool) -> None:
    """Like .NET: awaiting something already complete does not reschedule."""
    pool(max_workers=4)
    done = Task.run(lambda: 5)
    assert done.result() == 5

    async def work() -> tuple[int, int]:
        before = threading.get_ident()
        total = 0
        for _ in range(1000):
            total += await done
        return total, int(before == threading.get_ident())

    assert Task.run(work).result() == (5000, 1)


def test_execution_context_follows_the_task_across_threads(pool) -> None:
    pool(min_workers=4, max_workers=4)
    local = AsyncLocal[str](default="unset")
    local.value = "creator"

    async def child() -> str:
        return local.value or ""

    async def work() -> list[str]:
        seen = [local.value or ""]
        local.value = "task"
        for _ in range(20):
            await Task.yield_now()
            await Task.delay(0.001)
        seen.append(local.value or "")
        seen.append(await Task.run(child))  # captured where it was created
        return seen

    try:
        assert Task.run(work).result() == ["creator", "task", "task"]
        assert local.value == "creator"  # the task's changes stay in the task
        # Worker threads themselves never keep a task's values.
        assert Task.run(lambda: 0).result() == 0
    finally:
        local.value = "unset"


def test_unsupported_awaitable_is_reported_inside_the_coroutine(pool) -> None:
    pool(max_workers=2)

    class Foreign:
        def __await__(self):
            yield "not a flpit operation"

    async def work() -> str:
        try:
            await Foreign()
        except RuntimeError as error:
            return str(error)
        return "no error"

    assert "only supports Task awaitables" in Task.run(work).result()


def test_task_cannot_await_itself(pool) -> None:
    pool(max_workers=2)
    holder: list[Task[Any]] = []
    ready = threading.Event()

    async def work() -> str:
        ready.wait(5)
        try:
            await holder[0]
        except RuntimeError as error:
            return str(error)
        return "no error"

    holder.append(Task.run(work))
    ready.set()
    assert holder[0].result() == "a task cannot await itself"


# ---------------------------------------------------------------------------
# Pool sizing (.NET ThreadPool semantics)
# ---------------------------------------------------------------------------

def test_workers_start_on_demand_up_to_min_workers(pool) -> None:
    pool(min_workers=4, max_workers=4)
    release = threading.Event()
    entered = threading.Barrier(5)

    def hold() -> None:
        entered.wait(5)
        release.wait(5)

    held = [Task.run(hold) for _ in range(4)]
    try:
        entered.wait(5)  # all four are running concurrently, no delay
        assert len(_worker_names()) == 4
    finally:
        release.set()
    Task.when_all(held).result()


def test_max_workers_is_a_hard_limit(pool) -> None:
    pool(max_workers=1)
    release = threading.Event()
    started = threading.Event()

    def hold() -> None:
        started.set()
        release.wait(5)

    blocker = Task.run(hold)
    assert started.wait(2)
    victim = Task.run(lambda: "ran")
    try:
        time.sleep(0.8)  # longer than the starvation interval
        assert not victim.done()
        assert len(_worker_names()) == 1
    finally:
        release.set()
    assert victim.result() == "ran"
    blocker.result()


def test_a_waiting_worker_is_replaced_quickly(pool) -> None:
    """A worker waiting (not computing) while work is queued gets a replacement within ms."""
    pool(min_workers=1, max_workers=4)
    release = threading.Event()
    started = threading.Event()

    def hold() -> None:
        started.set()
        release.wait(10)

    blocker = Task.run(hold)
    assert started.wait(2)
    victim = Task.run(lambda: threading.current_thread().name)
    try:
        deadline = time.monotonic() + 2
        while not victim.done() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert victim.done()
        assert not blocker.done()
    finally:
        release.set()
    assert victim.result().startswith("Task-worker")
    blocker.result()


def test_starved_pool_injects_workers_beyond_min(pool) -> None:
    """A worker that computes is not replaced quickly, but queued work still gets a thread."""
    pool(min_workers=1, max_workers=4)
    started = threading.Event()
    stop = threading.Event()

    def compute() -> None:
        started.set()
        while not stop.is_set():
            pass

    blocker = Task.run(compute)
    assert started.wait(2)
    victim = Task.run(lambda: threading.current_thread().name)
    try:
        # Not quickly: the one worker keeps the CPU it may use busy ...
        time.sleep(0.1)
        assert not victim.done()
        # ... but the starvation rule adds a worker well before the blocker stops.
        deadline = time.monotonic() + 5
        while not victim.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert victim.done()
        assert not blocker.done()
    finally:
        stop.set()
    assert victim.result().startswith("Task-worker")
    blocker.result()


def test_surplus_workers_retire_when_idle(pool, monkeypatch) -> None:
    monkeypatch.setattr(task_module._WorkerPool, "_IDLE_TIMEOUT", 0.05)
    pool(min_workers=1, max_workers=8)

    async def child() -> int:
        await Task.delay(0.02)  # suspends, so the parent cannot finish it inline
        return 1

    async def parent() -> int:
        return Task.run(child).result()  # blocks: the pool adds a worker

    assert Task.when_all([Task.run(parent) for _ in range(2)]).result() == [1, 1]
    assert len(_worker_names()) >= 2

    deadline = time.monotonic() + 5
    while len(_worker_names()) > 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(_worker_names()) == 1  # back to min_workers, not below
    assert Task.run(lambda: 2).result() == 2


def test_blocking_result_in_worker_gets_a_replacement_thread(pool) -> None:
    """A worker blocked on a task that needs another worker is compensated for."""
    pool(min_workers=1, max_workers=8)

    async def child() -> int:
        # Suspends, so it cannot simply be finished inline by the parent: its
        # second half needs a worker while the parent's worker is blocked.
        await Task.delay(0.02)
        return 21

    async def parent() -> int:
        return Task.run(child).result() * 2

    started = time.monotonic()
    assert Task.run(parent).result() == 42
    assert time.monotonic() - started < 2
    assert len(_worker_names()) >= 2


# ---------------------------------------------------------------------------
# Task.result() inlining (.NET: Task.Wait runs an unstarted task inline)
# ---------------------------------------------------------------------------

def test_result_runs_unstarted_task_inline_on_the_waiting_worker(pool) -> None:
    """With one worker there is nobody else who could run the child."""
    pool(max_workers=1)

    def child() -> tuple[int, int]:
        return 21, threading.get_ident()

    async def async_child() -> tuple[int, int]:
        return 21, threading.get_ident()

    def sync_parent() -> bool:
        value, thread = Task.run(child).result()
        return value == 21 and thread == threading.get_ident()

    async def async_parent() -> bool:
        value, thread = Task.run(async_child).result()
        other, _ = Task.run(child).result()
        return value + other == 42 and thread == threading.get_ident()

    assert Task.run(sync_parent).result() is True
    assert Task.run(async_parent).result() is True
    assert len(_worker_names()) == 1


def test_inlined_task_runs_once_in_its_own_context_and_keeps_its_outcome(pool) -> None:
    pool(max_workers=1)
    local: AsyncLocal[str] = AsyncLocal()
    runs: list[str | None] = []

    def child() -> str | None:
        runs.append(local.value)
        local.value = "child"
        return local.value

    def failing() -> None:
        raise LookupError("boom")

    def parent() -> tuple[Any, ...]:
        local.value = "parent"
        inlined = Task.run(child)
        value = inlined.result()
        failed = Task.run(failing)
        with pytest.raises(LookupError, match="boom"):
            failed.result()
        cancelled = Task.run(child, token=cancelled_token)
        with pytest.raises(OperationCanceledError):
            cancelled.result()
        return value, local.value, inlined.result(), failed.status, cancelled.status

    source = CancellationTokenSource()
    source.cancel()
    cancelled_token = source.token

    assert Task.run(parent).result() == (
        "child", "parent", "child", Task.FAILED, Task.CANCELLED
    )
    # The queued start items of the inlined tasks found nothing left to do.
    assert Task.run(lambda: len(runs)).result() == 1
    assert runs == ["parent"]  # captured the parent's context when created


def test_result_inlines_nested_tasks_without_extra_workers(pool) -> None:
    pool(max_workers=1)

    def nested(depth: int) -> int:
        if depth == 0:
            return 0
        return 1 + Task.run(nested, depth - 1).result()

    # Within the inlining depth limit: no second worker is ever needed.
    assert Task.run(nested, 20).result() == 20


def test_result_stops_inlining_when_nested_too_deeply(pool) -> None:
    pool(min_workers=1, max_workers=64)
    depth = task_module._MAX_INLINE_DEPTH + 3

    def nested(remaining: int) -> int:
        if remaining == 0:
            return 0
        return 1 + Task.run(nested, remaining - 1).result()

    # Past the limit the worker blocks and the pool compensates instead.
    assert Task.run(nested, depth).result() == depth
    assert len(_worker_names()) > 1


def test_result_from_a_foreign_thread_does_not_run_the_task_there(pool) -> None:
    pool(max_workers=1)
    assert Task.run(threading.get_ident).result() != threading.get_ident()
    assert Task.run(lambda: threading.current_thread().name).result().startswith(
        "Task-worker"
    )


def test_inlined_coroutine_runs_to_its_first_pending_await(pool) -> None:
    pool(min_workers=2, max_workers=2)
    steps: list[tuple[str, int]] = []

    async def child() -> int:
        steps.append(("first", threading.get_ident()))
        await Task.delay(0.02)
        steps.append(("second", threading.get_ident()))
        return 7

    def parent() -> tuple[int, int]:
        return Task.run(child).result(), threading.get_ident()

    # Occupy the second worker so the child is still unstarted when the
    # parent asks for its result.
    release = threading.Event()
    entered = threading.Event()

    def occupy() -> None:
        entered.set()
        release.wait(5)

    blocker = Task.run(occupy)
    assert entered.wait(2)
    running = Task.run(parent)
    deadline = time.monotonic() + 2
    while not steps and time.monotonic() < deadline:
        time.sleep(0.005)
    release.set()
    value, parent_thread = running.result()
    blocker.result()
    assert value == 7
    assert steps[0] == ("first", parent_thread)
    assert steps[1][0] == "second" and steps[1][1] != parent_thread


def test_waiter_resumed_by_an_inlined_task_is_not_held_back_by_the_caller(pool) -> None:
    """Completing a task inline makes its awaiters runnable right away.

    They must go to the pool: the calling worker is still busy with its own
    work item and may be about to block on exactly such an awaiter.
    """
    pool(min_workers=2, max_workers=2)
    cell: dict[str, Task[int]] = {}
    gate_entered = threading.Event()
    gate_release = threading.Event()
    blocker_entered = threading.Event()
    blocker_release = threading.Event()

    def gate() -> None:
        gate_entered.set()
        gate_release.wait(5)

    def blocker() -> None:
        blocker_entered.set()
        blocker_release.wait(5)

    def parent() -> tuple[bool, int, int]:
        box: TaskCompletionSource[None] = TaskCompletionSource()

        async def waiter() -> int:
            await box.task
            return await cell["inner"] + 1

        waiting = Task.run(waiter)
        while waiting._waiting_on is None:
            time.sleep(0.001)
        # Keep the other worker busy while the queue is arranged as:
        # resume waiter, blocker, inner.
        Task.run(gate)
        assert gate_entered.wait(2)
        box.set_result()
        blocking = Task.run(blocker)
        cell["inner"] = inner = Task.run(threading.get_ident)
        # The other worker now parks the waiter on ``inner`` and then gets
        # stuck in the blocker; ``inner`` has not started.
        gate_release.set()
        assert blocker_entered.wait(2)
        inlined_on = inner.result()
        blocker_release.set()
        deadline = time.monotonic() + 5
        while not waiting.done() and time.monotonic() < deadline:
            time.sleep(0.005)
        finished = waiting.done()
        blocking.result()
        return finished, inlined_on, threading.get_ident()

    finished, inlined_on, parent_thread = Task.run(parent).result()
    assert inlined_on == parent_thread
    assert finished


def test_configure_validates_worker_limits(pool) -> None:
    pool(max_workers=2)
    Task.shutdown()
    with pytest.raises(ValueError):
        Task.configure(min_workers=0)
    with pytest.raises(ValueError):
        Task.configure(max_workers=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not exceed"):
        Task.configure(min_workers=5, max_workers=2)

    Task.configure(max_workers=7)
    assert task_module._runtime_config == {"min_workers": 7, "max_workers": 7, "burst_workers": 256}
    Task.configure(min_workers=2)
    assert task_module._runtime_config == {"min_workers": 2, "max_workers": 7, "burst_workers": 256}

    assert Task.run(lambda: 1).result() == 1
    with pytest.raises(RuntimeError, match="before runtime startup"):
        Task.configure(max_workers=3)


# ---------------------------------------------------------------------------
# Combinators and promises
# ---------------------------------------------------------------------------

def test_deep_chain_of_aggregates_does_not_overflow_the_stack(pool) -> None:
    pool(max_workers=4)
    source: TaskCompletionSource[int] = TaskCompletionSource()
    task: Task[Any] = source.task
    for depth in range(5000):
        task = Task.when_all(task) if depth % 2 else Task.when_any(task)

    source.set_result(7)

    assert isinstance(task.result(), list)


def test_when_all_scales_linearly(pool) -> None:
    pool(max_workers=4)
    count = 20_000
    sources = [TaskCompletionSource[int]() for _ in range(count)]
    aggregate = Task.when_all([source.task for source in sources])

    started = time.monotonic()
    for index, source in enumerate(sources):
        source.set_result(index)
    assert aggregate.result() == list(range(count))
    # Quadratic behaviour would take minutes here.
    assert time.monotonic() - started < 20


def test_when_any_detaches_from_losers(pool) -> None:
    pool(max_workers=2)
    loser: TaskCompletionSource[int] = TaskCompletionSource()
    for _ in range(200):
        winner: TaskCompletionSource[int] = TaskCompletionSource()
        aggregate = Task.when_any(loser.task, winner.task)
        winner.set_result(1)
        assert aggregate.result() is winner.task

    # A long-lived task must not accumulate one dead registration per race.
    assert not loser.task._continuations
    loser.set_result(0)


def test_collect_yields_every_task_once_in_completion_order(pool) -> None:
    pool(max_workers=4)
    sources = [TaskCompletionSource[int]() for _ in range(300)]
    tasks = [source.task for source in sources]
    order = list(range(299, -1, -1))

    async def consume() -> list[int]:
        seen = []
        async for finished in Task.collect(tasks):
            seen.append(finished.result())
        return seen

    consumer = Task.run(consume)
    # Tasks that are already complete when collect() first looks are reported
    # in input order, so wait until the consumer is listening on all of them.
    deadline = time.monotonic() + 5
    while not tasks[-1]._continuations and time.monotonic() < deadline:
        time.sleep(0.001)
    for index in order:
        sources[index].set_result(index)
        if index % 50 == 0:
            time.sleep(0.005)

    assert consumer.result() == order


def test_collect_of_nothing_and_of_completed_tasks(pool) -> None:
    pool(max_workers=2)
    done = [Task.run(lambda value=value: value) for value in range(5)]
    Task.when_all(done).result()

    async def consume(*args: Any) -> list[int]:
        return [finished.result() async for finished in Task.collect(*args)]

    assert Task.run(consume, []).result() == []
    assert Task.run(consume, done).result() == [0, 1, 2, 3, 4]


def test_completion_source_never_runs_awaiters_on_the_completing_thread(pool) -> None:
    pool(max_workers=2)
    source: TaskCompletionSource[int] = TaskCompletionSource()
    parked = threading.Event()

    async def awaiter() -> str:
        parked.set()
        await source.task
        return threading.current_thread().name

    task = Task.run(awaiter)
    assert parked.wait(2)
    time.sleep(0.02)
    source.set_result(1)  # completed from the test's thread

    assert task.result().startswith("Task-worker")


def test_awaiting_cancelled_task_raises_its_cancellation_exception(pool) -> None:
    pool(max_workers=2)
    cts = CancellationTokenSource()
    source: TaskCompletionSource[int] = TaskCompletionSource()

    async def awaiter() -> OperationCanceledError:
        try:
            await source.task
        except OperationCanceledError as error:
            return error
        raise AssertionError("not cancelled")

    task = Task.run(awaiter)
    time.sleep(0.02)
    source.set_canceled(cts.token)

    error = task.result()
    assert error.token is cts.token  # same information as source.task.result()
    cts.dispose()


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------

def test_delay_zero_is_already_complete_and_bad_delays_are_rejected(pool) -> None:
    pool(max_workers=1)
    assert Task.delay(0).done()
    with pytest.raises(ValueError):
        Task.delay(-0.1)
    with pytest.raises(ValueError):
        Task.delay(float("nan"))


def test_delays_complete_without_a_free_worker(pool) -> None:
    """Timers are not pool work: a saturated pool does not delay them."""
    pool(max_workers=1)
    release = threading.Event()
    started = threading.Event()

    def hold() -> None:
        started.set()
        release.wait(5)

    blocker = Task.run(hold)
    assert started.wait(2)
    try:
        delays = [Task.delay(0.01 * (index % 5)) for index in range(200)]
        deadline = time.monotonic() + 2
        while not all(d.done() for d in delays) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert all(d.done() for d in delays)
    finally:
        release.set()
    blocker.result()


def test_delay_is_not_early(pool) -> None:
    pool(max_workers=1)

    async def sleeper() -> float:
        started = time.perf_counter()
        await Task.delay(0.05)
        return time.perf_counter() - started

    assert Task.run(sleeper).result() >= 0.05 - 0.002


def test_earlier_timer_wakes_the_sleeping_timer_thread() -> None:
    # The timer thread sleeps until the nearest deadline. A timer that is due sooner than
    # that deadline must wake it up. No timing is compared: with the wake-up missing the
    # short delay completes after the long one (two minutes), with it after ~20 ms, and a
    # loaded runner (about 0.2 s late in stress runs) cannot blur a gap that large.
    long_timer = CancellationTokenSource()
    try:
        Task.delay(120, token=long_timer.token)  # the timer thread now waits for this one
        time.sleep(0.05)  # let it go to sleep
        started = time.perf_counter()
        short = Task.delay(0.02)
        short.wait(30)
        assert short.done(), f"a 20 ms delay was still pending after {time.perf_counter() - started:.1f} s"
    finally:
        long_timer.cancel()
        long_timer.dispose()


def test_cancel_after_uses_one_shared_timer_thread(pool) -> None:
    pool(max_workers=1)
    before = threading.active_count()
    sources = [CancellationTokenSource() for _ in range(300)]
    try:
        for source in sources:
            source.cancel_after(60)
        assert threading.active_count() <= before + 1

        fired = threading.Event()
        sources[0].token.register(fired.set)
        sources[0].cancel_after(0.02)  # re-arming replaces the earlier timer
        assert fired.wait(2)
        assert not sources[1].is_cancellation_requested
    finally:
        for source in sources:
            source.dispose()


def test_token_cancellation_racing_delay_completion_never_hangs(pool) -> None:
    pool(min_workers=4, max_workers=4)

    async def one(index: int) -> str:
        cts = CancellationTokenSource()
        try:
            delay = Task.delay(0.002, token=cts.token)
            if index % 2:
                await Task.delay(0.002)
            else:
                await Task.yield_now()
            cts.cancel()
            try:
                await delay
                return "completed"
            except OperationCanceledError:
                return "cancelled"
        finally:
            cts.dispose()

    outcomes = Task.when_all([Task.run(one, index) for index in range(400)]).result()
    assert set(outcomes) <= {"completed", "cancelled"}


# ---------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------

def test_many_tasks_wait_on_sockets_concurrently(pool) -> None:
    pool(max_workers=4)
    pairs = [socket.socketpair() for _ in range(20)]
    for reader, _ in pairs:
        reader.setblocking(False)

    async def read(reader: socket.socket) -> bytes:
        await IO.wait_readable(reader)
        return reader.recv(16)

    try:
        tasks = [Task.run(read, reader) for reader, _ in pairs]
        time.sleep(0.05)
        assert not any(task.done() for task in tasks)
        for index, (_, writer) in enumerate(pairs):
            writer.send(str(index).encode())
        assert Task.when_all(tasks).result() == [str(i).encode() for i in range(20)]
        assert any(t.name == "Task-io" for t in threading.enumerate())
    finally:
        for reader, writer in pairs:
            reader.close()
            writer.close()


def test_waiting_on_closed_socket_fails_the_wait_only(pool) -> None:
    pool(max_workers=2)
    reader, writer = socket.socketpair()
    reader.close()

    async def wait() -> str:
        try:
            await IO.wait_readable(reader)
        except ValueError as error:
            return str(error)
        return "no error"

    try:
        assert "closed socket" in Task.run(wait).result()
        assert Task.run(lambda: 1).result() == 1
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def test_shutdown_cancels_work_that_never_started(pool) -> None:
    pool(max_workers=1)
    release = threading.Event()
    started = threading.Event()
    ran: list[str] = []

    def hold() -> str:
        started.set()
        release.wait(5)
        return "held"

    async def never_started() -> None:
        ran.append("coroutine")

    blocker = Task.run(hold)
    assert started.wait(2)
    coroutine = never_started()
    queued = [Task.run(lambda: ran.append("function")), Task.run(coroutine)]
    promise: TaskCompletionSource[int] = TaskCompletionSource()

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # e.g. "coroutine was never awaited"
        report = Task.shutdown(grace_timeout=0.2, worker_timeout=0.05)
        release.set()
        gc.collect()

    assert report.workers_still_running == 1 and report.timed_out
    assert report.tasks_cancelled >= 3
    assert all(task.cancelled() for task in queued)
    assert promise.task.cancelled()
    assert promise.try_set_result(1) is False
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    assert ran == []
    # The function was already running: it is reported, not abandoned early.
    assert blocker.cancelled()


def test_running_function_may_finish_within_worker_timeout(pool) -> None:
    pool(max_workers=1)
    started = threading.Event()

    def short_job() -> str:
        started.set()
        time.sleep(0.1)
        return "finished"

    job = Task.run(short_job)
    assert started.wait(2)
    began = time.monotonic()
    report = Task.shutdown(grace_timeout=5.0, worker_timeout=2.0)

    # A function cannot be cancelled, so it does not use up the grace period
    # meant for coroutines; it gets worker_timeout and keeps its result.
    assert time.monotonic() - began < 2
    assert report == task_module.ShutdownReport(True, 0, 0, False)
    assert job.result() == "finished"


def test_shutdown_rejects_new_work_and_releases_blocked_waiters(pool) -> None:
    pool(max_workers=2)
    entered = threading.Event()
    shutting_down = threading.Event()

    async def stubborn() -> None:
        while True:
            try:
                entered.set()
                await Task.delay(30)
            except OperationCanceledError:
                shutting_down.set()
                continue  # ignores cancellation: must be forced

    task = Task.run(stubborn)
    assert entered.wait(2)
    outcome: list[Any] = []

    def wait_for_it() -> None:
        try:
            task.result()
        except BaseException as error:
            outcome.append(error)

    waiter = threading.Thread(target=wait_for_it)
    waiter.start()
    rejected: list[bool] = []

    def submit_during_shutdown() -> None:
        # Submit once shutdown has visibly started; it then lasts the whole grace period,
        # because stubborn ignores the cancellation. (A fixed sleep could also land after
        # shutdown finished, where a fresh runtime accepts the work.)
        assert shutting_down.wait(2)
        try:
            Task.run(lambda: 1)
        except RuntimeShutdownError:
            rejected.append(True)

    submitter = threading.Thread(target=submit_during_shutdown)
    submitter.start()
    report = Task.shutdown(grace_timeout=0.3, worker_timeout=0.5)
    submitter.join(2)
    waiter.join(2)

    assert rejected == [True]
    assert not waiter.is_alive()
    assert isinstance(outcome[0], OperationCanceledError)
    assert report.tasks_cancelled >= 1
    assert Task.run(lambda: 2).result() == 2  # a fresh runtime starts lazily


def test_concurrent_shutdown_calls_agree(pool) -> None:
    pool(max_workers=2)
    Task.run(lambda: 1).result()
    reports: list[Any] = []
    threads = [
        threading.Thread(target=lambda: reports.append(Task.shutdown(grace_timeout=0.2)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert len(reports) == 4
    assert all(report.runtime_stopped and not report.timed_out for report in reports)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_runtime_is_usable_in_a_forked_child(pool) -> None:
    pool(max_workers=2)
    assert Task.run(lambda: 1).result() == 1  # threads exist in the parent

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # fork with threads
        pid = os.fork()
    if pid == 0:  # pragma: no cover - runs in the child
        code = 1
        try:
            async def work() -> int:
                await Task.delay(0.01)
                return await Task.run(lambda: 41) + 1

            code = 0 if Task.run(work).result() == 42 else 2
        finally:
            os._exit(code)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        finished, status = os.waitpid(pid, os.WNOHANG)
        if finished:
            assert os.waitstatus_to_exitcode(status) == 0
            return
        time.sleep(0.02)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    pytest.fail("forked child hung using the Task runtime")


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------

def test_mixed_workload_from_many_threads(pool) -> None:
    pool(min_workers=6, max_workers=12)

    async def leaf(index: int) -> int:
        if index % 3 == 0:
            await Task.yield_now()
        if index % 7 == 0:
            await Task.delay(0.001)
        return index

    async def fan_out(count: int) -> int:
        return sum(await Task.when_all([Task.run(leaf, index) for index in range(count)]))

    async def chain(depth: int) -> int:
        return 0 if depth == 0 else 1 + await Task.run(chain, depth - 1)

    async def single_winner() -> int:
        source: TaskCompletionSource[int] = TaskCompletionSource()
        wins = await Task.when_all([Task.run(source.try_set_result, n) for n in range(8)])
        assert sum(wins) == 1
        return await source.task

    async def cancelled_waiters() -> int:
        cts = CancellationTokenSource()

        async def waiter() -> int:
            try:
                await Task.delay(30, token=cts.token)
            except OperationCanceledError:
                return 1
            return 0

        waiters = [Task.run(waiter) for _ in range(20)]
        await Task.yield_now()
        cts.cancel()
        try:
            return sum(await Task.when_all(waiters))
        finally:
            cts.dispose()

    async def root() -> None:
        for _ in range(5):
            results = await Task.when_all(
                Task.run(fan_out, 150),
                Task.run(chain, 60),
                Task.run(single_winner),
                Task.run(cancelled_waiters),
            )
            assert results[0] == sum(range(150))
            assert results[1] == 60
            assert results[3] == 20

    errors: list[BaseException] = []

    def external(count: int) -> None:
        try:
            for index in range(count):
                assert Task.run(leaf, index).result() == index
                assert Task.run(lambda: 5).result() == 5
        except BaseException as error:  # surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=external, args=(100,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    roots = [Task.run(root) for _ in range(4)]
    for task in roots:
        task.result()
    for thread in threads:
        thread.join(30)

    assert not errors
    assert not any(thread.is_alive() for thread in threads)
