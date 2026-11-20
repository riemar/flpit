"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's Task.continue_with: continuation options against every
antecedent outcome, with a state argument (``continue_with(fn, state)``).

Test names and scenarios ported from:
- TaskContinueWith_ContFuncAndActionWithArgsTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskContinueWith_ContFuncAndActionWithArgsTests.cs

Every upstream test keeps its name with a ``test_`` prefix; helpers keep their upstream
names. The 16 option-matrix test methods (one helper call per line) were translated mechanically;
the other five are ported by hand. ``new Task(...)`` + ``Start()`` antecedents use
``ColdTask`` (FlpIt has no unstarted tasks, by design; see task_helpers.py).
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

from nettests.task.task_helpers import ColdTask, EnsureExceptionIsAEofTCE

s_onlyOnRanToCompletion = TaskContinuationOptions.NOT_ON_CANCELED | TaskContinuationOptions.NOT_ON_FAULTED
s_onlyOnCanceled = TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION | TaskContinuationOptions.NOT_ON_FAULTED
s_onlyOnFaulted = TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION | TaskContinuationOptions.NOT_ON_CANCELED


# =============================================================================
# Test Methods (translated mechanically)
# =============================================================================

def test_RunContinueWithTaskTask_State() -> None:
    RunContinueWithTaskTask_State_Helper(TaskContinuationOptions.NONE)
    RunContinueWithTaskTask_State_Helper(s_onlyOnRanToCompletion)
    RunContinueWithTaskTask_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskTask_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskToTaskWithResult_State() -> None:
    RunContinueWithTaskToTaskWithResult_State_Helper(TaskContinuationOptions.NONE)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnRanToCompletion)
    RunContinueWithTaskToTaskWithResult_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTask_State() -> None:
    RunContinueWithTaskWithResultToTask_State_Helper(TaskContinuationOptions.NONE)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnRanToCompletion)
    RunContinueWithTaskWithResultToTask_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTaskWithResult_State() -> None:
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(TaskContinuationOptions.NONE)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnRanToCompletion)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskTask_State_FaultedCanceled() -> None:
    RunContinueWithTaskTask_State_Helper(s_onlyOnCanceled)
    RunContinueWithTaskTask_State_Helper(s_onlyOnFaulted)
    RunContinueWithTaskTask_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskTask_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskToTaskWithResult_State_FaultedCanceled() -> None:
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnCanceled)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnFaulted)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTask_State_FaultedCanceled() -> None:
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnCanceled)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnFaulted)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskWithResultToTaskWithResult_State_FaultedCanceled() -> None:
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnCanceled)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnFaulted)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)


def test_RunContinueWithTaskTask_State_OnException() -> None:
    RunContinueWithTaskTask_State_Helper(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskTask_State_Helper(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskTask_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskTask_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskToTaskWithResult_State_OnException() -> None:
    RunContinueWithTaskToTaskWithResult_State_Helper(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTask_State_OnException() -> None:
    RunContinueWithTaskWithResultToTask_State_Helper(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskWithResultToTask_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTaskWithResult_State_OnException() -> None:
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(TaskContinuationOptions.NONE, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnRanToCompletion, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnRanToCompletion | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskTask_State_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskTask_State_Helper(s_onlyOnCanceled, True)
    RunContinueWithTaskTask_State_Helper(s_onlyOnFaulted, True)
    RunContinueWithTaskTask_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskTask_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskToTaskWithResult_State_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnCanceled, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnFaulted, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskToTaskWithResult_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTask_State_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnCanceled, True)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnFaulted, True)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTask_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


def test_RunContinueWithTaskWithResultToTaskWithResult_State_FaultedCanceled_OnException() -> None:
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnCanceled, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnFaulted, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnCanceled | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)
    RunContinueWithTaskWithResultToTaskWithResult_State_Helper(s_onlyOnFaulted | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY, True)


# =============================================================================
# Test Methods (ported by hand)
# =============================================================================

def test_RunContinueWithPreCancelTests_State() -> None:
    def EnsureCompletionStatus(task: Task[Any], shouldBeCompleted: bool, message: str) -> None:
        if task.done() != shouldBeCompleted:
            pytest.fail(f"RunContinueWithPreCancelTests_State: > FAILED.  {message}.")

    cts = CancellationTokenSource()
    cts.cancel()
    mres = ManualResetEvent(False)
    # Pre-increment the dontCounts for pre-canceled continuations to make final check easier
    # (i.e., all counts should be 1 at end).
    doneCount = [0, 0, 1, 0, 1, 0]
    stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true

    def bump(index: int, wait: bool) -> Callable[..., None]:
        def action(*_: Any) -> None:
            if wait:
                mres.wait_one()
            doneCount[index] += 1
        return action

    t1 = ColdTask(bump(0, False))
    c1 = t1.task.continue_with(bump(1, False), stateParam)
    c2 = c1.continue_with(bump(2, True), stateParam, token=cts.token)
    c3 = c2.continue_with(bump(3, True), stateParam)
    c4 = c3.continue_with(bump(4, True), stateParam, token=cts.token,
                          options=TaskContinuationOptions.LAZY_CANCELLATION)
    c5 = c4.continue_with(bump(5, True), stateParam)

    EnsureCompletionStatus(c2, True, "  c2 should have completed (canceled) upon construction")
    EnsureCompletionStatus(c4, False, "  c4 should NOT have completed (canceled) upon construction")
    EnsureCompletionStatus(t1.task, False, "  t1 should NOT have completed before being started")
    EnsureCompletionStatus(c1, False, "  c1 should NOT have completed before antecedent completed")
    EnsureCompletionStatus(c3, False, "  c3 should NOT have completed before mres was set")
    EnsureCompletionStatus(c5, False, "  c5 should NOT have completed before mres was set")

    # These should be done already.  And Faulted.
    exception: Exception | None = None
    try:
        c2.wait()
        pytest.fail("RunContinueWithPreCancelTests_State:  Expected c2.Wait to throw AE/TCE")
    except Exception as ex:
        exception = ex
    EnsureExceptionIsAEofTCE(exception, "RunContinueWithPreCancelTests_State:  Expected c2.Wait to throw AE/TCE")

    mres.set()
    c3.wait()

    try:
        c4.wait()
        pytest.fail("RunContinueWithPreCancelTests_State:  Expected c4.Wait to throw AE/TCE")
    except Exception as ex:
        exception = ex
    EnsureExceptionIsAEofTCE(exception, "RunContinueWithPreCancelTests_State:  Expected c4.Wait to throw AE/TCE")
    c5.wait()

    EnsureCompletionStatus(t1.task, False, " t1 should NOT have completed (post-mres.Set()) before being started")
    EnsureCompletionStatus(c1, False, " c1 should NOT have completed (post-mres.Set()) before antecedent completed")

    t1.start()
    c1.wait()

    for i in range(6):
        if doneCount[i] != 1:
            pytest.fail(f"RunContinueWithPreCancelTests_State: > FAILED.  doneCount[{i}] should be 1, is {doneCount[i]}")


@pytest.mark.skip(reason="needs Task.Unwrap(), which is not part of FlpIt's continue_with support")
def test_RunContinuationChainingTest_State() -> None:
    pass


def test_RunContinueWithOnDisposedTaskTest_State() -> None:
    t1 = Task.run(lambda: None)
    t1.wait()
    # t1.Dispose();

    try:
        stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true
        t1.continue_with(lambda completedTask, obj: None, stateParam)
    except Exception:
        pytest.fail("RunContinueWithOnDisposedTaskTest_State:    > FAILED!  should NOT have seen an exception.")


def test_RunContinueWithParamsTest_State_Cancellation() -> None:
    stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true

    #
    # Test whether parentage/cancellation is working correctly
    #
    c1b: Task[None] | None = None
    c1c: Task[None] | None = None
    c2b: Task[None] | None = None
    c2c: Task[None] | None = None
    attached = TaskContinuationOptions.ATTACHED_TO_PARENT

    def body() -> None:
        nonlocal c1b, c1c, c2b, c2c
        cts = CancellationTokenSource()
        child1 = ColdTask(lambda: None, cts.token)  # TaskCreationOptions.AttachedToParent
        child2 = ColdTask(lambda: None)  # TaskCreationOptions.AttachedToParent

        c1b = child1.task.continue_with(lambda _, obj: None, stateParam,
                                        options=TaskContinuationOptions.NOT_ON_CANCELED | attached)
        c1c = child1.task.continue_with(lambda _, obj: None, stateParam, options=attached)

        c2b = child2.task.continue_with(lambda _, obj: None, stateParam,
                                        options=TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION | attached)
        c2c = child2.task.continue_with(lambda _, obj: None, stateParam, options=attached)

        cts.cancel()  # should cancel the unstarted child task
        child2.start()

    container = ColdTask(body)
    container.start()
    try:
        container.task.wait()
    except Exception:
        pass
    assert c1b is not None and c1c is not None and c2b is not None and c2c is not None

    # In .NET, container.Wait() also waits for its AttachedToParent children (here: the
    # continuations). FlpIt has no parent/child tasks, so the test waits for them itself.
    try:
        Task.wait_all(c1b, c1c, c2b, c2c)
    except AggregateError:
        pass

    if c1b.status != Task.CANCELLED:
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Continuation task w/NotOnCanceled should have been canceled when antecedent was canceled.")
    if c1c.status != Task.SUCCEEDED:
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Continuation task w/ canceled antecedent should have run to completion.")
    if c2b.status != Task.CANCELLED:
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Continuation task w/NotOnRanToCompletion should have been canceled when antecedent completed.")
    c2c.wait()
    if c2c.status != Task.SUCCEEDED:
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Continuation task w/ completed antecedent should have run to completion.")


def test_RunContinueWithParamsTest_State_IllegalParameters() -> None:
    t1 = ColdTask(lambda: None)
    stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true

    try:
        t1.task.continue_with(lambda ooo, obj: None, stateParam, options=TaskContinuationOptions(0x1000000))
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Should have seen exception from illegal continuation options.")
    except Exception:  # catch { }; pytest.fail() raises a BaseException, so it is not swallowed here
        pass

    try:
        t1.task.continue_with(lambda ooo, obj: None, stateParam,
                              options=TaskContinuationOptions.LONG_RUNNING | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Should have seen exception when combining LongRunning and ExecuteSynchronously")
    except Exception:  # catch { }; pytest.fail() raises a BaseException, so it is not swallowed here
        pass

    try:
        t1.task.continue_with(lambda ooo, obj: None, stateParam,
                              options=TaskContinuationOptions.NOT_ON_RAN_TO_COMPLETION
                              | TaskContinuationOptions.NOT_ON_FAULTED
                              | TaskContinuationOptions.NOT_ON_CANCELED)
        pytest.fail("RunContinueWithParamsTest_State    > FAILED.  Should have seen exception from illegal NotOnAny continuation options.")
    except Exception:  # catch { }; pytest.fail() raises a BaseException, so it is not swallowed here
        pass

    t1.start()
    t1.task.wait()


# =============================================================================
# Helper Methods
# =============================================================================

class _Ran:
    def __init__(self) -> None:
        self.value = False


def _run_helper(options: TaskContinuationOptions, runNegativeCases: bool, taskHasResult: bool, result: Any) -> None:
    ran = _Ran()
    stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true

    def initRan() -> None:
        ran.value = False

    def continuationMaker(t: Task[Any]) -> Task[Any]:
        def continuation(f: Task[Any], obj: object) -> Any:
            ran.value = True
            return result

        return t.continue_with(continuation, stateParam, options=options)

    base = RunContinueWithBase_ExceptionCases if runNegativeCases else RunContinueWithBase
    base(options, initRan, continuationMaker, lambda: ran.value, taskHasResult)


def RunContinueWithTaskTask_State_Helper(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task continuation to a Task."""
    _run_helper(options, runNegativeCases, False, None)


def RunContinueWithTaskToTaskWithResult_State_Helper(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task<T> continuation to a Task, with a Func<Task, T>."""
    _run_helper(options, runNegativeCases, False, 5)


def RunContinueWithTaskWithResultToTask_State_Helper(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
    """Chains a Task continuation to a Task<T>."""
    _run_helper(options, runNegativeCases, True, None)


def RunContinueWithTaskWithResultToTaskWithResult_State_Helper(options: TaskContinuationOptions, runNegativeCases: bool = False) -> None:
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


def RunContinueWithBase_ExceptionCases(
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
