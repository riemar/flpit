"""Multi-core stress tests for flpit.task (the thread-pool based Task runtime).

Purpose
-------
The ordinary test suite proves behaviour; this file hunts for *timing* bugs
that only show up when many threads really run at the same moment: lost
wake-ups, a task resumed twice, a completion that nobody observes, broken
bookkeeping in the pool, shutdown racing with new work. It is meant for a
machine with 8 or more cores, ideally on a free-threaded interpreter
(3.13t / 3.14t), where workers execute Python code in parallel.

Every test repeats a small racy scenario for a time budget and checks an
invariant that must hold no matter how the threads interleave. Nothing in
here depends on timing for its verdict: a failure is always a broken
invariant or a task that never completed.

How to run
----------
    PYTHONPATH=src python -m pytest test_task_multicore_stress.py -q

    # longer soak, e.g. 30 s per test, repeated
    FLPIT_STRESS_SECONDS=30 PYTHONPATH=src python -m pytest test_task_multicore_stress.py -q
    for i in $(seq 20); do PYTHONPATH=src python -m pytest test_task_multicore_stress.py -q -x || break; done

Knobs (environment variables)
-----------------------------
    FLPIT_STRESS_SECONDS       time budget per test                 (default 3)
    FLPIT_STRESS_WORKERS       pool workers                         (default max(8, cores))
    FLPIT_STRESS_THREADS       foreign threads driving the races    (default max(8, cores))
    FLPIT_STRESS_HANG_TIMEOUT  seconds before "still pending" fails (default 60)
    FLPIT_STRESS_SEED          base seed for the random choices     (default 12345)

What a failure looks like
-------------------------
* ``N of M tasks still pending``: a wake-up or completion was lost. The
  message includes the pool's counters at that moment.
* An assertion about counts/values: something ran twice, not at all, or saw
  another task's state.
* The process exits with thread stack dumps: something blocked so hard that
  even the test's own timeout could not fire (a deadlock). The dump shows
  where every thread is stuck.

A single failure in many runs is still a real bug: please keep the output.
"""

from __future__ import annotations

import faulthandler
import os
import random
import socket
import sys
import threading
import time
import warnings
from typing import Any, Callable, Iterable

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

pytestmark = pytest.mark.stress

CORES = getattr(os, "process_cpu_count", os.cpu_count)() or 1
SECONDS = float(os.environ.get("FLPIT_STRESS_SECONDS", "3"))
WORKERS = int(os.environ.get("FLPIT_STRESS_WORKERS", str(max(8, CORES))))
THREADS = int(os.environ.get("FLPIT_STRESS_THREADS", str(max(8, CORES))))
HANG_TIMEOUT = float(os.environ.get("FLPIT_STRESS_HANG_TIMEOUT", "60"))
SEED = int(os.environ.get("FLPIT_STRESS_SEED", "12345"))
GIL_ENABLED = getattr(sys, "_is_gil_enabled", lambda: True)()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _environment():
    if CORES < 8:
        warnings.warn(
            f"only {CORES} CPU core(s) available: these tests need 8+ cores to "
            "expose parallel races reliably",
            stacklevel=1,
        )
    if GIL_ENABLED:
        warnings.warn(
            "running with the GIL: only one thread executes Python at a time, "
            "so this run exercises thread switching but not true parallelism; "
            "also run on a free-threaded build (3.13t+)",
            stacklevel=1,
        )
    # With the GIL, switch threads far more often than the default 5 ms so
    # that the interleavings are at least dense.
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    yield
    sys.setswitchinterval(previous)


def _worker_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("Task-worker")]


def _install(errors: list[Any], **limits: int) -> None:
    """(Re)start the runtime with the given limits and collect its error reports."""
    Task.shutdown(grace_timeout=0.5, worker_timeout=5.0)
    Task.configure(**limits)
    Task.set_exception_handler(errors.append)


@pytest.fixture(autouse=True)
def errors():
    """Fresh runtime per test; fail on anything the runtime reported as unexpected."""
    previous = dict(task_module._runtime_config)
    reported: list[Any] = []
    _install(reported, min_workers=WORKERS, max_workers=WORKERS * 4)
    # Last line of defence: if a test deadlocks so badly that its own
    # timeouts cannot fire, dump every thread's stack and end the process.
    faulthandler.dump_traceback_later(SECONDS * 6 + HANG_TIMEOUT * 3, exit=True)
    try:
        yield reported
    finally:
        faulthandler.cancel_dump_traceback_later()
        report = Task.shutdown(grace_timeout=1.0, worker_timeout=10.0)
        Task.configure(**previous)
    assert not reported, f"runtime reported {len(reported)} unexpected error(s): {reported[:3]!r}"
    assert report.workers_still_running == 0, report
    deadline = time.monotonic() + 10
    while _worker_threads() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _worker_threads(), "worker threads survived shutdown"


def _pool_state() -> str:
    try:
        pool = task_module._get_runtime()._pool
        return (
            f"workers={pool._count} searching={pool._searching} blocked={pool._blocked} "
            f"parked={len(pool._parked)} queued={len(pool._items)} "
            f"alive_threads={len(_worker_threads())}"
        )
    except Exception as error:  # the internals moved; the test verdict stands
        return f"unavailable ({error!r})"


def _wait(tasks: Iterable[Task[Any]], what: str, timeout: float = HANG_TIMEOUT) -> None:
    """Wait for completion without Task.result(), so a hang becomes a failure."""
    pending = [task for task in tasks if not task.done()]
    total = len(pending)
    deadline = time.monotonic() + timeout
    spins = 0
    while pending:
        spins += 1
        if spins > 200:
            time.sleep(0.0002)
        pending = [task for task in pending if not task.done()]
        if pending and time.monotonic() > deadline:
            pytest.fail(
                f"{len(pending)} of {total} tasks still pending after {timeout:.0f}s "
                f"({what}); pool: {_pool_state()}; first: {pending[:3]!r}"
            )


def _in_threads(count: int, target: Callable[[int], None]) -> None:
    """Run target(index) on ``count`` threads released at the same instant."""
    failures: list[BaseException] = []
    barrier = threading.Barrier(count)

    def run(index: int) -> None:
        try:
            barrier.wait(30)
            target(index)
        except BaseException as error:  # includes pytest's Failed
            failures.append(error)

    threads = [
        threading.Thread(target=run, args=(index,), name=f"stress-{index}", daemon=True)
        for index in range(count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(SECONDS * 4 + HANG_TIMEOUT * 2)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    if stuck:
        pytest.fail(f"stress threads never finished: {stuck}; pool: {_pool_state()}")
    if failures:
        raise failures[0]


def _budget() -> float:
    return time.monotonic() + SECONDS


def _pause(rng: random.Random) -> None:
    """Idle for anything between nothing and a few hundred microseconds.

    The interesting moment is a worker deciding to go to sleep; varying the
    gap makes new work arrive before, during and after that decision.
    """
    kind = rng.randrange(5)
    if kind == 1:
        for _ in range(rng.randrange(3000)):
            pass
    elif kind == 2:
        time.sleep(0)
    elif kind == 3:
        time.sleep(rng.uniform(0, 0.0003))
    elif kind == 4:
        time.sleep(rng.uniform(0.0005, 0.002))


def _sync_echo(value: Any = None) -> Any:
    return value


async def _async_echo(value: Any = None) -> Any:
    return value


async def _await(awaitable: Any) -> Any:
    return await awaitable


async def _delay_then(seconds: float, value: Any = None) -> Any:
    await Task.delay(seconds)
    return value


# ---------------------------------------------------------------------------
# Wake-ups: work queued while workers go idle must always be picked up
# ---------------------------------------------------------------------------

def _one_unit_of_work(rng: random.Random) -> Task[Any]:
    kind = rng.randrange(5)
    if kind == 0:
        return Task.run(_sync_echo, 1)
    if kind == 1:
        return Task.run(_async_echo, 1)
    if kind == 2:
        # A coroutine parks on a source that is completed from this thread.
        source: TaskCompletionSource[int] = TaskCompletionSource()
        task = Task.run(_await, source.task)
        _pause(rng)
        source.set_result(1)
        return task
    if kind == 3:
        return Task.run(_delay_then, rng.uniform(0, 0.0005), 1)
    return Task.run(_await, Task.run(_sync_echo, 1))


def test_single_submitter_never_loses_a_wakeup() -> None:
    """One item at a time into an otherwise idle pool.

    Nobody else queues anything, so a wake-up that gets lost between "worker
    is about to sleep" and "work was queued" is not rescued by later traffic.
    """
    rng = random.Random(SEED)
    end = _budget()
    done = 0
    while time.monotonic() < end:
        task = _one_unit_of_work(rng)
        _wait([task], f"single submitter, item {done}")
        assert task.result() == 1
        done += 1
        _pause(rng)
    assert done > 0


def test_many_submitters_never_lose_a_wakeup() -> None:
    """Bursts from many threads with idle gaps in between."""
    end = _budget()
    totals = [0] * THREADS

    def submitter(index: int) -> None:
        rng = random.Random(SEED + index)
        while time.monotonic() < end:
            burst = [_one_unit_of_work(rng) for _ in range(rng.randrange(1, 6))]
            _wait(burst, f"submitter {index}")
            assert [task.result() for task in burst] == [1] * len(burst)
            totals[index] += len(burst)
            _pause(rng)

    _in_threads(THREADS, submitter)
    assert all(totals)


# ---------------------------------------------------------------------------
# Exactly-once execution and resumption
# ---------------------------------------------------------------------------

def test_task_body_runs_exactly_once_when_result_races_with_the_pool() -> None:
    """Task.result() may run an unstarted task inline while a worker pops it."""
    parents = WORKERS * 3
    children = 8
    end = _budget()
    while time.monotonic() < end:
        runs: list[list[list[int]]] = [[[] for _ in range(children)] for _ in range(parents)]

        def child(p: int, c: int) -> tuple[int, int]:
            runs[p][c].append(threading.get_ident())
            return p, c

        async def async_child(p: int, c: int) -> tuple[int, int]:
            runs[p][c].append(threading.get_ident())
            return p, c

        def spawn(p: int) -> list[Task[tuple[int, int]]]:
            return [
                Task.run(child if c % 2 else async_child, p, c) for c in range(children)
            ]

        def parent(p: int) -> list[tuple[int, int]]:
            return [kid.result() for kid in reversed(spawn(p))]

        async def async_parent(p: int) -> list[tuple[int, int]]:
            return [kid.result() for kid in reversed(spawn(p))]

        tasks = [Task.run(parent if p % 2 else async_parent, p) for p in range(parents)]
        _wait(tasks, "parents blocking on children")
        for p, task in enumerate(tasks):
            assert task.result() == [(p, c) for c in reversed(range(children))]
        executions = [len(runs[p][c]) for p in range(parents) for c in range(children)]
        assert executions == [1] * (parents * children), "a task body ran twice or never"


def test_completion_racing_with_await_resumes_every_awaiter_exactly_once() -> None:
    """Sources are completed at the very moment coroutines suspend on them."""
    sources_per_round = THREADS * 6
    awaiters_per_source = 3
    end = _budget()
    while time.monotonic() < end:
        sources: list[TaskCompletionSource[int]] = [
            TaskCompletionSource() for _ in range(sources_per_round)
        ]
        resumed: list[list[int]] = [
            [] for _ in range(sources_per_round * awaiters_per_source)
        ]

        async def awaiter(slot: int, task: Task[int]) -> int:
            value = await task
            resumed[slot].append(value)
            return value

        tasks = [
            Task.run(awaiter, index * awaiters_per_source + a, sources[index].task)
            for index in range(sources_per_round)
            for a in range(awaiters_per_source)
        ]

        def completer(thread: int) -> None:
            for index in range(thread, sources_per_round, THREADS):
                if index % 3 == 0:
                    Task.run(sources[index].set_result, index)  # from a worker
                else:
                    sources[index].set_result(index)  # from this foreign thread

        _in_threads(THREADS, completer)
        _wait(tasks, "awaiters of concurrently completed sources")
        for slot, task in enumerate(tasks):
            index = slot // awaiters_per_source
            assert task.result() == index
            assert resumed[slot] == [index], "an awaiter resumed twice or with a wrong value"


def test_exactly_one_completion_wins_and_everyone_sees_the_same_outcome() -> None:
    batch = 64
    end = _budget()
    while time.monotonic() < end:
        sources: list[TaskCompletionSource[int]] = [TaskCompletionSource() for _ in range(batch)]
        winners: list[list[int]] = [[] for _ in range(batch)]

        async def observe(task: Task[int]) -> tuple[str, Any]:
            try:
                return "result", await task
            except OperationCanceledError:
                return "cancelled", None
            except ValueError as error:
                return "error", str(error)

        observers = [
            [Task.run(observe, source.task) for _ in range(2)] for source in sources
        ]

        def racer(thread: int) -> None:
            for index, source in enumerate(sources):
                kind = (thread + index) % 3
                if kind == 0:
                    won = source.try_set_result(thread)
                elif kind == 1:
                    won = source.try_set_exception(ValueError(str(thread)))
                else:
                    won = source.try_set_canceled()
                if won:
                    winners[index].append(thread)

        _in_threads(THREADS, racer)
        _wait([task for pair in observers for task in pair], "observers of raced sources")
        for index, source in enumerate(sources):
            assert len(winners[index]) == 1, "zero or several completions reported success"
            thread = winners[index][0]
            kind = (thread + index) % 3
            expected = (
                ("result", thread) if kind == 0
                else ("error", str(thread)) if kind == 1
                else ("cancelled", None)
            )
            assert source.task.status == (
                Task.SUCCEEDED if kind == 0 else Task.FAILED if kind == 1 else Task.CANCELLED
            )
            for observer in observers[index]:
                assert observer.result() == expected
            late: Task[tuple[str, Any]] = Task.run(observe, source.task)
            _wait([late], "late observer")
            assert late.result() == expected


def test_coroutine_is_resumed_by_one_worker_at_a_time_and_keeps_its_context() -> None:
    """Many coroutines hop between workers through every kind of await.

    A coroutine resumed by two workers at once fails with "coroutine already
    executing"; a continuation run in the wrong context sees another task's
    AsyncLocal value.
    """
    local: AsyncLocal[int] = AsyncLocal()
    tasks_per_round = WORKERS * 4
    iterations = 60
    hops: set[int] = set()
    end = _budget()

    async def traveller(ident: int) -> int:
        local.value = ident
        for step in range(iterations):
            kind = (ident + step) % 6
            if kind == 0:
                await Task.yield_now()
            elif kind == 1:
                # Completed by another worker while this coroutine suspends.
                source: TaskCompletionSource[int] = TaskCompletionSource()
                Task.run(source.set_result, step)
                assert await source.task == step
            elif kind == 2:
                assert await Task.run(_sync_echo, step) == step
            elif kind == 3:
                assert await Task.run(_async_echo, step) == step
            elif kind == 4:
                await Task.delay(0.0003 if step % 20 == 4 else 0)
            else:
                assert await Task.when_all(
                    Task.run(_sync_echo, step), Task.run(_async_echo, ident)
                ) == [step, ident]
            assert local.value == ident, "resumed in another task's context"
            hops.add(threading.get_ident())
        return ident

    while time.monotonic() < end:
        tasks = [Task.run(traveller, ident) for ident in range(tasks_per_round)]
        _wait(tasks, "travelling coroutines")
        assert [task.result() for task in tasks] == list(range(tasks_per_round))
    assert len(hops) > 1, "coroutines never ran on more than one worker"


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def test_when_all_when_any_and_collect_under_concurrent_completion() -> None:
    count = 48
    rng = random.Random(SEED)
    end = _budget()

    async def consume(tasks: list[Task[int]]) -> list[Task[int]]:
        seen = []
        async for finished in Task.collect(tasks):
            assert finished.done()
            seen.append(finished)
        return seen

    while time.monotonic() < end:
        sources: list[TaskCompletionSource[int]] = [TaskCompletionSource() for _ in range(count)]
        tasks = [source.task for source in sources]
        failing = rng.randrange(count) if rng.random() < 0.3 else None
        order = list(range(count))
        rng.shuffle(order)

        everything = Task.when_all(tasks)
        awaited_everything = Task.run(_await, Task.when_all(tasks))
        first = Task.when_any(tasks)
        collected = Task.run(consume, tasks)

        def completer(thread: int) -> None:
            for position in range(thread, count, THREADS):
                index = order[position]
                if index == failing:
                    sources[index].set_exception(KeyError(index))
                else:
                    sources[index].set_result(index)

        _in_threads(THREADS, completer)
        _wait([everything, awaited_everything, first, collected], "aggregates")

        if failing is None:
            assert everything.result() == list(range(count))
            assert awaited_everything.result() == list(range(count))
        else:
            for aggregate in (everything, awaited_everything):
                with pytest.raises(KeyError):
                    aggregate.result()
        winner = first.result()
        assert winner.done() and any(winner is task for task in tasks)
        seen = collected.result()
        assert len(seen) == count
        assert {id(task) for task in seen} == {id(task) for task in tasks}


# ---------------------------------------------------------------------------
# Cancellation and timers
# ---------------------------------------------------------------------------

def test_cancellation_racing_with_timer_completion_never_strands_an_awaiter() -> None:
    count = THREADS * 8
    step = 0.0004
    end = _budget()
    rng = random.Random(SEED)

    async def observe(delay: Task[None]) -> str:
        try:
            await delay
        except OperationCanceledError:
            return "cancelled"
        return "elapsed"

    outcomes = {"cancelled": 0, "elapsed": 0}
    while time.monotonic() < end:
        sources = [CancellationTokenSource() for _ in range(count)]
        # Delay ``index`` elapses about when its thread gets round to
        # cancelling it, so both orders happen.
        delays = [
            Task.delay(step * (index // THREADS + 1) * rng.uniform(0.6, 1.4), token=source.token)
            for index, source in enumerate(sources)
        ]
        observers = [Task.run(observe, delay) for delay in delays]

        def canceller(thread: int) -> None:
            for index in range(thread, count, THREADS):
                time.sleep(step)
                sources[index].cancel()

        _in_threads(THREADS, canceller)
        _wait(observers + delays, "delays raced against cancellation")
        for delay, observer in zip(delays, observers):
            outcome = observer.result()
            assert (outcome == "cancelled") == delay.cancelled()
            outcomes[outcome] += 1
        for source in sources:
            source.dispose()
    assert sum(outcomes.values()) > 0


def test_token_callbacks_run_exactly_once_while_registering_and_cancelling() -> None:
    per_thread = 40
    end = _budget()
    while time.monotonic() < end:
        source = CancellationTokenSource()
        token = source.token
        ran: list[list[int]] = [[] for _ in range(THREADS * per_thread)]
        kept = [False] * (THREADS * per_thread)

        def worker(thread: int) -> None:
            for k in range(per_thread):
                slot = thread * per_thread + k
                registration = token.register(lambda slot=slot: ran[slot].append(1))
                if k % 3 == 0:
                    registration.dispose()
                else:
                    kept[slot] = True
                if thread == 0 and k == per_thread // 2:
                    source.cancel()

        _in_threads(THREADS, worker)
        assert source.is_cancellation_requested
        for slot, calls in enumerate(ran):
            assert len(calls) <= 1, "a cancellation callback ran twice"
            if kept[slot]:
                assert len(calls) == 1, "a registered cancellation callback never ran"
        source.dispose()


def test_timers_from_many_threads_fire_once_and_never_early() -> None:
    end = _budget()
    fired = [0] * THREADS
    disposed: list[list[CancellationTokenSource]] = [[] for _ in range(THREADS)]

    def worker(thread: int) -> None:
        rng = random.Random(SEED + thread)
        while time.monotonic() < end:
            requested = [rng.uniform(0, 0.004) for _ in range(rng.randrange(1, 8))]
            started = time.monotonic()
            delays = [Task.delay(seconds) for seconds in requested]
            # Disposed long before its timer is due: must simply never fire.
            abandoned = CancellationTokenSource()
            abandoned.cancel_after(0.5)
            abandoned.dispose()
            disposed[thread].append(abandoned)
            sources = [CancellationTokenSource() for _ in range(2)]
            for source in sources:
                source.cancel_after(rng.uniform(0, 0.003))
            for seconds, delay in zip(requested, delays):
                _wait([delay], f"delay of {seconds:.4f}s")
                assert time.monotonic() - started >= seconds, "a delay completed early"
                assert delay.result() is None
            deadline = time.monotonic() + HANG_TIMEOUT
            for source in sources:
                while not source.is_cancellation_requested:
                    if time.monotonic() > deadline:
                        pytest.fail("cancel_after() never fired")
                    time.sleep(0.0002)
                source.dispose()
            fired[thread] += len(requested)

    _in_threads(THREADS, worker)
    assert all(fired)
    time.sleep(0.7)  # past the due time of every abandoned timer
    assert not any(
        source.is_cancellation_requested for sources in disposed for source in sources
    ), "the timer of a disposed CancellationTokenSource still fired"
    timers = [t for t in threading.enumerate() if t.name == "Task-timer"]
    assert len(timers) == 1, f"expected one timer thread, found {len(timers)}"


# ---------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------

def test_socket_waits_wake_every_reader_for_every_message() -> None:
    pairs_count = WORKERS * 2
    messages = 150
    end = _budget()

    async def reader(sock: socket.socket) -> int:
        received = 0
        while received < messages:
            await IO.wait_readable(sock)
            try:
                received += len(sock.recv(4096))
            except BlockingIOError:
                continue
        return received

    rounds = 0
    while rounds == 0 or time.monotonic() < end:
        rounds += 1
        pairs = [socket.socketpair() for _ in range(pairs_count)]
        try:
            for reading, _ in pairs:
                reading.setblocking(False)
            readers = [Task.run(reader, reading) for reading, _ in pairs]

            def writer(thread: int) -> None:
                rng = random.Random(SEED + thread)
                mine = [writing for _, writing in pairs[thread::THREADS]]
                for _ in range(messages):
                    for writing in mine:
                        writing.send(b"x")
                    if rng.random() < 0.3:
                        _pause(rng)

            _in_threads(THREADS, writer)
            _wait(readers, "socket readers")
            assert [task.result() for task in readers] == [messages] * pairs_count
        finally:
            for reading, writing in pairs:
                reading.close()
                writing.close()


def test_socket_readiness_racing_with_cancellation_resumes_the_waiter_once() -> None:
    """Readiness and cancellation both try to resume the same parked waiter.

    Exactly one may win. If both did, the second resumption would arrive
    while the coroutine is suspended on its next await and hand it a wrong
    value.
    """
    count = THREADS * 4
    end = _budget()
    outcomes = {"ready": 0, "cancelled": 0}
    while time.monotonic() < end:
        pairs = [socket.socketpair() for _ in range(count)]
        sources = [CancellationTokenSource() for _ in range(count)]
        gates: list[TaskCompletionSource[int]] = [TaskCompletionSource() for _ in range(count)]
        try:
            for reading, _ in pairs:
                reading.setblocking(False)

            async def waiter(index: int) -> tuple[str, int]:
                try:
                    await IO.wait_readable(pairs[index][0], token=sources[index].token)
                    outcome = "ready"
                except OperationCanceledError:
                    outcome = "cancelled"
                return outcome, await gates[index].task

            tasks = [Task.run(waiter, index) for index in range(count)]

            def racer(thread: int) -> None:
                # One thread makes socket ``index`` readable while its
                # neighbour cancels the same wait.
                for index in range(count):
                    if index % THREADS == thread:
                        pairs[index][1].send(b"x")
                    if (index + 1) % THREADS == thread:
                        sources[index].cancel()

            _in_threads(THREADS, racer)
            time.sleep(0.002)
            for index, gate in enumerate(gates):
                gate.set_result(index)
            _wait(tasks, "socket waits raced against cancellation")
            for index, task in enumerate(tasks):
                outcome, value = task.result()
                assert value == index, "a waiter was resumed a second time"
                outcomes[outcome] += 1
        finally:
            for source in sources:
                source.dispose()
            for reading, writing in pairs:
                reading.close()
                writing.close()
    assert sum(outcomes.values()) > 0


# ---------------------------------------------------------------------------
# Pool growth, bookkeeping and shutdown
# ---------------------------------------------------------------------------

def test_workers_blocked_on_started_tasks_are_compensated(errors) -> None:
    """Sync-over-async on a small pool: it must grow instead of deadlocking."""
    _install(errors, min_workers=2, max_workers=64)

    async def child(value: int) -> int:
        await Task.delay(0.003)  # suspends: cannot be finished inline
        return value

    async def parent(value: int) -> int:
        return Task.run(child, value).result() + Task.run(_sync_echo, 1).result()

    parents = [Task.run(parent, value) for value in range(24)]
    _wait(parents, "parents blocked on suspended children")
    assert [task.result() for task in parents] == [value + 1 for value in range(24)]


def test_pool_bookkeeping_is_consistent_once_idle() -> None:
    """After heavy traffic the pool's counters must describe reality again.

    Drifting counters are how a later wake-up gets lost: a pool that believes
    somebody is still looking for work stops waking sleepers.
    """
    end = _budget()

    def submitter(index: int) -> None:
        rng = random.Random(SEED + index)
        while time.monotonic() < end:
            burst = [_one_unit_of_work(rng) for _ in range(rng.randrange(1, 20))]
            _wait(burst, f"load from submitter {index}")
            if rng.random() < 0.2:
                _pause(rng)

    _in_threads(THREADS, submitter)

    pool = task_module._get_runtime()._pool
    needed = ("_count", "_searching", "_blocked", "_parked", "_items", "_lock")
    if not all(hasattr(pool, name) for name in needed):
        pytest.skip("pool internals changed; update this consistency check")
    deadline = time.monotonic() + 10
    while True:
        with pool._lock:
            state = (pool._count, pool._searching, pool._blocked, len(pool._parked), len(pool._items))
        count, searching, blocked, parked, queued = state
        alive = len(_worker_threads())
        if searching == 0 and blocked == 0 and queued == 0 and parked == count == alive:
            break
        if time.monotonic() > deadline:
            pytest.fail(
                "idle pool is inconsistent: "
                f"workers={count} alive_threads={alive} searching={searching} "
                f"blocked={blocked} parked={parked} queued={queued}"
            )
        time.sleep(0.01)
    # And it still works afterwards.
    probe = Task.run(_sync_echo, "alive")
    _wait([probe], "probe after idle check")
    assert probe.result() == "alive"


def test_shutdown_under_load_leaves_no_task_pending(errors) -> None:
    rng = random.Random(SEED)
    end = _budget()
    cycles = 0
    while cycles == 0 or time.monotonic() < end:
        cycles += 1
        _install(errors, min_workers=4, max_workers=WORKERS)
        tracked: list[Task[Any]] = []
        lock = threading.Lock()

        def track(task: Task[Any]) -> Task[Any]:
            with lock:
                tracked.append(task)
            return task

        never = [TaskCompletionSource() for _ in range(8)]
        for source in never:
            track(source.task)

        async def leaf(index: int) -> int:
            kind = index % 5
            if kind == 0:
                for _ in range(5):
                    await Task.yield_now()
            elif kind == 1:
                await Task.delay(random.random() * 0.02)
            elif kind == 2:
                await never[index % len(never)].task
            elif kind == 3:
                await Task.run(time.sleep, 0.001)
            return index

        async def spawner() -> str:
            try:
                while True:
                    batch = [track(Task.run(leaf, index)) for index in range(20)]
                    track(Task.when_all(batch))
                    track(Task.when_any(batch))
                    await Task.delay(0.001)
            except RuntimeShutdownError:
                return "rejected"

        for _ in range(3):
            track(Task.run(spawner))
        stop = threading.Event()

        def external() -> None:
            while not stop.is_set():
                try:
                    track(Task.run(time.sleep, 0.0005))
                except RuntimeShutdownError:
                    return
                time.sleep(0.0005)

        threads = [threading.Thread(target=external, daemon=True) for _ in range(4)]
        for thread in threads:
            thread.start()
        time.sleep(rng.uniform(0.005, 0.05))
        report = Task.shutdown(grace_timeout=rng.choice([0.0, 0.01, 0.2]), worker_timeout=10.0)
        stop.set()
        for thread in threads:
            thread.join(HANG_TIMEOUT)
            assert not thread.is_alive(), "a submitting thread is stuck after shutdown"
        assert report.workers_still_running == 0 and not report.timed_out, report
        with lock:
            snapshot = list(tracked)
        # Work submitted after the shutdown finished runs on a fresh runtime
        # and completes normally; everything else must already be terminal.
        _wait(snapshot, f"tasks after shutdown (cycle {cycles})", timeout=20)
        for source in never:
            assert source.task.cancelled()
