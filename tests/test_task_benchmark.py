"""Informational performance comparisons: flpit.task.Task vs asyncio.

Run explicitly, because timings are diagnostic and intentionally have no
pass/fail thresholds:

    pytest -s -v tests/test_task_performance.py

These are steady-state micro benchmarks, not claims about production throughput.
Adjust the constants below for longer runs on target hardware.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, Awaitable, Callable

import pytest

from flpit.task import Task


# Deliberately modest defaults so the suite remains quick to run locally.
REPEATS = int(os.environ.get("FLPIT_BENCH_REPEATS", "4"))
TASK_COUNT = int(os.environ.get("FLPIT_BENCH_TASKS", "250"))
YIELD_TASK_COUNT = int(os.environ.get("FLPIT_BENCH_YIELD_TASKS", "100"))
YIELDS_PER_TASK = int(os.environ.get("FLPIT_BENCH_YIELDS_PER_TASK", "5"))
TIMER_TASK_COUNT = int(os.environ.get("FLPIT_BENCH_TIMER_TASKS", "80"))
TIMER_DELAY_SECONDS = float(os.environ.get("FLPIT_BENCH_TIMER_DELAY", "0.005"))
AGGREGATION_TASK_COUNT = int(os.environ.get("FLPIT_BENCH_AGGREGATION_TASKS", "200"))
BACKGROUND_TASK_COUNT = int(os.environ.get("FLPIT_BENCH_BACKGROUND_TASKS", "64"))
BACKGROUND_SLEEP_SECONDS = float(os.environ.get("FLPIT_BENCH_BACKGROUND_SLEEP", "0.002"))
WORKER_COUNT = int(os.environ.get("FLPIT_BENCH_WORKERS", "8"))
MAX_PENDING_BACKGROUND = max(512, BACKGROUND_TASK_COUNT * 2)
WAIT_TIMEOUT_SECONDS = 30.0


@pytest.fixture(scope="module", autouse=True)
def _configure_task_runtime():
    """Give the Task side enough bounded capacity for these comparisons."""
    Task.shutdown(grace_timeout=1.0, worker_timeout=2.0)
    Task.configure(
        max_workers=WORKER_COUNT,
        max_pending_background=MAX_PENDING_BACKGROUND,
    )
    yield
    Task.shutdown(grace_timeout=1.0, worker_timeout=2.0)


async def _task_noop(value: int = 1) -> int:
    return value


async def _asyncio_noop(value: int = 1) -> int:
    return value


def _measure_task(
        operation: Callable[[], Any], repeats: int = REPEATS
) -> tuple[list[float], Any]:
    """Warm up once, then measure repeated Task-runtime operations."""
    operation()
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = operation()
        samples.append(perf_counter() - started)
    return samples, result


def _measure_asyncio(
        operation: Callable[[], Awaitable[Any]],
        repeats: int = REPEATS,
        *,
        max_workers: int | None = None,
) -> tuple[list[float], Any]:
    """Warm up and measure on one reused event loop (startup excluded)."""
    async def runner() -> tuple[list[float], Any]:
        if max_workers is not None:
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=max_workers))

        await operation()
        samples: list[float] = []
        result: Any = None
        for _ in range(repeats):
            started = perf_counter()
            result = await operation()
            samples.append(perf_counter() - started)
        return samples, result

    return asyncio.run(runner())


def _median(samples: list[float]) -> float:
    return statistics.median(samples)


def _report(
        label: str,
        task_samples: list[float],
        asyncio_samples: list[float],
        *,
        operations_per_run: int,
) -> None:
    task_median = _median(task_samples)
    asyncio_median = _median(asyncio_samples)
    ratio = asyncio_median / task_median if task_median else float("inf")
    task_rate = operations_per_run / task_median if task_median else float("inf")
    asyncio_rate = operations_per_run / asyncio_median if asyncio_median else float("inf")
    print(
        f"\n[PERF] {label}\n"
        f"  Task:    median={task_median * 1000:.3f} ms, "
        f"{task_rate:,.0f} operations/s\n"
        f"  asyncio: median={asyncio_median * 1000:.3f} ms, "
        f"{asyncio_rate:,.0f} operations/s\n"
        f"  relative: asyncio/Task time={ratio:.2f}x "
        f"(above 1.0 means Task took less time)"
    )


def _pctl_ms(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index] * 1000


@pytest.mark.benchmark
class TestTaskCreationAndCompletion:
    """Cost of creating, scheduling and completing trivial coroutine tasks."""

    def test_create_and_complete_trivial_tasks(self):
        def task_operation():
            tasks = [Task.run(_task_noop, i) for i in range(TASK_COUNT)]
            return Task.when_all(tasks).result(WAIT_TIMEOUT_SECONDS)

        async def asyncio_operation():
            tasks = [asyncio.create_task(_asyncio_noop(i)) for i in range(TASK_COUNT)]
            return await asyncio.gather(*tasks)

        task_samples, task_result = _measure_task(task_operation)
        asyncio_samples, asyncio_result = _measure_asyncio(asyncio_operation)

        expected = list(range(TASK_COUNT))
        assert task_result == expected
        assert asyncio_result == expected
        _report(
            f"create + complete {TASK_COUNT} trivial tasks",
            task_samples,
            asyncio_samples,
            operations_per_run=TASK_COUNT,
        )


@pytest.mark.benchmark
class TestSchedulingThroughput:
    """Scheduler throughput for tasks that cooperatively yield repeatedly."""

    def test_cooperative_yield_throughput(self):
        async def task_yield_job(value: int) -> int:
            for _ in range(YIELDS_PER_TASK):
                await Task.yield_now()
            return value

        async def asyncio_yield_job(value: int) -> int:
            for _ in range(YIELDS_PER_TASK):
                await asyncio.sleep(0)
            return value

        def task_operation():
            tasks = [Task.run(task_yield_job, i) for i in range(YIELD_TASK_COUNT)]
            return Task.when_all(tasks).result(WAIT_TIMEOUT_SECONDS)

        async def asyncio_operation():
            tasks = [
                asyncio.create_task(asyncio_yield_job(i))
                for i in range(YIELD_TASK_COUNT)
            ]
            return await asyncio.gather(*tasks)

        task_samples, task_result = _measure_task(task_operation)
        asyncio_samples, asyncio_result = _measure_asyncio(asyncio_operation)

        expected = list(range(YIELD_TASK_COUNT))
        assert task_result == expected
        assert asyncio_result == expected
        _report(
            f"{YIELD_TASK_COUNT} tasks x {YIELDS_PER_TASK} cooperative yields",
            task_samples,
            asyncio_samples,
            operations_per_run=YIELD_TASK_COUNT * YIELDS_PER_TASK,
        )


@pytest.mark.benchmark
class TestTimerHandling:
    """Concurrent timer completion and wake-up lateness."""

    def test_concurrent_delay_wakeups(self):
        async def task_timer_job() -> float:
            started = perf_counter()
            await Task.delay(TIMER_DELAY_SECONDS)
            return perf_counter() - started - TIMER_DELAY_SECONDS

        async def asyncio_timer_job() -> float:
            started = perf_counter()
            await asyncio.sleep(TIMER_DELAY_SECONDS)
            return perf_counter() - started - TIMER_DELAY_SECONDS

        def task_operation():
            tasks = [Task.run(task_timer_job) for _ in range(TIMER_TASK_COUNT)]
            return Task.when_all(tasks).result(WAIT_TIMEOUT_SECONDS)

        async def asyncio_operation():
            tasks = [asyncio.create_task(asyncio_timer_job()) for _ in range(TIMER_TASK_COUNT)]
            return await asyncio.gather(*tasks)

        task_samples, task_lateness = _measure_task(task_operation)
        asyncio_samples, asyncio_lateness = _measure_asyncio(asyncio_operation)

        assert len(task_lateness) == TIMER_TASK_COUNT
        assert len(asyncio_lateness) == TIMER_TASK_COUNT
        _report(
            f"{TIMER_TASK_COUNT} concurrent timers at {TIMER_DELAY_SECONDS * 1000:.1f} ms",
            task_samples,
            asyncio_samples,
            operations_per_run=TIMER_TASK_COUNT,
        )
        print(
            "  wake-up lateness (p50/p95): "
            f"Task={_pctl_ms(task_lateness, 0.50):.3f}/"
            f"{_pctl_ms(task_lateness, 0.95):.3f} ms; "
            f"asyncio={_pctl_ms(asyncio_lateness, 0.50):.3f}/"
            f"{_pctl_ms(asyncio_lateness, 0.95):.3f} ms"
        )


@pytest.mark.benchmark
class TestTaskAggregation:
    """Overhead of when_all/gather and when_any/FIRST_COMPLETED."""

    def test_when_all_against_gather_for_completed_children(self):
        task_children = [Task.run(_task_noop, i) for i in range(AGGREGATION_TASK_COUNT)]
        expected = Task.when_all(task_children).result(WAIT_TIMEOUT_SECONDS)

        def task_aggregate():
            return Task.when_all(task_children).result(WAIT_TIMEOUT_SECONDS)

        task_samples, task_result = _measure_task(task_aggregate)

        # Prepare children before timing so this measures aggregation overhead,
        # not child creation/completion cost.
        async def measure_completed_gather():
            children = [
                asyncio.create_task(_asyncio_noop(i))
                for i in range(AGGREGATION_TASK_COUNT)
            ]
            await asyncio.gather(*children)
            await asyncio.gather(*children)  # warm-up aggregation
            samples: list[float] = []
            result: Any = None
            for _ in range(REPEATS):
                started = perf_counter()
                result = await asyncio.gather(*children)
                samples.append(perf_counter() - started)
            return samples, result

        asyncio_samples, asyncio_result = asyncio.run(measure_completed_gather())
        assert task_result == expected
        assert asyncio_result == list(range(AGGREGATION_TASK_COUNT))
        _report(
            f"when_all/gather over {AGGREGATION_TASK_COUNT} completed children",
            task_samples,
            asyncio_samples,
            operations_per_run=1,
        )

    def test_when_any_against_wait_first_completed(self):
        task_children = [Task.run(_task_noop, i) for i in range(AGGREGATION_TASK_COUNT)]
        Task.when_all(task_children).result(WAIT_TIMEOUT_SECONDS)

        def task_aggregate():
            return Task.when_any(task_children).result(WAIT_TIMEOUT_SECONDS)

        task_samples, task_winner = _measure_task(task_aggregate)
        assert task_winner in task_children

        async def measure_completed_wait():
            children = [
                asyncio.create_task(_asyncio_noop(i))
                for i in range(AGGREGATION_TASK_COUNT)
            ]
            await asyncio.gather(*children)
            await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)  # warm-up
            samples: list[float] = []
            result: Any = None
            for _ in range(REPEATS):
                started = perf_counter()
                result = await asyncio.wait(
                    children, return_when=asyncio.FIRST_COMPLETED
                )
                samples.append(perf_counter() - started)
            return samples, result

        asyncio_samples, asyncio_result = asyncio.run(measure_completed_wait())
        done, pending = asyncio_result
        assert done
        assert not pending
        _report(
            f"when_any/wait(FIRST_COMPLETED) over {AGGREGATION_TASK_COUNT} completed children",
            task_samples,
            asyncio_samples,
            operations_per_run=1,
        )


@pytest.mark.benchmark
class TestBackgroundWork:
    """Dispatch overhead for synchronous blocking work on bounded thread pools."""

    @staticmethod
    def _blocking_work(value: int) -> int:
        time.sleep(BACKGROUND_SLEEP_SECONDS)
        return value

    def test_background_function_against_asyncio_to_thread(self):
        def task_operation():
            tasks = [
                Task.run(self._blocking_work, i)
                for i in range(BACKGROUND_TASK_COUNT)
            ]
            return Task.when_all(tasks).result(WAIT_TIMEOUT_SECONDS)

        async def asyncio_operation():
            return await asyncio.gather(
                *(
                    asyncio.to_thread(self._blocking_work, i)
                    for i in range(BACKGROUND_TASK_COUNT)
                )
            )

        task_samples, task_result = _measure_task(task_operation)
        asyncio_samples, asyncio_result = _measure_asyncio(
            asyncio_operation,
            max_workers=WORKER_COUNT,
        )

        expected = list(range(BACKGROUND_TASK_COUNT))
        assert task_result == expected
        assert asyncio_result == expected
        _report(
            f"{BACKGROUND_TASK_COUNT} blocking calls, {WORKER_COUNT} worker threads, "
            f"{BACKGROUND_SLEEP_SECONDS * 1000:.1f} ms each",
            task_samples,
            asyncio_samples,
            operations_per_run=BACKGROUND_TASK_COUNT,
        )
