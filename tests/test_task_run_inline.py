"""Task.run_inline: start a coroutine on the calling thread until its first real suspension.

Two groups of tests:

* **Scenarios with a .NET reference.** Calling an ``async`` method in .NET runs it
  synchronously until its first ``await`` of something incomplete. Each scenario names the
  C# program it mirrors and the output .NET gives for it. The start order, awaiting
  completed work, an exception before the first ``await`` and ``Task.Run`` queuing an async
  lambda were run on .NET 8.0.34 and 10.0.15 with ``lab/dotnet/AsyncStartOrder``; the other
  expectations come from the .NET documentation.
* **Execution probes**: thread identity, hops, context isolation, the depth fallback and
  calls from threads that are not pool workers.
"""
from __future__ import annotations

import gc
import sys
import threading
import warnings
from collections.abc import AsyncGenerator
from typing import Any

import pytest

import flpit.task as task_module
from flpit.core.linq import ArgumentOutOfRangeError
from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    task,
    OperationCanceledError,
    RuntimeShutdownError,
    Task,
    TaskCompletionSource,
    TaskCreationOptions,
)
from flpit.threading import AsyncLocal


@pytest.fixture(scope="module", autouse=True)
def default_sized_pool() -> Any:
    """Several workers, whatever an earlier module configured: some scenarios block one worker
    in ``wait()`` while the coroutine they started resumes on another."""
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(min_workers=8, max_workers=64)
    yield
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


def on_pool[R](function: Any) -> R:
    """Run ``function`` on a pool worker (as a framework handling a request does) and return its result."""
    return Task.run(function).result()


def is_pool_worker(thread: threading.Thread) -> bool:
    return thread.name.startswith("Task-worker-")


# ---------------------------------------------------------------------------
# Scenarios with a .NET reference
# ---------------------------------------------------------------------------


def test_code_before_the_first_incomplete_await_runs_before_the_caller_continues() -> None:
    """C#::

        var log = new List<string>(); var tcs = new TaskCompletionSource();
        async Task M() { log.Add("A"); await Task.CompletedTask; log.Add("B"); await tcs.Task; log.Add("C"); }
        var t = M(); log.Add("caller"); tcs.SetResult(); t.Wait();
        // log: A, B, caller, C
    """

    def scenario() -> list[str]:
        log: list[str] = []
        tcs: TaskCompletionSource[None] = TaskCompletionSource()

        async def m() -> None:
            log.append("A")
            await Task.completed_task
            log.append("B")
            await tcs.task
            log.append("C")

        t = Task.run_inline(m)
        log.append("caller")
        assert not t.done()
        tcs.set_result(None)
        t.wait()
        return log

    assert on_pool(scenario) == ["A", "B", "caller", "C"]
    assert scenario() == ["A", "B", "caller", "C"]  # the same from a thread outside the pool


def test_a_coroutine_that_never_suspends_has_completed_on_return() -> None:
    """C#: ``async Task<int> M() { await Task.CompletedTask; return 42; }`` -- ``M().IsCompletedSuccessfully`` is true."""

    async def m() -> int:
        await Task.completed_task
        return 42

    def scenario() -> tuple[str, int]:
        t = Task.run_inline(m)
        return t.status, t.result()

    assert on_pool(scenario) == (Task.SUCCEEDED, 42)


def test_exception_before_the_first_suspension_is_captured_in_the_task() -> None:
    """C#: ``async Task M() { throw new InvalidOperationException("boom"); }``

    ``var t = M();`` does not throw; ``t.IsFaulted`` is true and awaiting it rethrows.
    """

    async def m() -> None:
        raise RuntimeError("boom")

    def scenario() -> tuple[Task[None]]:
        # In a tuple: Task.run would await a returned awaitable.
        return (Task.run_inline(m),)  # must not raise

    (t,) = on_pool(scenario)
    assert t.status == Task.FAILED
    with pytest.raises(RuntimeError, match="boom"):
        t.result()


def test_exception_after_awaiting_completed_tasks_is_still_captured() -> None:
    async def m() -> None:
        await Task.completed_task
        await Task.delay(0)
        raise ValueError("late but synchronous")

    t = Task.run_inline(m)
    assert t.status == Task.FAILED
    exception = t.exception()
    assert isinstance(exception, AggregateError)
    assert isinstance(exception.exceptions[0], ValueError)


def test_operation_canceled_before_the_first_suspension_cancels_the_task() -> None:
    """C#: an async method that throws ``OperationCanceledException`` completes as Canceled."""

    async def m() -> None:
        raise OperationCanceledError("stop")

    t = Task.run_inline(m)
    assert t.status == Task.CANCELLED
    with pytest.raises(OperationCanceledError, match="stop"):
        t.result()


def test_already_cancelled_token_cancels_without_running_anything() -> None:
    """C#: ``Task.Run(func, cancelledToken)`` is Canceled and never invokes ``func``.

    (An async method has no token of its own; the ``token`` of run_inline is the one
    of ``Task.run``, and behaves as there.)
    """
    ran: list[str] = []
    cts = CancellationTokenSource()
    cts.cancel()

    async def m() -> None:
        ran.append("ran")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)  # "coroutine was never awaited"
        for work in (m, m()):
            t = Task.run_inline(work, token=cts.token)
            assert t.status == Task.CANCELLED
        gc.collect()
    assert ran == []


def test_exception_after_the_first_suspension_faults_the_task_later() -> None:
    tcs: TaskCompletionSource[None] = TaskCompletionSource()

    async def m() -> None:
        await tcs.task
        raise KeyError("after")

    t = Task.run_inline(m)
    assert not t.done()
    tcs.set_result(None)
    with pytest.raises(KeyError):
        t.result()


# ---------------------------------------------------------------------------
# Execution probes
# ---------------------------------------------------------------------------


def test_runs_on_the_calling_worker_until_the_first_suspension() -> None:
    def scenario() -> tuple[threading.Thread, dict[str, threading.Thread]]:
        seen: dict[str, threading.Thread] = {}

        async def m() -> None:
            seen["before"] = threading.current_thread()
            await Task.yield_now()
            seen["after"] = threading.current_thread()

        Task.run_inline(m).wait()
        return threading.current_thread(), seen

    caller, seen = on_pool(scenario)
    assert seen["before"] is caller
    assert is_pool_worker(seen["after"])


def test_from_a_thread_outside_the_pool_it_runs_there_then_resumes_on_the_pool() -> None:
    seen: dict[str, threading.Thread] = {}

    async def m() -> str:
        seen["before"] = threading.current_thread()
        await Task.yield_now()
        seen["after"] = threading.current_thread()
        return "done"

    t = Task.run_inline(m)
    assert seen["before"] is threading.current_thread()
    assert t.result() == "done"
    assert is_pool_worker(seen["after"])


def test_task_run_still_never_runs_on_the_calling_thread() -> None:
    seen: list[threading.Thread] = []

    async def m() -> None:
        seen.append(threading.current_thread())

    Task.run(m).wait()
    assert seen and seen[0] is not threading.current_thread()


def test_awaiting_completed_tasks_does_not_hop() -> None:
    def scenario() -> tuple[threading.Thread, set[threading.Thread], str]:
        threads: set[threading.Thread] = set()
        done_source: TaskCompletionSource[int] = TaskCompletionSource()
        done_source.set_result(1)

        async def inner() -> int:
            threads.add(threading.current_thread())
            return 2

        async def m() -> int:
            total = 0
            threads.add(threading.current_thread())
            await Task.completed_task
            threads.add(threading.current_thread())
            total += await done_source.task
            await Task.delay(0)
            total += await Task.run_inline(inner)  # completed synchronously as well
            threads.add(threading.current_thread())
            return total

        t = Task.run_inline(m)
        status = t.status
        assert t.result() == 3
        return threading.current_thread(), threads, status

    caller, threads, status = on_pool(scenario)
    assert status == Task.SUCCEEDED
    assert threads == {caller}


def test_context_flows_in_but_changes_do_not_flow_back() -> None:
    local: AsyncLocal[str] = AsyncLocal()

    def scenario() -> tuple[str | None, list[str | None], str | None]:
        local.value = "caller"
        seen: list[str | None] = []

        async def m() -> None:
            seen.append(local.value)
            local.value = "inside"
            await Task.yield_now()
            seen.append(local.value)

        t = Task.run_inline(m)
        after_start = local.value
        t.wait()
        return after_start, seen, local.value

    after_start, seen, at_end = on_pool(scenario)
    assert seen == ["caller", "inside"]
    assert after_start == "caller"
    assert at_end == "caller"


def test_each_inline_task_is_the_current_task_while_it_runs() -> None:
    seen: list[Any] = []

    async def m() -> None:
        seen.append(task_module._current_task.value)

    t = Task.run_inline(m)
    assert seen == [t]
    assert task_module._current_task.value is None


def test_deep_nesting_falls_back_to_the_pool_instead_of_overflowing_the_stack() -> None:
    depth = 1500  # inline all the way down this would need several thousand frames
    threads: list[threading.Thread] = []

    async def nest(level: int) -> int:
        threads.append(threading.current_thread())
        if level == 0:
            return 0
        return 1 + await Task.run_inline(nest, level - 1)

    def scenario() -> int:
        return Task.run_inline(nest, depth).result()

    assert on_pool(scenario) == depth
    # The first levels run on the calling worker. Then a level is queued, and since the
    # caller blocks in result(), another worker runs it.
    assert len(set(threads[: task_module._MAX_INLINE_DEPTH])) == 1
    assert len(set(threads)) > 1


def test_nesting_depth_is_restored_after_each_start() -> None:
    async def fails() -> None:
        raise RuntimeError("x")

    async def suspends() -> None:
        await Task.yield_now()

    for work in (fails, suspends, lambda: 1):
        Task.run_inline(work)
        assert task_module._thread_state.inline == 0


def test_on_the_runtime_internal_threads_it_queues_instead() -> None:
    result: dict[str, Any] = {}

    async def m() -> None:
        result["thread"] = threading.current_thread()

    def internal_thread() -> None:
        task_module._thread_state.internal = True  # as on the timer and IO threads
        result["task"] = Task.run_inline(m)

    thread = threading.Thread(target=internal_thread)
    thread.start()
    thread.join()
    result["task"].wait()
    assert result["thread"] is not thread


def test_async_generators_started_inline_on_a_foreign_thread_use_flpit_hooks() -> None:
    hooks_before = sys.get_asyncgen_hooks()
    seen: list[Any] = []

    async def numbers() -> AsyncGenerator[int]:
        yield 1

    async def m() -> int:
        seen.append(sys.get_asyncgen_hooks().firstiter)
        async for value in numbers():
            return value
        return 0

    assert Task.run_inline(m).result() == 1
    assert seen == [task_module._asyncgen_firstiter]
    assert sys.get_asyncgen_hooks() == hooks_before


def test_synchronous_callables_run_inline_too() -> None:
    def scenario() -> tuple[threading.Thread, threading.Thread, str]:
        seen: list[threading.Thread] = []

        def work(x: int, *, token: Any) -> int:
            seen.append(threading.current_thread())
            return x * 2

        t = Task.run_inline(work, 21, token=CancellationTokenSource().token, pass_token=True)
        assert t.result() == 42
        return threading.current_thread(), seen[0], t.status

    caller, ran_on, status = on_pool(scenario)
    assert ran_on is caller
    assert status == Task.SUCCEEDED


def test_coroutine_functions_with_arguments_and_pass_token() -> None:
    source = CancellationTokenSource()

    async def m(a: int, b: int = 0, *, token: Any) -> tuple[int, Any]:
        return a + b, token

    t = Task.run_inline(m, 1, b=2, token=source.token, pass_token=True)
    assert t.result() == (3, source.token)


def test_other_awaitables_are_accepted() -> None:
    finished = Task.run_inline(lambda: "value")
    assert Task.run_inline(finished).result() == "value"


def test_continuations_run_after_inline_completion() -> None:
    async def m() -> int:
        return 5

    assert Task.run_inline(m).continue_with(lambda t: t.result() + 1).result() == 6


def test_long_running_is_rejected_and_closes_the_coroutine() -> None:
    async def m() -> None:
        pass

    coroutine = m()
    with pytest.raises(ArgumentOutOfRangeError):
        Task.run_inline(coroutine, creation_options=TaskCreationOptions.LONG_RUNNING)
    assert coroutine.cr_frame is None  # closed: no "never awaited" warning


def test_invalid_arguments_are_rejected_as_by_task_run() -> None:
    async def m() -> None:
        pass

    coroutine = m()
    with pytest.raises(TypeError):
        Task.run_inline(coroutine, 1)
    assert coroutine.cr_frame is None
    with pytest.raises(TypeError):
        Task.run_inline(42)
    with pytest.raises(ValueError):
        Task.run_inline(m, pass_token=True)


def test_other_creation_options_behave_as_with_task_run() -> None:
    async def m() -> None:
        pass

    options = TaskCreationOptions.RUN_CONTINUATIONS_ASYNCHRONOUSLY
    t = Task.run_inline(m, creation_options=options)
    assert t.creation_options == options
    assert t.status == Task.SUCCEEDED


def test_concurrent_inline_starts_from_many_workers() -> None:
    gate: TaskCompletionSource[int] = TaskCompletionSource()

    async def work(i: int) -> int:
        if i % 3 == 0:
            await Task.yield_now()
        elif i % 3 == 1:
            return i + await gate.task  # pending until the gate opens
        return i

    def submitter(offset: int) -> list[Task[int]]:
        return [Task.run_inline(work, offset + i) for i in range(300)]

    submitters = [Task.run(submitter, k * 1000) for k in range(8)]
    tasks = [t for s in submitters for t in s.result()]
    gate.set_result(0)
    assert Task.when_all(tasks).result() == [t_index for k in range(8) for t_index in range(k * 1000, k * 1000 + 300)]


# ---------------------------------------------------------------------------
# @task(inline=True)
# ---------------------------------------------------------------------------


def test_inline_task_calls_start_in_turn_like_csharp_async_method_calls() -> None:
    """``lab/dotnet/AsyncStartOrder`` case 1, on .NET 8 and 10::

        var a = FooAsync(); var b = BarAsync(); await Task.WhenAll(a, b);

    Foo runs to its first incomplete await (after its CPU work) before FooAsync() returns;
    only then does Bar start. Both run on the caller's thread until then, and overlap after.
    """
    log: list[tuple[str, threading.Thread]] = []
    foo_gate: TaskCompletionSource[None] = TaskCompletionSource()
    bar_gate: TaskCompletionSource[None] = TaskCompletionSource()  # C#: Task.Delay(10)

    def note(step: str) -> None:
        log.append((step, threading.current_thread()))

    @task(inline=True)
    async def foo() -> None:
        note("Foo: start")
        sum(range(100_000))  # CPU work before the first await
        note("Foo: before first await")
        await foo_gate.task
        note("Foo: after await")

    @task(inline=True)
    async def bar() -> None:
        note("Bar: start")
        await bar_gate.task
        note("Bar: after await")

    def scenario() -> threading.Thread:
        note("caller: before foo()")
        a = foo()
        note("caller: foo() returned")
        b = bar()
        note("caller: bar() returned")
        bar_gate.set_result(None)
        b.wait()  # Bar finishes while Foo still waits: they overlap
        foo_gate.set_result(None)
        Task.when_all(a, b).wait()
        return threading.current_thread()

    caller = on_pool(scenario)
    steps = [step for step, _ in log]
    assert steps[:6] == [
        "caller: before foo()", "Foo: start", "Foo: before first await",
        "caller: foo() returned", "Bar: start", "caller: bar() returned",
    ]
    assert all(thread is caller for _, thread in log[:6])
    assert steps.index("Bar: after await") < steps.index("Foo: after await")


def test_plain_task_calls_start_on_the_pool() -> None:
    """``@task`` stays ``Task.Run`` on every call: the body never runs on the caller."""
    seen: list[threading.Thread] = []

    @task
    async def queued() -> None:
        seen.append(threading.current_thread())

    @task()
    def queued_sync() -> None:
        seen.append(threading.current_thread())

    Task.when_all(queued(), queued_sync()).wait()
    assert len(seen) == 2
    assert threading.current_thread() not in seen


def test_inline_task_rules_match_run_inline() -> None:
    @task(inline=True)
    async def fails() -> None:
        raise RuntimeError("captured")

    @task(inline=True)
    async def finishes(x: int) -> int:
        await Task.completed_task
        return x * 2

    t = fails()  # does not raise
    assert t.status == Task.FAILED
    done = finishes(21)
    assert done.status == Task.SUCCEEDED and done.result() == 42
    assert finishes.__name__ == "finishes"


def test_inline_is_rejected_for_plain_functions() -> None:
    with pytest.raises(TypeError, match="async def"):
        @task(inline=True)
        def plain() -> int:
            return 1


class TestShutdown:
    @pytest.fixture(autouse=True)
    def isolated_runtime(self) -> Any:
        previous = dict(task_module._runtime_config)
        Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
        yield
        Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
        Task.configure(**previous)

    def test_rejected_while_the_runtime_shuts_down(self) -> None:
        tcs: TaskCompletionSource[None] = TaskCompletionSource()
        attempt: dict[str, Any] = {}
        running = threading.Event()

        async def blocker() -> None:
            running.set()
            try:
                await tcs.task
            except OperationCanceledError:
                # Shutdown is in progress: starting new work from here is refused.
                async def late() -> None:
                    pass

                coroutine = late()
                try:
                    Task.run_inline(coroutine)
                except RuntimeShutdownError as error:
                    attempt["error"] = error
                attempt["closed"] = coroutine.cr_frame is None
                raise

        Task.run(blocker)
        # The blocker must be running when shutdown starts: a task still queued then is
        # cancelled before it runs (correctly), and its except block never executes.
        assert running.wait(2)
        Task.shutdown(grace_timeout=1.0, worker_timeout=1.0)
        assert isinstance(attempt.get("error"), RuntimeShutdownError)
        assert attempt["closed"]

    def test_a_suspended_inline_task_is_cancelled_by_shutdown(self) -> None:
        tcs: TaskCompletionSource[None] = TaskCompletionSource()

        async def m() -> None:
            await tcs.task

        t = Task.run_inline(m)
        assert not t.done()
        report = Task.shutdown(grace_timeout=1.0, worker_timeout=1.0)
        assert t.status == Task.CANCELLED
        assert report.tasks_cancelled >= 1
