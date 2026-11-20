"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's Task.continue_with: continuation options against every
antecedent outcome.

Test names and scenarios ported from:
- TaskContinueWith_ContFuncAndActionTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskContinueWith_ContFuncAndActionTests.cs

Every upstream test keeps its name with a ``test_`` prefix; helpers keep their upstream
names. The 16 test methods (one helper call per line) were translated mechanically.
``Wait()`` / ``AggregateException`` / ``TaskCanceledException`` are ``wait()`` /
``AggregateError`` / ``TaskCanceledError``. ``Task.Factory.StartNew`` is ``Task.run``;
upstream's ``Task`` vs ``Task<string>`` antecedents and ``Action`` vs ``Func<..., int>``
continuations are the same Python call, so the four helpers differ only in name, as upstream.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskCanceledError,
    TaskContinuationOptions,
)
from flpit.threading import ManualResetEvent

s_onlyOnRanToCompletion = TaskContinuationOptions.NOT_ON_CANCELED | TaskContinuationOptions.NOT_ON_FAULTED
s_onlyOnCanceled = TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION | TaskContinuationOptions.NOT_ON_FAULTED
s_onlyOnFaulted = TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION | TaskContinuationOptions.NOT_ON_CANCELED


# =============================================================================
# Test Methods (translated mechanically)
# =============================================================================

def test_RunContinueWithTestsNoState_NoneCompleted() -> None:
    RunContinueWithTaskTask(TaskContinuationOptions.NONE)
    RunContinueWithTaskTask(s_onlyOnRanToCompletion)
    RunContinueWithTaskTask(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskTask(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskToTaskWithResult_NoneCompleted() -> None:
    RunContinueWithTaskToTaskWithResult(TaskContinuationOptions.NONE)
    RunContinueWithTaskToTaskWithResult(s_onlyOnRanToCompletion)
    RunContinueWithTaskToTaskWithResult(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskToTaskWithResult(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTask_NoneCompleted() -> None:
    RunContinueWithTaskWithResultToTask(TaskContinuationOptions.NONE)
    RunContinueWithTaskWithResultToTask(s_onlyOnRanToCompletion)
    RunContinueWithTaskWithResultToTask(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTask(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTaskWithResult_NoneCompleted() -> None:
    RunContinueWithTaskWithResultToTaskWithResult(TaskContinuationOptions.NONE)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnRanToCompletion)
    RunContinueWithTaskWithResultToTaskWithResult(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTestsNoState_FaultedCanceled() -> None:
    RunContinueWithTaskTask(s_onlyOnCanceled)
    RunContinueWithTaskTask(s_onlyOnFaulted)
    RunContinueWithTaskTask(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskTask(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskToTaskWithResult_FaultedCanceled() -> None:
    RunContinueWithTaskToTaskWithResult(s_onlyOnCanceled)
    RunContinueWithTaskToTaskWithResult(s_onlyOnFaulted)
    RunContinueWithTaskToTaskWithResult(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskToTaskWithResult(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTask_FaultedCanceled() -> None:
    RunContinueWithTaskWithResultToTask(s_onlyOnCanceled)
    RunContinueWithTaskWithResultToTask(s_onlyOnFaulted)
    RunContinueWithTaskWithResultToTask(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTask(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTaskWithResult_FaultedCanceled() -> None:
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnCanceled)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnFaulted)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTestsNoState_NoneCompleted_OnException() -> None:
    RunContinueWithTaskTask(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskTask(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskTask(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskTask(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskToTaskWithResult_NoneCompleted_OnException() -> None:
    RunContinueWithTaskToTaskWithResult(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskToTaskWithResult(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskToTaskWithResult(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskToTaskWithResult(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTask_NoneCompleted_OnException() -> None:
    RunContinueWithTaskWithResultToTask(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskWithResultToTask(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskWithResultToTask(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTask(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTaskWithResult_NoneCompleted_OnException() -> None:
    RunContinueWithTaskWithResultToTaskWithResult(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskWithResultToTaskWithResult(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTestsNoState_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskTask(s_onlyOnCanceled, True)
    RunContinueWithTaskTask(s_onlyOnFaulted, True)
    RunContinueWithTaskTask(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskTask(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskToTaskWithResult_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskToTaskWithResult(s_onlyOnCanceled, True)
    RunContinueWithTaskToTaskWithResult(s_onlyOnFaulted, True)
    RunContinueWithTaskToTaskWithResult(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskToTaskWithResult(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTask_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskWithResultToTask(s_onlyOnCanceled, True)
    RunContinueWithTaskWithResultToTask(s_onlyOnFaulted, True)
    RunContinueWithTaskWithResultToTask(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTask(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTaskWithResult_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnCanceled, True)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnFaulted, True)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTaskWithResult(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


class _Ran:
    def __init__(self) -> None:
        self.value = False


def _run_helper(options: TaskContinuationOptions, runNegativeCases: bool, taskHasResult: bool, result: Any) -> None:
    ran = _Ran()

    def initRan() -> None:
        ran.value = False

    def continuationMaker(t: Task[Any]) -> Task[Any]:
        def continuation(f: Task[Any]) -> Any:
            ran.value = True
            return result

        return t.continue_with(continuation, options=options)

    base = RunContinueWithBase_NegativeCases if runNegativeCases else RunContinueWithBase
    base(options, initRan, continuationMaker, lambda: ran.value, taskHasResult)


def RunContinueWithTaskTask(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task continuation to a Task."""
    _run_helper(options, runNegativeCases, False, None)


def RunContinueWithTaskToTaskWithResult(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task<T> continuation to a Task, with a Func<Task, T>."""
    _run_helper(options, runNegativeCases, False, 5)


def RunContinueWithTaskWithResultToTask(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task continuation to a Task<T>."""
    _run_helper(options, runNegativeCases, True, None)


def RunContinueWithTaskWithResultToTaskWithResult(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task<U> continuation to a Task<T>, with a Func<Task<T>, U>."""
    _run_helper(options, runNegativeCases, True, 5)


# =============================================================================
# Helper Methods
# =============================================================================

def _wait_for_cancel(cont: Task[Any]) -> bool:
    """``try { cont.Wait(); } catch (AggregateException ex) { if (ex.InnerExceptions[0] is TaskCanceledException) cancel = true; }``"""
    try:
        cont.wait()
    except AggregateError as ex:
        if isinstance(ex.exceptions[0], TaskCanceledError):
            return True
    return False


def _check(expect: bool, ranValue: Callable[[], bool], cancel: bool) -> None:
    if expect != ranValue() or expect == cancel:
        pytest.fail(
            "RunContinueWithBase: >> Failed: continuation didn't run or get canceled when expected: "
            f"ran = {ranValue()}, cancel = {cancel}"
        )


def RunContinueWithBase(
        options: TaskContinuationOptions,
        initRan: Callable[[], None],
        continuationMaker: Callable[[Task[Any]], Task[Any]],
        ranValue: Callable[[], bool],
        taskHasResult: bool,
) -> None:
    """Base logic for RunContinueWithXXXYYY() methods."""
    # (1) ContinueWith after task finishes Successfully.
    expect = (options & TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION) == 0
    task: Task[Any] = Task.run(lambda: "") if taskHasResult else Task.run(lambda: None)
    task.wait()
    initRan()
    cont = continuationMaker(task)
    _check(expect, ranValue, _wait_for_cancel(cont))

    # (2) ContinueWith before task finishes Successfully.
    expect = (options & TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION) == 0
    mre = ManualResetEvent(False)

    def wait_then_return() -> str | None:
        mre.wait_one()
        return "" if taskHasResult else None

    task = Task.run(wait_then_return)
    initRan()
    cont = continuationMaker(task)
    mre.set()
    task.wait()
    _check(expect, ranValue, _wait_for_cancel(cont))


def _boom() -> None:
    raise Exception("Boom")


def RunContinueWithBase_NegativeCases(
        options: TaskContinuationOptions,
        initRan: Callable[[], None],
        continuationMaker: Callable[[Task[Any]], Task[Any]],
        ranValue: Callable[[], bool],
        taskHasResult: bool,
) -> None:
    """Base logic for RunContinueWithXXXYYY() methods."""
    # (Task<string> and Task behave the same for these cases; taskHasResult only picks the delegate type upstream.)
    # (3) ContinueWith after task finishes Exceptionally.
    expect = (options & TaskContinuationOptions.NOT_ON_FAULTED) == 0
    task: Task[Any] = Task.run(_boom)
    try:
        task.wait()
    except AggregateError:
        pass  # swallow(ouch)
    initRan()
    cont = continuationMaker(task)
    _check(expect, ranValue, _wait_for_cancel(cont))

    # (4) ContinueWith before task finishes Exceptionally.
    expect = (options & TaskContinuationOptions.NOT_ON_FAULTED) == 0
    mre = ManualResetEvent(False)

    def wait_then_boom() -> None:
        mre.wait_one()
        _boom()

    task = Task.run(wait_then_boom)
    initRan()
    cont = continuationMaker(task)
    mre.set()
    try:
        task.wait()
    except AggregateError:
        pass  # swallow(ouch)
    _check(expect, ranValue, _wait_for_cancel(cont))

    # (5) ContinueWith after task becomes Aborted.
    expect = (options & TaskContinuationOptions.NOT_ON_CANCELED) == 0
    # Create a task that will transition into Canceled state
    cts = CancellationTokenSource()
    cancellationMRE = ManualResetEvent(False)

    def wait_then_cancel() -> None:
        cancellationMRE.wait_one()
        raise OperationCanceledError(token=cts.token)

    task = Task.run(wait_then_cancel, token=cts.token)
    cts.cancel()
    cancellationMRE.set()
    initRan()
    cont = continuationMaker(task)
    _check(expect, ranValue, _wait_for_cancel(cont))

    # (6) ContinueWith before task becomes Aborted.
    expect = (options & TaskContinuationOptions.NOT_ON_CANCELED) == 0
    # Create a task that will transition into Canceled state
    cts = CancellationTokenSource()
    ct = cts.token
    cancellationMRE = ManualResetEvent(False)

    def wait_then_cancel_ct() -> None:
        cancellationMRE.wait_one()
        raise OperationCanceledError(token=ct)

    task = Task.run(wait_then_cancel_ct, token=ct)
    initRan()
    cont = continuationMaker(task)
    cts.cancel()
    cancellationMRE.set()
    _check(expect, ranValue, _wait_for_cancel(cont))
