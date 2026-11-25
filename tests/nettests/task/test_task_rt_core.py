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

import os
import threading
from datetime import timedelta

import pytest

from flpit.core.linq import ArgumentOutOfRangeError, InvalidOperationError
from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    InvalidStateError,
    OperationCanceledError,
    Task,
    TaskCanceledError,
    TaskCompletionSource,
    TaskCreationOptions,
)
from flpit.threading import ManualResetEvent


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


class _CountdownEvent:
    """Minimal System.Threading.CountdownEvent for the ported tests."""

    def __init__(self, count: int) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self.current_count = count
        if count == 0:
            self._event.set()

    def signal(self) -> None:
        with self._lock:
            self.current_count -= 1
            if self.current_count == 0:
                self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


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
        assert source.task.result() == 10
    elif kind == "cancel":
        assert source.task.cancelled()
        with pytest.raises(OperationCanceledError):
            source.task.result()
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
    assert promise.task.result() == 10


def test_RunTaskCompletionSourceTests_SetException() -> None:
    promise: TaskCompletionSource[int] = TaskCompletionSource()
    errors = [ValueError("Exception A"), ZeroDivisionError("Exception B")]
    assert promise.try_set_exception(iter(errors))
    assert promise.task.status == Task.FAILED

    # The .NET original: Wait() throws an AggregateException with both inner exceptions.
    with pytest.raises(AggregateError) as caught:
        promise.task.wait()
    assert caught.value.exceptions == tuple(errors)


def test_RunTaskCompletionSourceTests_SetCanceled() -> None:
    with CancellationTokenSource() as cts:
        promise: TaskCompletionSource[int] = TaskCompletionSource()
        promise.set_canceled(cts.token)
        assert promise.task.status == Task.CANCELLED
        with pytest.raises(OperationCanceledError) as caught:
            promise.task.result()
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
            promise.task.result()


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
    assert task.result() == 42
    assert task.result() == 42
    assert seen == [payload]
    assert task.done()


def test_TestTaskTConstruction_ct() -> None:
    """Adapted: Task.run accepts a token and doesn't start pre-cancelled work."""
    live = CancellationTokenSource()
    try:
        assert Task.run(lambda: 42, token=live.token).result() == 42
    finally:
        live.dispose()

    cancelled = CancellationTokenSource()
    cancelled.cancel()
    invoked = threading.Event()
    try:
        task = Task.run(lambda: invoked.set(), token=cancelled.token)
        with pytest.raises(OperationCanceledError):
            task.result()
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
    assert promise.task.result() == 42
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
    assert waiter.result() == 123

    cancelled_promise: TaskCompletionSource[int] = TaskCompletionSource()

    async def consume_cancelled() -> int:
        return await cancelled_promise.task

    cancelled_waiter = Task.run(consume_cancelled)
    assert cancelled_promise.try_set_canceled()
    with pytest.raises(OperationCanceledError):
        cancelled_waiter.result()


def test_RunSynchronouslyTest() -> None:
    _unsupported("Task.RunSynchronously and TaskFactory.StartNew")


def test_CoreRunSynchronouslyTest() -> None:
    _unsupported("Task.RunSynchronously and TaskScheduler selection")


def test_CoreRunSynchronouslyTest_NegativeTests() -> None:
    _unsupported("Task.RunSynchronously, Task.Start, and invalid task-state transitions")


def test_RunTaskExceptionTest() -> None:
    """Adapted: preserve and re-raise the original exception from Task.result()."""
    good = Task.run(lambda: 42)
    assert good.result() == 42

    error = ValueError("foobomb")

    def fail() -> int:
        raise error

    failed = Task.run(fail)
    with pytest.raises(ValueError, match="foobomb") as caught:
        failed.result()
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
    winner = Task.when_any(tasks).result()
    assert winner is fast
    assert winner.result() == 100
    assert Task.when_any(Task.run(lambda: 7)).result().result() == 7


def test_RunTaskWaitAnyTests_Negative() -> None:
    with pytest.raises(ValueError):
        Task.when_any()
    with pytest.raises(TypeError):
        Task.when_any([object()])


def test_RunTaskWaitAllTests() -> None:
    """Adapted from WaitAll: when_all waits for all results and preserves input order."""
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    tasks = [Task.run(value_after, i, delay) for i, delay in [(1, 0.03), (2, 0.005), (3, 0.015)]]
    assert Task.when_all(tasks).result() == [1, 2, 3]


def test_RunLongRunningTaskTests() -> None:
    # This is computed such that this number of long-running tasks will result in a back-up
    # without some assistance from TaskScheduler.RunBlocking() or TaskCreationOptions.LongRunning.
    ntasks = (os.cpu_count() or 1) * 2

    mre = ManualResetEvent(False)  # could just use a bool?
    cde = _CountdownEvent(ntasks)  # to count the number of Tasks that successfully start
    tasks = []
    for _ in range(ntasks):
        def work() -> None:
            cde.signal()  # indicate that task has begun execution
            mre.wait_one()

        # Task.Factory.StartNew(..., CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default)
        tasks.append(Task.run(work, creation_options=TaskCreationOptions.LONG_RUNNING))

    waitSucceeded = cde.wait(5)
    if not waitSucceeded:
        pytest.fail(
            "RunLongRunningTaskTests - TaskCreationOptions.LongRunning:    > FAILED.  "
            f"Timed out waiting for tasks to start. CDE.CurrentCount: {cde.current_count}, "
            f"CDE.Initial Count: {ntasks}"
        )

    mre.set()
    Task.wait_all(tasks)


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
            pending.result()
        assert pending.done()
        assert pending.cancelled()

        completed = Task.run(lambda: 123)
        assert completed.result() == 123
        assert completed.done()
        assert not completed.cancelled()
    finally:
        source.dispose()


def test_RunTaskStatusTests_NegativeTests() -> None:
    """Adapted: faults and cancellation remain distinguishable through public APIs."""
    failed = Task.run(lambda: (_ for _ in ()).throw(ValueError("fault")))
    with pytest.raises(ValueError, match="fault"):
        failed.result()
    assert failed.done()
    assert not failed.cancelled()

    source = CancellationTokenSource()
    try:
        cancelled = Task.delay(60, token=source.token)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            cancelled.result()
        assert cancelled.done()
        assert cancelled.cancelled()
    finally:
        source.dispose()


def test_RunTaskWaitTest() -> None:
    # wait on non-exceptional task
    t = Task.run(lambda: None)
    t.wait()

    if not t.done():
        pytest.fail("RunTaskWaitTest:  > error: task reported back !IsCompleted")

    # wait on non-exceptional delay started task (new Task(...); t.Start()):
    # not ported, unstarted tasks are not part of the FlpIt API, by design.

    # wait on a task that has children (TaskCreationOptions.AttachedToParent):
    # not ported, FlpIt has no parent/child tasks; every task behaves like a .NET
    # Task.Run task, which denies child attachment.


def test_Wait_SingleThreaded() -> None:
    # Upstream: IsNotMultithreadingSupported. Every assertion but the last three holds on
    # a multithreaded runtime too; those three are commented out below.
    incompleteTask: Task[None] = TaskCompletionSource().task

    Task.completed_task.wait()
    assert Task.completed_task.wait(0)
    assert not incompleteTask.wait(0)
    assert not Task.wait_all([incompleteTask], timeout=0)
    assert Task.wait_any([incompleteTask], timeout=0) == -1

    assert not incompleteTask.wait(0.001)
    assert not Task.wait_all([incompleteTask], timeout=0.001)
    assert Task.wait_any([incompleteTask], timeout=0.001) == -1
    # Assert.Throws<PlatformNotSupportedException>(() => incompleteTask.Wait());
    # Assert.Throws<PlatformNotSupportedException>(() => Task.WaitAll([incompleteTask]));
    # Assert.Throws<PlatformNotSupportedException>(() => Task.WaitAny([incompleteTask]));
    # -> single-threaded runtimes only: on FlpIt these block forever, so they are not run.


def test_RunTaskWaitTest_NegativeTests() -> None:
    exceptionMsg = "myexception"

    # test exceptions
    task = Task.run(lambda: None)
    with pytest.raises(ArgumentOutOfRangeError):
        task.wait(-0.002)
    with pytest.raises(ArgumentOutOfRangeError):
        task.wait(timedelta(milliseconds=-2))
    with pytest.raises(ArgumentOutOfRangeError):
        task.wait(timedelta(milliseconds=4_294_967_295))  # uint.MaxValue

    # wait on a task that gets canceled
    cts = CancellationTokenSource()
    ct = cts.token

    taskStartedEvent = ManualResetEvent(False)

    def spin_until_canceled() -> None:
        taskStartedEvent.set()
        while not ct.is_cancellation_requested:
            pass
        raise OperationCanceledError(token=ct)  # acknowledge the request

    t: Task[None] = Task.run(spin_until_canceled, token=ct)

    taskStartedEvent.wait_one()  # make sure the task starts running before we set the CTS
    cts.cancel()

    try:
        t.wait()
        pytest.fail("RunTaskWaitTest:  > error: Wait on exceptional task show have thrown.")
    except Exception as e:
        if (
                not isinstance(e, AggregateError)
                or len(e.exceptions) != 1
                or not isinstance(e.exceptions[0], TaskCanceledError)
        ):
            pytest.fail("RunTaskWaitTest:  > error: Wait on exceptional task threw wrong exception.")

    # wait on a task that throws
    def throw() -> None:
        raise Exception(exceptionMsg)

    t = Task.run(throw)
    try:
        t.wait()
        pytest.fail("RunTaskWaitTest:  > error: Wait on exceptional task show have thrown.")
    except Exception as e:
        if (
                not isinstance(e, AggregateError)
                or len(e.exceptions) != 1
                or str(e.exceptions[0]) != exceptionMsg
        ):
            pytest.fail("RunTaskWaitTest:  > error: Wait on exceptional task threw wrong exception.")

    # wait on a task that has an exceptional child task (TaskCreationOptions.AttachedToParent):
    # not ported, FlpIt has no parent/child tasks; every task behaves like a .NET
    # Task.Run task, which denies child attachment.


def test_RunTaskRecursiveWaitTest() -> None:
    t2: Task[None] | None = None

    def outer() -> None:
        nonlocal t2
        t2 = Task.run(lambda: None)
        t2.wait()

    t = Task.run(outer)
    t.wait()

    if not t.done():
        pytest.fail("RunTaskRecursiveWaitTest:  > error: task reported back !t.IsCompleted")

    assert t2 is not None
    if not t2.done():
        pytest.fail("RunTaskRecursiveWaitTest:  > error: task reported back !t2.IsCompleted")

    # Second half (new Task(...) / t.Start()): not ported, unstarted tasks are not part
    # of the FlpIt API, by design. It repeats the first half with constructed tasks.


def test_RunTaskWaitTimeoutTest() -> None:
    mre = ManualResetEvent(False)
    t = Task.run(lambda: mre.wait_one())
    t.wait(0.1)

    if t.done():
        pytest.fail("RunTaskWaitTimeoutTest:  > error: task reported back IsCompleted")

    mre.set()
    t.wait()

    if not t.done():
        pytest.fail("RunTaskWaitTimeoutTest:  > error: task reported back !IsCompleted")


def test_RunTaskRecursiveWaitTimeoutTest() -> None:
    taskStartedMRE = ManualResetEvent(False)
    mre = ManualResetEvent(False)
    t2: Task[bool] | None = None

    def outer() -> None:
        nonlocal t2
        taskStartedMRE.set()
        t2 = Task.run(lambda: mre.wait_one())
        t2.wait()

    t = Task.run(outer)

    taskStartedMRE.wait_one()  # wait for the outer task to start executing
    t.wait(0.1)

    if t.done():
        pytest.fail("RunTaskRecursiveWaitTimeoutTest:  > error: task reported back t.IsCompleted")

    assert t2 is not None
    if t2.done():
        pytest.fail("RunTaskRecursiveWaitTimeoutTest:  > error: task reported back t2.IsCompleted")

    mre.set()
    t.wait()

    if not t.done():
        pytest.fail("RunTaskRecursiveWaitTimeoutTest:  > error: task reported back !t.IsCompleted")

    if not t2.done():
        pytest.fail("RunTaskRecursiveWaitTimeoutTest:  > error: task reported back !t2.IsCompleted")

    # Second half (new Task(...) / t.Start()): not ported, unstarted tasks are not part
    # of the FlpIt API, by design. It repeats the first half with constructed tasks.


def test_RunTaskCanceledExceptionTests() -> None:
    tce: TaskCanceledError

    # Test empty constructor
    tce = TaskCanceledError()
    assert tce.task is None  # "Expected null Task prop after empty ctor"
    assert tce.inner_exception is None  # "Expected null InnerException prop after empty ctor"

    message = "my exception message"
    tce = TaskCanceledError(message)
    assert str(tce) == message, "RunTaskCanceledExceptionTests:  Message != string passed to ctor(string)"
    assert tce.task is None  # "Expected null Task prop after ctor(string)"
    assert tce.inner_exception is None  # "Expected null InnerException prop after ctor(string)"

    t1 = Task.run(lambda: None)
    tce = TaskCanceledError(t1)
    assert tce.task is t1, "RunTaskCanceledExceptionTests:  Task != task passed to ctor(Task)"
    assert tce.inner_exception is None  # "Expected null InnerException prop after ctor(Task)"

    ioe = InvalidOperationError()
    tce = TaskCanceledError(message, ioe)
    assert str(tce) == message, "RunTaskCanceledExceptionTests:  Message != string passed to ctor(string, exception)"
    assert tce.task is None  # "Expected null Task prop after ctor(string, exception)"
    assert tce.inner_exception is ioe, "RunTaskCanceledExceptionTests:  InnerException != exception passed to ctor(string, exception)"


def test_RunTaskSchedulerExceptionTests() -> None:
    _unsupported("TaskSchedulerException constructors; no matching FlpIt public exception")


def test_RunAsyncWaitHandleTests() -> None:
    _unsupported("IAsyncResult.AsyncWaitHandle; FlpIt exposes result(timeout), not a WaitHandle")
