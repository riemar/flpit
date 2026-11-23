"""The flpit counterpart of lab/dotnet/AsyncStartOrder: the same four cases, the same checks.

Shows that starting coroutines with ``@task(inline=True)`` / ``Task.run_inline`` behaves like
calling async methods in C#, and that ``Task.run`` of an async function queues like
``Task.Run(async () => ...)``. Each check prints PASS/FAIL; the exit code is the number of failures.

    python lab/task/async_start_order.py
    dotnet run -f net8.0 --project lab/dotnet/AsyncStartOrder      # the C# original, to compare

Line by line, the C# names map to:

    async Task FooAsync() { ... }      @task(inline=True) async def foo(): ...
    var a = FooAsync();                a = foo()
    await Task.Delay(100)              await Task.delay(0.1)
    await Task.CompletedTask           await Task.completed_task
    await Task.FromResult(41)          await (a completed TaskCompletionSource).task   (flpit has no from_result)
    Task.Run(async () => ...)          Task.run(async_function)
    Environment.CurrentManagedThreadId threading.current_thread().name
"""
from __future__ import annotations

import sys
import threading
import time

from flpit.core.linq import InvalidOperationError
from flpit.task import Task, TaskCompletionSource, task

failures = 0


def check(ok: bool, what: str) -> None:
    global failures
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures += 1


def spin(ms: int) -> None:
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        pass


def thread() -> str:
    return threading.current_thread().name


# var a = FooAsync(); var b = BarAsync(); await Task.WhenAll(a, b);
async def calling_async_methods_runs_each_prefix_inline_in_turn() -> None:
    print("1. a = foo(); b = bar()   (C#: var a = FooAsync(); var b = BarAsync();)")
    log: list[tuple[str, str, float]] = []
    clock = time.perf_counter()

    def note(step: str) -> None:
        log.append((step, thread(), (time.perf_counter() - clock) * 1000))

    @task(inline=True)
    async def foo() -> None:
        note("Foo: start")
        spin(200)                        # CPU work before the first await
        note("Foo: before first await")
        await Task.delay(0.1)            # first incomplete await
        note("Foo: after await")

    @task(inline=True)
    async def bar() -> None:
        note("Bar: start")
        await Task.delay(0.01)
        note("Bar: after await")

    note("caller: before FooAsync()")
    a = foo()
    note("caller: FooAsync() returned")
    b = bar()
    note("caller: BarAsync() returned")
    await Task.when_all(a, b)

    for step, name, ms in log:
        print(f"       {ms:4.0f} ms  {name:>14}  {step}")
    steps = [step for step, _, _ in log]
    prefix = [
        "caller: before FooAsync()", "Foo: start", "Foo: before first await",
        "caller: FooAsync() returned", "Bar: start", "caller: BarAsync() returned",
    ]
    check(steps[: len(prefix)] == prefix,
          "Foo runs to its first incomplete await before foo() returns; only then does Bar start")
    caller = log[0][1]
    check(all(name == caller for _, name, _ in log[: len(prefix)]),
          "Foo's and Bar's parts before their first await run on the caller's thread")
    foo_reached_await = next(ms for step, _, ms in log if step == "Foo: before first await")
    bar_started = next(ms for step, _, ms in log if step == "Bar: start")
    check(bar_started >= foo_reached_await and bar_started >= 190,
          f"Bar starts only after Foo's 200 ms of CPU work (Bar started at {bar_started:.0f} ms)")
    bar_done = next(ms for step, _, ms in log if step == "Bar: after await")
    foo_done = next(ms for step, _, ms in log if step == "Foo: after await")
    check(bar_done < foo_done,
          "after the first await both are in flight at once (Bar's 10 ms delay finishes before Foo's 100 ms)")


def awaiting_completed_work_does_not_suspend() -> None:
    print("2. awaiting already completed tasks")
    log: list[str] = []
    forty_one: TaskCompletionSource[int] = TaskCompletionSource()
    forty_one.set_result(41)             # C#: Task.FromResult(41)

    @task(inline=True)
    async def m() -> int:
        log.append("M: start")
        await Task.completed_task
        x = await forty_one.task
        await Task.delay(0)              # completes synchronously
        log.append("M: end")
        return x + 1

    t = m()
    log.append("caller")
    check(log == ["M: start", "M: end", "caller"] and t.status == Task.SUCCEEDED and t.result() == 42,
          "an async method that only awaits completed work has finished when the call returns")


def exception_before_first_await_is_captured_not_thrown() -> None:
    print("3. exception before the first await")

    @task(inline=True)
    async def boom() -> None:
        await Task.completed_task
        raise InvalidOperationError("boom")

    t: Task[None] | None = None
    threw = False
    try:
        t = boom()
    except Exception:
        threw = True
    check(not threw and t is not None and t.status == Task.FAILED and isinstance(t.exception(), InvalidOperationError),
          "calling does not throw; the returned task is faulted")


def task_run_queues_even_an_async_function() -> None:
    print("4. Task.run(async_function)   (C#: Task.Run(async () => ...))")
    caller = thread()
    body_thread: list[str] = []
    gate = threading.Event()

    async def body() -> None:
        body_thread.append(thread())
        gate.wait()                      # inline, this would deadlock the caller
        await Task.yield_now()

    t = Task.run(body)
    returned_before_body_finished = not t.done()
    gate.set()
    t.result()
    check(returned_before_body_finished and body_thread[0] != caller,
          "Task.run returns at once and runs even the async function's first part on the pool")


def main() -> int:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]} ({'GIL' if gil else 'free-threaded'})")
    # C#: CallingAsyncMethodsRunsEachPrefixInlineInTurn().GetAwaiter().GetResult()
    Task.run_inline(calling_async_methods_runs_each_prefix_inline_in_turn()).result()
    awaiting_completed_work_does_not_suspend()
    exception_before_first_await_is_captured_not_thrown()
    task_run_queues_even_an_async_function()
    print("ALL PASSED" if failures == 0 else f"{failures} FAILED")
    return failures


if __name__ == "__main__":
    sys.exit(main())
