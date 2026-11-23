"""Plain ``async def`` vs ``@task(inline=True)`` inside await chains.

Shows why ``@task(inline=True)`` belongs where a Task is started, not on every
``async def``: a plain ``await foo()`` runs the coroutine inside the caller's task, while
a decorated function creates a Task per call, and every level of a suspended chain
then resumes as its own pool work item.

    python benchmarks/scripts/inline_chain_bench.py [--depth 10] [--ops 3000]

Each figure includes starting and waiting for the outer task (about 3.5 µs).
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

from flpit.task import Task, task


async def plain(level: int) -> int:
    if level == 0:
        await Task.yield_now()  # one real suspension at the bottom of the chain
        return 0
    return 1 + await plain(level - 1)


@task(inline=True)
async def decorated(level: int) -> int:
    if level == 0:
        await Task.yield_now()
        return 0
    return 1 + await decorated(level - 1)


async def leaf_plain() -> int:
    return 1


@task(inline=True)
async def leaf_decorated() -> int:
    return 1


async def call_plain() -> int:
    return await leaf_plain()


async def call_decorated() -> int:
    return await leaf_decorated()


def measure(start: Callable[[], Any], ops: int, repeats: int) -> float:
    """Best µs per ``Task.run_inline(start()).result()``, measured on a pool worker."""

    def body() -> float:
        t0 = time.perf_counter()
        for _ in range(ops):
            Task.run_inline(start()).result()
        return (time.perf_counter() - t0) / ops * 1e6

    return min(Task.run(body).result() for _ in range(repeats))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--ops", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    depth = args.depth
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]} ({'GIL' if gil else 'free-threaded'}), ops={args.ops}, best of {args.repeats}")
    print()
    print("| case | µs per call |")
    print("|---|---:|")
    rows = [
        (f"await chain, {depth} levels, plain async def", lambda: plain(depth)),
        (f"await chain, {depth} levels, every level @task(inline=True)", lambda: decorated(depth)),
        ("await of one call that never suspends, plain async def", call_plain),
        ("await of one call that never suspends, @task(inline=True)", call_decorated),
    ]
    for label, start in rows:
        print(f"| {label} | {measure(start, args.ops, args.repeats):.1f} |")


if __name__ == "__main__":
    main()
