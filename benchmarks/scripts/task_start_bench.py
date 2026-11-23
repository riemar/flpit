"""Microbenchmark: what it costs to start, resume and complete a Task.

Run directly (prints Markdown tables):

    python benchmarks/scripts/task_start_bench.py            # default sizes
    python benchmarks/scripts/task_start_bench.py --quick    # smoke run
    python benchmarks/scripts/task_start_bench.py --threads 1,2,4 --ops 20000

Three tables:

* **Per operation**, one submitting thread, in µs/op. Each case is run from an
  external (non-pool) thread and from a pool worker, the place where a web framework
  handles a request. "end-to-end" waits for every task before the clock stops.
* **Throughput** with several submitting threads (pool workers), in ops/s.
* **Cost split** of the building blocks a ``Task.run`` pays for, in ns/op, measured
  first, from the main thread.

Timings are the best of ``--repeats`` runs. They are diagnostic: there are no
pass/fail thresholds. On a GIL build only one thread runs Python code at a time, so
multi-thread throughput measures contention, not parallelism.
"""
from __future__ import annotations

import argparse
import contextvars
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from flpit.task import Task, TaskCompletionSource, _get_runtime

_start_inline = getattr(Task, "run_inline", None)
try:
    from flpit.threading import ThreadPool
    _queue_work_item = ThreadPool.queue
except ImportError:  # flpit before ThreadPool
    _queue_work_item = None


# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------

def sync_noop() -> int:
    return 1


async def async_noop() -> int:
    return 1


async def async_one_yield() -> int:
    await Task.yield_now()
    return 1


async def async_await_completed(done: Task[Any], n: int) -> int:
    total = 0
    for _ in range(n):
        total += await done
    return total


def from_result_tcs() -> Task[int]:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_result(1)
    return source.task


def from_result_api() -> Task[int]:
    return Task.from_result(1)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _best(repeats: int, body: Callable[[], float]) -> float:
    return min(body() for _ in range(repeats))


def _on_pool(function: Callable[[], float]) -> float:
    """Run ``function`` as a synchronous task on a pool worker and return its value."""
    return Task.run(function).result()


def _per_op_submit(start: Callable[[], Task[Any]], n: int, *, on_pool: bool) -> tuple[float, float]:
    """(µs/op to submit, µs/op end-to-end) for ``n`` independent tasks."""

    def body() -> tuple[float, float]:
        tasks: list[Task[Any]] = [None] * n  # type: ignore[list-item]
        t0 = time.perf_counter()
        for i in range(n):
            tasks[i] = start()
        t1 = time.perf_counter()
        for task in tasks:
            task.wait()
        t2 = time.perf_counter()
        return (t1 - t0) / n * 1e6, (t2 - t0) / n * 1e6

    if on_pool:
        return Task.run(body).result()
    return body()


def _per_op_latency(start: Callable[[], Task[Any]], n: int) -> float:
    """µs per sequential ``start().wait()`` from an external thread: includes the wake-up."""
    t0 = time.perf_counter()
    for _ in range(n):
        start().wait()
    return (time.perf_counter() - t0) / n * 1e6


def _await_completed(n: int) -> float:
    """µs per ``await`` of a task that has already completed, inside one coroutine."""
    finished = Task.run(async_noop)
    finished.wait()
    t0 = time.perf_counter()
    Task.run(async_await_completed, finished, n).result()
    return (time.perf_counter() - t0) / n * 1e6


def _throughput(start: Callable[[], Task[Any]], threads: int, n: int) -> float:
    """Total ops/s with ``threads`` pool workers each submitting ``n // threads`` tasks.

    Each submitter takes its own timestamps, so the measured span runs from the first
    submission to the last completion, whichever threads they happen on.
    """
    per_thread = max(1, n // threads)
    barrier = threading.Barrier(threads)

    def submitter() -> tuple[float, float]:
        tasks = []
        barrier.wait()
        t0 = time.perf_counter()
        for _ in range(per_thread):
            tasks.append(start())
        for task in tasks:
            task.wait()
        return t0, time.perf_counter()

    spans = [driver.result() for driver in [Task.run(submitter) for _ in range(threads)]]
    elapsed = max(end for _, end in spans) - min(begin for begin, _ in spans)
    return per_thread * threads / elapsed


def _ns(n: int, body: Callable[[], None]) -> float:
    t0 = time.perf_counter()
    body()
    return (time.perf_counter() - t0) / n * 1e9


def _cost_split(n: int) -> list[tuple[str, float]]:
    runtime = _get_runtime()
    pool = runtime._pool
    rows: list[tuple[str, float]] = []

    def loop(fn: Callable[[], Any]) -> Callable[[], None]:
        def body() -> None:
            for _ in range(n):
                fn()
        return body

    rows.append(("plain function call", _ns(n, loop(sync_noop))))

    def coro_to_completion() -> None:
        for _ in range(n):
            try:
                async_noop().send(None)
            except StopIteration:
                pass

    rows.append(("coroutine create + send to completion", _ns(n, coro_to_completion)))
    rows.append(("threading.Lock()", _ns(n, loop(threading.Lock))))
    rows.append(("contextvars.copy_context()", _ns(n, loop(contextvars.copy_context))))
    ctx = contextvars.copy_context()
    rows.append(("Context.run(noop)", _ns(n, loop(lambda: ctx.run(sync_noop)))))
    rows.append(("Task.__init__ (allocation incl. lock + context copy)", _ns(n, loop(lambda: Task(runtime)))))

    tasks = [Task(runtime, capture_context=False) for _ in range(n)]

    def track() -> None:
        for task in tasks:
            runtime._tasks.add(task)
        for task in tasks:
            runtime._tasks.discard(task)

    rows.append(("registry add + discard (WeakSet)", _ns(n, track)))

    lock = threading.Lock()

    def lock_cycle() -> None:
        for _ in range(n):
            with lock:
                pass

    rows.append(("one uncontended lock acquire/release", _ns(n, lock_cycle)))

    items: deque[Any] = deque()

    def append_pop() -> None:
        for _ in range(n):
            items.append(sync_noop)
            items.popleft()

    rows.append(("deque append + popleft (the queue itself)", _ns(n, append_pop)))

    def finish() -> None:
        for task in tasks:
            runtime._tasks.add(task)
            task._finish(Task.SUCCEEDED, 1)

    rows.append(("Task._finish (no continuations, incl. registry discard)", _ns(n, finish)))

    def start_sync() -> None:
        for _ in range(n):
            task = Task(runtime)
            task._work = (sync_noop, (), {})
            runtime._tasks.add(task)
            task._start()

    rows.append(("Task.__init__ + _start of sync fn, inline (no queue)", _ns(n, start_sync)))

    def start_async() -> None:
        for _ in range(n):
            task = Task(runtime)
            task._work = (async_noop, (), {})
            runtime._tasks.add(task)
            task._start()

    rows.append(("Task.__init__ + _start/_drive of async fn, inline (no queue)", _ns(n, start_async)))

    # Wake-up: a parked worker picking up one item, measured as a ping round trip
    # from an external thread. Sleep first so the workers park.
    pings = max(50, n // 100)
    event = threading.Event()
    total = 0.0
    for _ in range(pings):
        time.sleep(0.002)
        event.clear()
        t0 = time.perf_counter()
        pool.queue(event.set)
        event.wait()
        total += time.perf_counter() - t0
    rows.append(("queue -> parked worker runs item (wake-up round trip)", total / pings * 1e9))

    total = 0.0
    for _ in range(pings):
        event.clear()
        t0 = time.perf_counter()
        pool.queue(event.set)
        event.wait()
        total += time.perf_counter() - t0
    rows.append(("queue -> worker runs item, back to back (often still spinning)", total / pings * 1e9))
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ops", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--threads", default="1,2,4")
    parser.add_argument("--quick", action="store_true", help="small sizes, for a smoke run")
    args = parser.parse_args(argv)
    n = 500 if args.quick else args.ops
    repeats = 1 if args.quick else args.repeats
    threads = [int(x) for x in args.threads.split(",") if x]

    # First, before the other runs leave workers spinning or parked mid-way: on a
    # free-threaded build they disturb these single-thread figures.
    split = _cost_split(n)

    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]} ({'GIL' if gil else 'free-threaded, GIL disabled'}), "
          f"{threading.active_count()} threads at start, ops={n}, best of {repeats}")
    _per_op_submit(lambda: Task.run(sync_noop), 200, on_pool=True)  # warm the pool

    cases: list[tuple[str, Callable[[], Task[Any]]]] = [
        ("Task.run(sync fn)", lambda: Task.run(sync_noop)),
        ("Task.run(async fn returning at once)", lambda: Task.run(async_noop)),
        ("Task.run(async fn with one yield_now)", lambda: Task.run(async_one_yield)),
    ]
    if _start_inline is not None:
        cases += [
            ("Task.run_inline(async fn returning at once)", lambda: _start_inline(async_noop)),
            ("Task.run_inline(coroutine object, returning at once)", lambda: _start_inline(async_noop())),
            ("Task.run_inline(async fn with one yield_now)", lambda: _start_inline(async_one_yield)),
        ]
    from_result = ("Task.from_result(1)", from_result_api) if hasattr(Task, "from_result") else (
        "TaskCompletionSource + set_result (no Task.from_result)", from_result_tcs)
    cases.append(from_result)

    print()
    print("| case | submit, ext thread µs/op | end-to-end, ext thread µs/op | submit, on pool µs/op "
          "| end-to-end, on pool µs/op | sequential start+wait, ext µs/op |")
    print("|---|---:|---:|---:|---:|---:|")
    for label, start in cases:
        ext = min((_per_op_submit(start, n, on_pool=False) for _ in range(repeats)), key=lambda r: r[1])
        pool = min((_per_op_submit(start, n, on_pool=True) for _ in range(repeats)), key=lambda r: r[1])
        latency = _best(repeats, lambda: _per_op_latency(start, max(100, n // 10)))
        print(f"| {label} | {ext[0]:.2f} | {ext[1]:.2f} | {pool[0]:.2f} | {pool[1]:.2f} | {latency:.2f} |")
    awaited = _best(repeats, lambda: _await_completed(n))
    print(f"| `await` an already completed task (inside one coroutine) | | | {awaited:.3f} | {awaited:.3f} | |")
    if _queue_work_item is not None:
        def work_items() -> float:
            remaining = [n]
            done = threading.Event()
            lock = threading.Lock()

            def item() -> None:
                with lock:
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        done.set()

            t0 = time.perf_counter()
            for _ in range(n):
                _queue_work_item(item)
            done.wait()
            return (time.perf_counter() - t0) / n * 1e6

        print(f"| ThreadPool.queue(fn), end-to-end | | {_best(repeats, work_items):.2f} | | | |")

    print()
    header = " | ".join(f"{t} submitter{'s' if t > 1 else ''} ops/s" for t in threads)
    print(f"| case (submitters are pool workers) | {header} |")
    print("|---|" + "---:|" * len(threads))
    for label, start in cases:
        values = [_best(repeats, lambda t=t: -_throughput(start, t, n)) for t in threads]
        print(f"| {label} | " + " | ".join(f"{-v:,.0f}" for v in values) + " |")

    print()
    print("| building block | ns/op |")
    print("|---|---:|")
    for label, value in split:
        print(f"| {label} | {value:,.0f} |")


if __name__ == "__main__":
    main()
