"""What ``Task.asyncio_interop`` costs a flpit await, and what an await from asyncio costs.

With interop enabled, every await of a pending Task first asks whether an asyncio loop runs on
this thread. Asked with ``asyncio.get_running_loop()`` that raises and catches an exception on a
flpit worker; asked with asyncio's ``_get_running_loop()`` it is one C call returning None.

    python benchmarks/scripts/asyncio_interop_bench.py [--rounds 20000] [--repeats 3]

"await setup" times one pending await up to its yield (the part interop changes), without the
queueing and wake-ups around it; on a busy machine the end-to-end figure varies by microseconds
between runs, far more than the check costs.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
import timeit

from flpit.task import Task, TaskCompletionSource
from flpit.threading import ThreadPool


def pending_awaits(rounds: int) -> float:
    """µs per await of a pending task by a flpit coroutine on a pool worker."""

    async def body() -> None:
        for _ in range(rounds):
            source: TaskCompletionSource[int] = TaskCompletionSource()
            ThreadPool.queue(lambda s: s.set_result(1), source)
            await source.task

    start = time.perf_counter()
    Task.run(body).result()
    return (time.perf_counter() - start) / rounds * 1e6


def asyncio_round_trips(rounds: int) -> float:
    """µs per ``await Task.run(...)`` from a coroutine on an asyncio loop thread."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def body() -> None:
        for _ in range(rounds):
            await Task.run(lambda: None)

    start = time.perf_counter()
    asyncio.run_coroutine_threadsafe(body(), loop).result()
    elapsed = (time.perf_counter() - start) / rounds * 1e6
    loop.call_soon_threadsafe(loop.stop)
    return elapsed


def await_setup(enabled: bool) -> float:
    """ns for one pending await of a Task up to its yield: the path interop changes."""
    source: TaskCompletionSource[int] = TaskCompletionSource()
    pending = source.task
    implementation = Task._await_asyncio_interop if enabled else Task._await_pure_flpit_task

    def step() -> None:
        awaiting = implementation(pending)
        next(awaiting)
        awaiting.close()

    n = 200_000
    return min(timeit.repeat(step, number=n, repeat=7)) / n * 1e9


def check_costs() -> tuple[float, float]:
    def raising() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass

    n = 200_000
    get = asyncio.events._get_running_loop
    return (min(timeit.repeat(raising, number=n, repeat=5)) / n * 1e9,
            min(timeit.repeat(get, number=n, repeat=5)) / n * 1e9)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=20000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]} ({'GIL' if gil else 'free-threaded'}), best of {args.repeats}")
    print()
    raising, c_call = check_costs()
    print("| case | cost |")
    print("|---|---:|")
    print(f"| is a loop running? `asyncio.get_running_loop()` + `except` on a flpit worker | {raising:.0f} ns |")
    print(f"| is a loop running? asyncio's `_get_running_loop()` | {c_call:.0f} ns |")
    for enabled in (False, True):
        print(f"| pending await setup, interop {'on' if enabled else 'off'} | {await_setup(enabled):.0f} ns |")
    previous = Task.asyncio_interop
    try:
        for enabled in (False, True):
            Task.asyncio_interop = enabled
            pending_awaits(min(2000, args.rounds))
            best = min(pending_awaits(args.rounds) for _ in range(args.repeats))
            print(f"| pending await by flpit code, end to end, interop {'on' if enabled else 'off'} | {best:.2f} µs |")
        Task.asyncio_interop = True
        best = min(asyncio_round_trips(max(1, args.rounds // 4)) for _ in range(args.repeats))
        print(f"| `await Task.run(...)` from an asyncio loop thread | {best:.1f} µs |")
    finally:
        Task.asyncio_interop = previous


if __name__ == "__main__":
    main()
