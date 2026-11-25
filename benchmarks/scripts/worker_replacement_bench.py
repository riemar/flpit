"""What replacing waiting workers buys a pool running sync calls, and that CPU work is left alone.

    python benchmarks/scripts/worker_replacement_bench.py

100 work items that each wait 50 ms (``time.sleep``, standing in for a sync client call), and
40 CPU-bound items, on the default pool: with replacement (the default) and without it
(``burst_workers=1``, which never lets the pool grow past ``min_workers`` quickly). Each case
runs in a fresh interpreter.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

CASE = textwrap.dedent("""
    import sys, threading, time
    from flpit.task import Task
    if sys.argv[1] == "off":
        Task.configure(burst_workers=1)
    def wait(): time.sleep(0.05)
    def compute():
        total = 0
        for i in range(300_000):
            total += i
    def burst(work, n):
        start = time.perf_counter()
        for t in [Task.run(work) for _ in range(n)]:
            t.result()
        return (time.perf_counter() - start) * 1000
    burst(wait, 10)
    waiting = min(burst(wait, 100) for _ in range(3))
    before = threading.active_count()
    computing = burst(compute, 40)
    print(f"{waiting:.0f} {computing:.0f} {threading.active_count() - before}")
""")


def main() -> None:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]} ({'GIL' if gil else 'free-threaded'})")
    print()
    print("| default pool | 100 items waiting 50 ms | 40 CPU-bound items | threads added by the CPU items |")
    print("|---|---:|---:|---:|")
    for mode, label in (("off", "without replacement"), ("on", "with replacement")):
        out = subprocess.run([sys.executable, "-c", CASE, mode], capture_output=True, text=True, check=True)
        waiting, computing, added = out.stdout.split()
        print(f"| {label} | {waiting} ms | {computing} ms | {added} |")


if __name__ == "__main__":
    main()
