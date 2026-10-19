"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of tests from current dotnet/runtime TaskRtTests_Core.cs.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskRtTests_Core.cs

Every public test method in that C# file is represented below with the original
PascalCase name prefixed by ``test_``. Supported behavior is translated to
FlpIt's Task API. Tests requiring unsupported .NET APIs are retained as explicit
pytest skips so the missing contract remains visible for future decisions.
"""
from __future__ import annotations

import threading

import pytest

from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    InvalidStateError,
    OperationCanceledError,
    Task,
    TaskCompletionSource,
)


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


# TaskCompletionSource tests migrated from this .NET source file.
def _race_completion_source(kind: str, concurrency: int = 32) -> None:
    """Race external completion calls and assert exactly one terminal winner."""
    source: TaskCompletionSource[int] = TaskCompletionSource()
    barrier = threading.Barrier(concurrency)
    outcomes: list[bool] = []
    outcomes_lock = threading.Lock()

    def contender(index: int) -> None:
        barrier.wait(timeout=3)
        if kind == "result":
            won = source.try_set_result(10)
        elif kind == "cancel":
            won = source.try_set_canceled()
        else:
            won = source.try_set_exception(ValueError(f"failure-{index}"))
        with outcomes_lock:
            outcomes.append(won)

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert len(outcomes) == concurrency
    assert sum(outcomes) == 1
    if kind == "result":
        assert source.task.result(timeout=2) == 10
    elif kind == "cancel":
        assert source.task.cancelled()
        with pytest.raises(OperationCanceledError):
            source.task.result(timeout=2)
    else:
        assert source.task.status == Task.FAILED


def test_RunTCSCompletionStateTests() -> None:
    _race_completion_source("result")


def test_RunTCSCompletionStateTests_SetCancel() -> None:
    _race_completion_source("cancel")


def test_RunTCSCompletionStateTests_SetException() -> None:
    _race_completion_source("exception")


def test_RunTaskCompletionSourceTests() -> None:
    token_source = CancellationTokenSource()
    try:
        promise: TaskCompletionSource[int] = TaskCompletionSource(token_source.token)
        assert promise.task is promise.task
        assert promise.task.status == Task.PENDING
        # As in .NET, the value supplied as the source's state is not a linked
        # cancellation token: canceling that source does not complete the promise.
        token_source.cancel()
        assert not promise.task.done()

        error = ValueError("persistent failure")
        promise.set_exception(error)
        assert promise.task.status == Task.FAILED
        assert not promise.try_set_result(15)
        assert not promise.try_set_exception(ValueError("later"))
        assert not promise.try_set_canceled()
        with pytest.raises(InvalidStateError):
            promise.set_result(10)
        with pytest.raises(InvalidStateError):
            promise.set_exception(ValueError("later"))
        with pytest.raises(InvalidStateError):
            promise.set_canceled()
    finally:
        token_source.dispose()

    multi: TaskCompletionSource[int] = TaskCompletionSource()
    errors = [ValueError("Exception A"), TypeError("Exception B")]
    assert multi.try_set_exception(errors)


def test_RunTaskCompletionSourceTests_Negative() -> None:
    promise: TaskCompletionSource[int] = TaskCompletionSource()
    with pytest.raises(TypeError):
        promise.try_set_exception(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        promise.try_set_exception([ValueError("valid"), None])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        promise.try_set_exception([])
    assert not promise.task.done()

    promise.set_result(10)
    assert not promise.try_set_result(15)
    with pytest.raises(InvalidStateError):
        promise.set_result(15)
    assert promise.task.result(timeout=2) == 10


def test_RunTaskCompletionSourceTests_SetException() -> None:
    promise: TaskCompletionSource[int] = TaskCompletionSource()
    errors = [ValueError("Exception A"), ZeroDivisionError("Exception B")]
    assert promise.try_set_exception(iter(errors))
    assert promise.task.status == Task.FAILED

    with pytest.raises(AggregateError):
        promise.task.result(timeout=2)


def test_RunTaskCompletionSourceTests_SetCanceled() -> None:
    with CancellationTokenSource() as cts:
        promise: TaskCompletionSource[int] = TaskCompletionSource()
        promise.set_canceled(cts.token)
        assert promise.task.status == Task.CANCELLED
        with pytest.raises(OperationCanceledError) as caught:
            promise.task.result(timeout=2)
        assert caught.value.token is cts.token
        with pytest.raises(InvalidStateError):
            promise.set_canceled(cts.token)


def test_RunTaskCompletionSourceTests_CancellationTests() -> None:
    with CancellationTokenSource() as cts:
        promise: TaskCompletionSource[int] = TaskCompletionSource(cts.token)
        cts.cancel()
        assert promise.task.status == Task.PENDING

        promise.set_canceled()
        assert promise.task.cancelled()
        assert not promise.try_set_exception(ValueError("spam"))
        assert not promise.try_set_result(10)
        assert not promise.try_set_canceled()
        with pytest.raises(InvalidStateError):
            promise.set_result(15)
        with pytest.raises(InvalidStateError):
            promise.set_exception(ValueError("yet another exception"))
        with pytest.raises(InvalidStateError):
            promise.set_canceled()
        with pytest.raises(OperationCanceledError):
            promise.task.result(timeout=2)


def test_RunTaskCreateTests() -> None:
    _unsupported("Task constructor, Task.Start, and TaskCreationOptions")


def test_TestTaskTConstruction_bare() -> None:
    """Adapted: Task.run callable arguments, returned value, and repeated result reads."""
    seen: list[object] = []
    payload = object()

    def work(value: object) -> int:
        seen.append(value)
        return 42

    task = Task.run(work, payload)
    assert task.result(timeout=2) == 42
    assert task.result(timeout=2) == 42
    assert seen == [payload]
    assert task.done()


def test_TestTaskTConstruction_ct() -> None:
    """Adapted: Task.run accepts a token and doesn't start pre-cancelled work."""
    live = CancellationTokenSource()
    try:
        assert Task.run(lambda: 42, token=live.token).result(timeout=2) == 42
    finally:
        live.dispose()

    cancelled = CancellationTokenSource()
    cancelled.cancel()
    invoked = threading.Event()
    try:
        task = Task.run(lambda: invoked.set(), token=cancelled.token)
        with pytest.raises(OperationCanceledError):
            task.result(timeout=2)
        assert task.cancelled()
        assert not invoked.is_set()
    finally:
        cancelled.dispose()


def test_TestTaskTConstruction_tco() -> None:
    _unsupported("TaskCreationOptions and Task<T> constructor/Factory.StartNew overloads")


def test_TestTaskTConstruction_ct_tco() -> None:
    _unsupported("TaskCreationOptions combined with Task<T> constructor/factory overloads")


def test_RunBasicTaskWithResultTest() -> None:
    state = object()
    promise: TaskCompletionSource[int] = TaskCompletionSource(state)
    assert promise.task is promise.task
    assert promise.task.async_state is state
    assert promise.task.status == Task.PENDING
    promise.set_result(42)
    assert promise.task.result(timeout=2) == 42
    assert promise.task.status == Task.SUCCEEDED


def test_RunBasicTaskWithResultTest_Negative() -> None:
    """Adapted: invalid delegates are rejected by Task.run."""
    with pytest.raises(TypeError):
        Task.run(None)
    with pytest.raises(TypeError):
        Task.run(object())


def test_RunBasicTaskWithResultTest_PromiseTestsAndCancellation() -> None:
    promise: TaskCompletionSource[int] = TaskCompletionSource()

    async def consume() -> int:
        return await promise.task

    waiter = Task.run(consume)
    assert promise.try_set_result(123)
    assert waiter.result(timeout=2) == 123

    cancelled_promise: TaskCompletionSource[int] = TaskCompletionSource()

    async def consume_cancelled() -> int:
        return await cancelled_promise.task

    cancelled_waiter = Task.run(consume_cancelled)
    assert cancelled_promise.try_set_canceled()
    with pytest.raises(OperationCanceledError):
        cancelled_waiter.result(timeout=2)


def test_RunSynchronouslyTest() -> None:
    _unsupported("Task.RunSynchronously and TaskFactory.StartNew")


def test_CoreRunSynchronouslyTest() -> None:
    _unsupported("Task.RunSynchronously and TaskScheduler selection")


def test_CoreRunSynchronouslyTest_NegativeTests() -> None:
    _unsupported("Task.RunSynchronously, Task.Start, and invalid task-state transitions")


def test_RunTaskExceptionTest() -> None:
    """Adapted: preserve and re-raise the original exception from Task.result()."""
    good = Task.run(lambda: 42)
    assert good.result(timeout=2) == 42

    error = ValueError("foobomb")

    def fail() -> int:
        raise error

    failed = Task.run(fail)
    with pytest.raises(ValueError, match="foobomb") as caught:
        failed.result(timeout=2)
    assert caught.value is error
    assert failed.done()


def test_RunTaskWaitAnyTests() -> None:
    """Adapted from WaitAny: the first completed task is returned; >64 waiters work."""
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    tasks = [Task.run(value_after, i, 0.05) for i in range(69)]
    fast = Task.run(value_after, 100, 0.002)
    tasks.insert(64, fast)
    winner = Task.when_any(tasks).result(timeout=2)
    assert winner is fast
    assert winner.result(timeout=2) == 100
    assert Task.when_any(Task.run(lambda: 7)).result(timeout=2).result(timeout=2) == 7


def test_RunTaskWaitAnyTests_Negative() -> None:
    with pytest.raises(ValueError):
        Task.when_any()
    with pytest.raises(TypeError):
        Task.when_any([object()])


def test_RunTaskWaitAnyTests_WithCancellationTokenTests() -> None:
    """Adapted: cancel the aggregate wait without cancelling its children."""
    source = CancellationTokenSource()

    async def slow(value: int) -> int:
        await Task.delay(0.05)
        return value

    first = Task.run(slow, 1)
    second = Task.run(slow, 2)
    try:
        aggregate = Task.when_any(first, second, token=source.token)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            aggregate.result(timeout=2)
        assert not first.cancelled()
        assert not second.cancelled()
        assert {first.result(timeout=2), second.result(timeout=2)} == {1, 2}
    finally:
        source.dispose()


def test_RunTaskWaitAllTests() -> None:
    """Adapted from WaitAll: when_all waits for all results and preserves input order."""
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    tasks = [Task.run(value_after, i, delay) for i, delay in [(1, 0.03), (2, 0.005), (3, 0.015)]]
    assert Task.when_all(tasks).result(timeout=2) == [1, 2, 3]


def test_RunLongRunningTaskTests() -> None:
    _unsupported("TaskCreationOptions.LongRunning and explicit TaskScheduler behavior")


def test_RunRefactoringTests() -> None:
    _unsupported("Task constructors/Start, TaskFactory.StartNew, and TaskCreationOptions")


def test_RunTaskStatusTests() -> None:
    """Adapt what FlpIt exposes: pending/completed/cancelled via done() and cancelled()."""
    source = CancellationTokenSource()
    try:
        pending = Task.delay(60, token=source.token)
        assert not pending.done()
        assert not pending.cancelled()
        source.cancel()
        with pytest.raises(OperationCanceledError):
            pending.result(timeout=2)
        assert pending.done()
        assert pending.cancelled()

        completed = Task.run(lambda: 123)
        assert completed.result(timeout=2) == 123
        assert completed.done()
        assert not completed.cancelled()
    finally:
        source.dispose()


def test_RunTaskStatusTests_NegativeTests() -> None:
    """Adapted: faults and cancellation remain distinguishable through public APIs."""
    failed = Task.run(lambda: (_ for _ in ()).throw(ValueError("fault")))
    with pytest.raises(ValueError, match="fault"):
        failed.result(timeout=2)
    assert failed.done()
    assert not failed.cancelled()

    source = CancellationTokenSource()
    try:
        cancelled = Task.delay(60, token=source.token)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            cancelled.result(timeout=2)
        assert cancelled.done()
        assert cancelled.cancelled()
    finally:
        source.dispose()


def test_RunTaskWaitTest() -> None:
    task = Task.run(lambda: None)
    assert task.result(timeout=2) is None
    assert task.done()


def test_Wait_SingleThreaded() -> None:
    _unsupported("Task.CompletedTask, Wait/WaitAll/WaitAny, and no-thread runtime mode")


def test_RunTaskWaitTest_NegativeTests() -> None:
    """Adapted exception part: result() re-raises the original task failure, not AggregateException."""
    error = RuntimeError("myexception")

    def fail() -> None:
        raise error

    task = Task.run(fail)
    with pytest.raises(RuntimeError, match="myexception") as caught:
        task.result(timeout=2)
    assert caught.value is error


def test_RunTaskRecursiveWaitTest() -> None:
    """Adapted to native await composition; blocking nested .NET Wait is not portable."""
    async def parent() -> int:
        child = Task.run(lambda: 42)
        return await child

    assert Task.run(parent).result(timeout=2) == 42


def test_RunTaskWaitTimeoutTest() -> None:
    """Adapted: result(timeout) times out without completing/cancelling the task."""
    started = threading.Event()
    release = threading.Event()

    def blocked() -> int:
        started.set()
        release.wait(2)
        return 42

    task = Task.run(blocked)
    try:
        assert started.wait(1)
        with pytest.raises(TimeoutError):
            task.result(timeout=0.01)
        assert not task.done()
    finally:
        release.set()
    assert task.result(timeout=2) == 42
    assert task.done()


def test_RunTaskRecursiveWaitTimeoutTest() -> None:
    _unsupported("Nested blocking waits and ThreadPool worker-injection behavior")


def test_RunTaskCanceledExceptionTests() -> None:
    _unsupported("TaskCanceledException constructors and .NET Task property on that exception")


def test_RunTaskSchedulerExceptionTests() -> None:
    _unsupported("TaskSchedulerException constructors; no matching FlpIt public exception")


def test_RunAsyncWaitHandleTests() -> None:
    _unsupported("IAsyncResult.AsyncWaitHandle; FlpIt exposes result(timeout), not a WaitHandle")
