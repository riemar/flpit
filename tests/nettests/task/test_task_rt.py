"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of tests from current dotnet/runtime TaskRtTests.cs.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskRtTests.cs

Every public test method in that C# file is represented below. The original
PascalCase method names are preserved with a ``test_`` prefix. Unsupported .NET
semantics remain visible as explicit skips; adaptations are documented inline.
"""
from __future__ import annotations

import pytest

from datetime import timedelta
from typing import Any

from flpit.core.linq import ArgumentNullError, ArgumentOutOfRangeError, InvalidOperationError
from flpit.task import (
    AggregateError,
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskContinuationOptions,
)
from flpit.threading import ThreadLocal


# Task.Delay's contract that FlpIt's Task.delay does not follow yet: TimeSpan (timedelta) overloads, -1 for an
# infinite delay, and ArgumentOutOfRangeException below -1 ms or above uint.MaxValue - 2 ms (FlpIt raises
# ValueError for a negative delay). Strict: the marker fails as soon as Task.delay is aligned.
_DELAY_CONTRACT = pytest.mark.xfail(
    strict=True, reason="Task.delay: no timedelta overloads, no -1 = infinite, ValueError instead of .NET's bounds")
_UINT_MAX = 4_294_967_295
_INT_MIN = -2_147_483_648


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


def test_RunRunTests() -> None:
    # Not ported: "AttachedToParent is ignored in Task.Run delegate", which creates cold tasks with
    # new Task(..., AttachedToParent) inside Task.Run and starts them afterwards. FlpIt has neither cold tasks
    # nor attached children (every task is like a .NET Task.Run task).

    # Test basic functionality w/o cancellation token
    count = 0

    def set_count(value: int) -> None:
        nonlocal count
        count = value

    task1 = Task.run(set_count, 1)
    task1.wait()
    assert count == 1, "    > FAILED.  Task completed but did not run."
    assert task1.status == Task.SUCCEEDED, "    > FAILED.  Task did not end in RanToCompletion state."

    task_with_result1 = Task.run(lambda: 7)
    task_with_result1.wait()
    assert task_with_result1.result() == 7, "    > FAILED.  Task<int> completed but did not run."
    assert task_with_result1.status == Task.SUCCEEDED, "    > FAILED.  Task<int> did not end in RanToCompletion state."

    # Task.Run(Func<Task>) unwraps: the returned task completes with the inner one.
    task1 = Task.run(lambda: Task.run(set_count, 11))
    task1.wait()
    assert count == 11, "    > FAILED.  Task(unwrapped) completed but did not run."
    assert task1.status == Task.SUCCEEDED, "    > FAILED.  Task(unwrapped) did not end in RanToCompletion state."

    task_with_result1 = Task.run(lambda: Task.run(lambda: 17))
    task_with_result1.wait()
    assert task_with_result1.result() == 17, "    > FAILED.  Task<int>(unwrapped) completed but did not run."
    assert task_with_result1.status == Task.SUCCEEDED, (
        "    > FAILED.  Task<int>(unwrapped) did not end in RanToCompletion state.")

    # Test basic functionality w/ uncancelled cancellation token
    cts = CancellationTokenSource()
    token = cts.token
    task2 = Task.run(set_count, 21, token=token)
    task2.wait()
    assert count == 21, "    > FAILED.  Task w/ uncanceled token completed but did not run."
    assert task2.status == Task.SUCCEEDED, "    > FAILED.  Task w/ uncanceled token did not end in RanToCompletion state."

    task_with_result2 = Task.run(lambda: 27, token=token)
    task_with_result2.wait()
    assert task_with_result2.result() == 27, "    > FAILED.  Task<int> w/ uncanceled token completed but did not run."
    assert task_with_result2.status == Task.SUCCEEDED, (
        "    > FAILED.  Task<int> w/ uncanceled token did not end in RanToCompletion state.")

    task2 = Task.run(lambda: Task.run(set_count, 31), token=token)
    task2.wait()
    assert count == 31, "    > FAILED.  Task(unwrapped) w/ uncanceled token completed but did not run."
    assert task2.status == Task.SUCCEEDED, (
        "    > FAILED.  Task(unwrapped) w/ uncanceled token did not end in RanToCompletion state.")

    task_with_result2 = Task.run(lambda: Task.run(lambda: 37), token=token)
    task_with_result2.wait()
    assert task_with_result2.result() == 37, (
        "    > FAILED.  Task<int>(unwrapped) w/ uncanceled token completed but did not run.")
    assert task_with_result2.status == Task.SUCCEEDED, (
        "    > FAILED.  Task<int>(unwrapped) w/ uncanceled token did not end in RanToCompletion state.")


def test_RunRunTests_Cancellation_Negative() -> None:
    cts = CancellationTokenSource()
    token = cts.token
    count = 0

    def set_count(value: int) -> int:
        nonlocal count
        count = value
        return count

    cts.cancel()
    variants = {
        41: ("Task", lambda: Task.run(set_count, 41, token=token)),
        47: ("Task<int>", lambda: Task.run(set_count, 47, token=token)),
        51: ("Task(unwrapped)", lambda: Task.run(lambda: Task.run(set_count, 51), token=token)),
        57: ("Task<int>(unwrapped)", lambda: Task.run(lambda: Task.run(set_count, 57), token=token)),
    }
    for value, (label, start) in variants.items():
        task3 = start()
        with pytest.raises(AggregateError):
            task3.wait()
        assert count != value, f"    > FAILED.  {label} w/ canceled token ran when it should not have."
        assert task3.cancelled(), f"    > FAILED.  {label} w/ canceled token should have ended in Canceled state"


def test_RunRunTests_FastPathTests() -> None:
    # Task.Run(() => existingTask) returns a proxy for an already completed, faulted or canceled task.
    cts = CancellationTokenSource()
    cts.cancel()

    def faulted() -> int:
        raise Exception("FAULTED!")

    for kind, value in (("Task", None), ("Task<TResult>", 42)):
        already_completed_task = Task.run(lambda: value)
        already_completed_task.wait()
        already_faulted_task = Task.run(faulted)
        try:
            already_faulted_task.wait()
        except Exception:  # noqa: BLE001, S110
            pass
        already_canceled_task = Task.run(lambda: value, token=cts.token)  # should result in cancellation
        try:
            already_canceled_task.wait()
        except Exception:  # noqa: BLE001, S110
            pass

        fast_path1 = Task.run(lambda: already_completed_task)
        fast_path1.wait()
        assert fast_path1.status == Task.SUCCEEDED, (
            f"Expected proxy for already-ran-to-completion {kind} to be in RanToCompletion status")
        assert fast_path1.result() == value

        fast_path1 = Task.run(lambda: already_faulted_task)
        with pytest.raises(Exception):  # noqa: B017 - Expected proxy for already-faulted task to throw on Wait()
            fast_path1.wait()
        assert fast_path1.status == Task.FAILED, f"Expected proxy for already-faulted {kind} to be in Faulted status"

        fast_path1 = Task.run(lambda: already_canceled_task)
        with pytest.raises(Exception):  # noqa: B017 - Expected proxy for already-canceled task to throw on Wait()
            fast_path1.wait()
        assert fast_path1.status == Task.CANCELLED, f"Expected proxy for already-canceled {kind} to be in Canceled status"


def test_RunRunTests_Unwrap_NegativeCases() -> None:
    _unsupported("Task.Run(Func<Task>) automatic unwrapping of a Task returned by a synchronous delegate")


def test_RunFromResult() -> None:
    # Test FromResult with value type
    results: list[Any] = [-1, 0, 1, 42, 2_147_483_647, -2_147_483_648, 42, -42]  # includes duplicate values to ensure that tasks from these aren't the same object
    tasks = [Task.from_result(r) for r in results]

    # Make sure they've all completed
    for i, task in enumerate(tasks):
        assert task.done(), f"TaskRtTests.RunFromResult:    > FAILED: Task {i} should have already completed (value)"

    # Make sure they all completed successfully
    for i, task in enumerate(tasks):
        assert task.status == Task.SUCCEEDED, (
            f"TaskRtTests.RunFromResult:    > FAILED: Task {i} should have already completed successfully (value)")

    # Make sure no two are the same instance
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            assert tasks[i] is not tasks[j], (
                f"TaskRtTests.RunFromResult:    > FAILED: {i} and {j} created tasks should not be equal (value)")

    # Make sure they all have the correct results
    for i, task in enumerate(tasks):
        assert task.result() == results[i], (
            f"TaskRtTests.RunFromResult:    > FAILED: Task {i} had the result {task.result()} but should have had "
            f"{results[i]} (value)")

    # Test FromResult with reference type
    ref_results: list[object | None] = [object(), object(), None, object()]
    ref_tasks = [Task.from_result(r) for r in ref_results]

    for i, task in enumerate(ref_tasks):
        assert task.done(), f"TaskRtTests.RunFromResult:    > FAILED: Task {i} should have already completed  (ref)"
    for i, task in enumerate(ref_tasks):
        assert task.status == Task.SUCCEEDED, (
            f"TaskRtTests.RunFromResult:    > FAILED: Task {i} should have already completed successfully (ref)")
    for i in range(len(ref_tasks)):
        for j in range(i + 1, len(ref_tasks)):
            assert ref_tasks[i] is not ref_tasks[j], (
                f"TaskRtTests.RunFromResult:    > FAILED: {i} and {j} created tasks should not be equal (ref)")
    for i, task in enumerate(ref_tasks):
        assert task.result() is ref_results[i], f"TaskRtTests.RunFromResult:    > FAILED: Task {i} had the wrong result (ref)"

    # Test FromException
    exceptions: list[Exception] = [InvalidOperationError(), OperationCanceledError(), Exception(), Exception()]  # includes duplicate values to ensure that tasks from these aren't the same object
    ex_tasks = [Task.from_exception(e) for e in exceptions]

    # Make sure they've all completed
    for i, task in enumerate(ex_tasks):
        assert task.done(), f"Task {i} should have already completed"

    # Make sure they all completed with an error
    for i, task in enumerate(ex_tasks):
        assert task.status == Task.FAILED, f"    > FAILED: Task {i} should have already faulted"

    # Make sure no two are the same instance
    for i in range(len(ex_tasks)):
        for j in range(i + 1, len(ex_tasks)):
            assert ex_tasks[i] is not ex_tasks[j], f"    > FAILED: {i} and {j} created tasks should not be equal"

    # Make sure they all have the correct exceptions
    for i, task in enumerate(ex_tasks):
        exception = task.exception()
        assert exception is not None
        assert isinstance(exception, AggregateError)
        assert len(exception.exceptions) == 1
        assert exception.exceptions[0] is exceptions[i]

    # Make sure we handle invalid exceptions correctly
    with pytest.raises(ArgumentNullError):
        Task.from_exception(None)  # type: ignore[arg-type]

    # Make sure we throw from waiting on a faulted task.
    # .NET's .Result raises AggregateException; FlpIt's result() is GetAwaiter().GetResult() and raises the
    # failure itself (docs/task/exceptions.md). wait() is the AggregateError form.
    with pytest.raises(InvalidOperationError):
        Task.from_exception(InvalidOperationError()).result()
    with pytest.raises(AggregateError):
        Task.from_exception(InvalidOperationError()).wait()


def test_FromResult_KnownResults_Cached() -> None:
    # Task.FromResult caches some known values (bool, -1..8, default(T)) "as an implementation detail", the
    # original says. FlpIt's from_result returns a new task every time.
    _unsupported("Task.FromResult result caching, an implementation detail of .NET")


def test_RunFromResult_FaultedTask() -> None:
    _unsupported("the internal TaskExceptionHolder 'observed' flag, read via reflection")


@_DELAY_CONTRACT
@pytest.mark.parametrize("delay", [-2, _INT_MIN, _UINT_MAX])
def test_TaskDelay_OutOfBounds_ThrowsException(delay: int) -> None:
    with pytest.raises(ArgumentOutOfRangeError, match="delay"):
        Task.delay(timedelta(milliseconds=delay))  # type: ignore[arg-type]
    if _INT_MIN <= delay <= 2_147_483_647:
        with pytest.raises(ArgumentOutOfRangeError):
            Task.delay(delay / 1000)  # Task.Delay((int)delay): FlpIt takes seconds


@_DELAY_CONTRACT
def test_TaskDelay_MaxSupported_Success() -> None:
    cts = CancellationTokenSource()
    t = Task.delay(timedelta(milliseconds=_UINT_MAX - 2), token=cts.token)  # type: ignore[arg-type]
    assert not t.done()
    cts.cancel()
    assert t.cancelled()


@_DELAY_CONTRACT
def test_RunDelayTests() -> None:
    cts = CancellationTokenSource()
    token = cts.token
    task1 = Task.delay(0)
    task2 = Task.delay(timedelta(0))  # type: ignore[arg-type]
    task3 = Task.delay(0, token=token)
    task4 = Task.delay(timedelta(0), token=token)  # type: ignore[arg-type]
    Task.wait_all(task1, task2, task3, task4)  # an unexpected exception fails the test
    assert task1.status == Task.SUCCEEDED, "    > FAILED.  Expected Delay(0) to run to completion"
    assert task2.status == Task.SUCCEEDED, "    > FAILED.  Expected Delay(TimeSpan(0)) to run to completion"
    assert task3.status == Task.SUCCEEDED, "    > FAILED.  Expected Delay(0,uncanceledToken) to run to completion"
    assert task4.status == Task.SUCCEEDED, "    > FAILED.  Expected Delay(TimeSpan(0),uncanceledToken) to run to completion"
    task7 = Task.delay(10)
    assert not task7.done(), "RunDelayTests:    > FAILED.  Delay(10000) appears to have completed too soon(1)."
    Task.delay(0.01)
    assert not task7.done(), "RunDelayTests:    > FAILED.  Delay(10000) appears to have completed too soon(2)."


def test_FlpIt_RunDelayTests_Seconds() -> None:
    """RunDelayTests with the overloads FlpIt has (seconds): keeps running while the TimeSpan ones are xfail."""
    cts = CancellationTokenSource()
    task1 = Task.delay(0)
    task3 = Task.delay(0, token=cts.token)
    Task.wait_all(task1, task3)
    assert task1.status == Task.SUCCEEDED and task3.status == Task.SUCCEEDED
    task7 = Task.delay(10)
    assert not task7.done()
    Task.delay(0.01)
    assert not task7.done()


@_DELAY_CONTRACT
def test_RunDelayTests_NegativeCases() -> None:
    disposed_cts = CancellationTokenSource()
    disposed_cts.dispose()

    with pytest.raises(ArgumentOutOfRangeError):
        Task.delay(-2 / 1000)  # Task.Delay(-2)
    with pytest.raises(ArgumentOutOfRangeError):
        Task.delay(timedelta(days=1000))  # type: ignore[arg-type]

    cts = CancellationTokenSource()
    token = cts.token
    cts.cancel()
    task5 = Task.delay(0, token=token)
    task6 = Task.delay(timedelta(0), token=token)  # type: ignore[arg-type]
    try:
        Task.wait_all(task5, task6)
    except Exception:  # noqa: BLE001, S110
        pass
    assert task5.status == Task.CANCELLED, "RunDelayTests:    > FAILED.  Expected Delay(0,canceledToken) to end up Canceled"
    assert task6.status == Task.CANCELLED, (
        "RunDelayTests:    > FAILED.  Expected Delay(TimeSpan(0),canceledToken) to end up Canceled")

    cts2 = CancellationTokenSource()
    task8 = Task.delay(-1, token=cts2.token)  # infinite
    task9 = Task.delay(timedelta(days=1), token=cts2.token)  # type: ignore[arg-type]
    Task.run(cts2.cancel)
    try:
        Task.wait_all(task8, task9)
    except Exception:  # noqa: BLE001, S110
        pass
    assert task8.cancelled(), "RunDelayTests:    > FAILED.  Expected Delay(-1, token) to end up Canceled."
    assert task9.cancelled(), "RunDelayTests:    > FAILED.  Expected Delay(TimeSpan(1,0,0,0), token) to end up Canceled."
    with pytest.raises(AggregateError) as ae:
        task8.wait()
    inner = ae.value.exceptions[0]
    assert isinstance(inner, OperationCanceledError) and inner.token is cts2.token, (
        "RunDelayTests:    > FAILED.  Expected resulting OCE to contain canceled token.")


def test_TaskDelay_Cancellation_ContinuationsInvokedAsynchronously() -> None:
    cts = CancellationTokenSource()

    tl: ThreadLocal[int] = ThreadLocal(default=0)
    seen: list[int] = []
    # Task.Delay(-1, token): FlpIt's Task.delay has no infinite delay; an hour stands in.
    c = Task.delay(3600, token=cts.token).continue_with(
        lambda _: seen.append(tl.value),  # Assert.Equal(0, tl.Value), checked below
        options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY,
    )

    tl.value = 42
    cts.cancel()
    tl.value = 0

    c.result()  # c.GetAwaiter().GetResult()
    assert seen == [0]


def test_RunExceptionWrappingTest() -> None:
    # The original counts AggregateException nesting levels after Wait() for monadic ContinueWith(...).Unwrap()
    # and for Task.Factory.FromAsync: FlpIt has neither Unwrap() nor FromAsync.
    _unsupported("ContinueWith(...).Unwrap() and Task.Factory.FromAsync")


def test_RunHideSchedulerTests() -> None:
    _unsupported("TaskScheduler.Current, TaskCreationOptions.HideScheduler, and ContinueWith")


def test_RunHideSchedulerTests_Negative() -> None:
    _unsupported("TaskCompletionSource validation of TaskCreationOptions.HideScheduler")


def test_RunDenyChildAttachTests() -> None:
    _unsupported("AttachedToParent/DenyChildAttach task hierarchy semantics")


def test_RunBasicTaskWithResultTest_Negative() -> None:
    # new Task<int>(() => 1) is a cold task in .NET; any task serves for argument validation here.
    task_with_result = Task.run(lambda: 1)
    # ContinueWith(null, state, ...) in the CancellationToken / TaskContinuationOptions / both overloads:
    # FlpIt has one continue_with(continuation, state, *, token, options).
    with pytest.raises(ArgumentNullError):
        task_with_result.continue_with(None, None, token=CancellationToken.none())  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError):
        task_with_result.continue_with(None, None, options=TaskContinuationOptions.NONE)  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError):
        task_with_result.continue_with(  # type: ignore[arg-type]
            None, None, token=CancellationToken.none(), options=TaskContinuationOptions.NONE)
    # ContinueWith(..., (TaskScheduler)null): FlpIt has no task schedulers.
