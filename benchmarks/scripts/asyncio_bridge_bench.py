"""What @asyncio_task costs: shared bridge loops vs. the previous new asyncio.Runner per call.

    python benchmarks/scripts/asyncio_bridge_bench.py [calls]

Runs ``calls`` concurrent calls of a coroutine that awaits ``asyncio.sleep(0)`` (pure overhead)
and of one that sleeps 10 ms (I/O-like waiting), on each backend and the per-call Runner.
"""
from __future__ import annotations

import asyncio
import functools
import select
import sys
import time

from flpit import asyncio_bridge
from flpit.task import Task, asyncio_task, task


def runner_per_call(async_function):  # the decorator as it was before the bridge
    @functools.wraps(async_function)
    def wrapper(*args, **kwargs):
        with asyncio.Runner() as runner:
            return runner.run(async_function(*args, **kwargs))

    return task(wrapper)


async def overhead():
    await asyncio.sleep(0)


async def waiting():
    await asyncio.sleep(0.01)


def measure(decorated, calls: int) -> float:
    for t in [decorated() for _ in range(50)]:  # warm up: loops, workers
        t.result()
    start = time.perf_counter()
    for t in [decorated() for _ in range(calls)]:
        t.result()
    return time.perf_counter() - start


def main() -> None:
    calls = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    print(f"Python {sys.version.split()[0]}{'t' if not getattr(sys, '_is_gil_enabled', lambda: True)() else ''}, {calls} concurrent calls")
    backends = ["strands", "threads"] if hasattr(select, "epoll") else ["threads"]
    for name, body in (("sleep(0)", overhead), ("sleep(10 ms)", waiting)):
        row = [f"{name:>13}"]
        for backend in backends:
            asyncio_bridge.shutdown()
            asyncio_bridge.configure(backend=backend)
            row.append(f"{backend}: {measure(asyncio_task(body), calls) * 1e6 / calls:7.1f} µs/call")
        asyncio_bridge.shutdown()
        row.append(f"Runner per call: {measure(runner_per_call(body), calls) * 1e6 / calls:7.1f} µs/call")
        print("  ".join(row))
    Task.shutdown()


if __name__ == "__main__":
    main()
