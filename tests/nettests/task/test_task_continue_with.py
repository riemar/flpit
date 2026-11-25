"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's Task.continue_with.

Test names and scenarios ported from:
- TaskContinueWithTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskContinueWithTests.cs

Every upstream test keeps its name with a ``test_`` prefix; helpers keep their upstream
names. Mapping to FlpIt's Python API:

- ``t.ContinueWith(fn, [state,] token, options, TaskScheduler.Default)`` is
  ``t.continue_with(fn, [state,] token=token, options=options)``: FlpIt has no task
  schedulers, so the scheduler argument is dropped;
- ``new Task(action)`` + ``t.Start()`` antecedents use ``ColdTask`` (FlpIt has no unstarted
  tasks, by design; see task_helpers.py); ``Task.Factory.StartNew`` is ``Task.run``;
- ``Wait()`` / ``AggregateException`` / ``TaskCanceledException`` are ``wait()`` /
  ``AggregateError`` / ``TaskCanceledError``; ``Status`` / ``TaskStatus.RanToCompletion``
  are ``status`` / ``Task.SUCCEEDED``; ``CreationOptions`` is ``creation_options``.

Not ported: ``Unwrap()`` and ``TaskFactory.ContinueWhenAll/Any``, which are not part of
FlpIt's continue_with support. Tests built on them are skipped; tests that only loop
over them run their ``ContinueWith`` part.
"""
from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest

from flpit.core.linq import ArgumentNullError
from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    Task,
    TaskCanceledError,
    TaskCompletionSource,
    TaskContinuationOptions,
    TaskCreationOptions,
)
from flpit.threading import ManualResetEvent

from nettests.task.task_helpers import ColdTask, EnsureExceptionIsAEofTCE, EnsureTaskCanceledExceptionThrown

TCO = TaskContinuationOptions

_SKIP_UNWRAP = pytest.mark.skip(reason="needs Task.Unwrap(), which is not part of FlpIt's continue_with support")


# =============================================================================
# ContinueWith Tests
# =============================================================================

def test_RunContinueWithAsyncStateCheckTests() -> None:
    t = ColdTask(lambda: None)
    c1 = t.task.continue_with(lambda _: None)
    c2 = t.task.continue_with(lambda _: 42)

    f = ColdTask(lambda: 1)
    c3 = f.task.continue_with(lambda _: None)
    c4 = f.task.continue_with(lambda antecedent: antecedent.result())

    t.start()
    f.start()

    Task.wait_all(c1, c2, c3, c4)

    assert c1.async_state is None, "RunContinueWithAsyncStateCheckTests: Task=>Task continuation leaks state"
    assert c2.async_state is None, "RunContinueWithAsyncStateCheckTests: Task=>Task<TResult> continuation leaks state"
    assert c3.async_state is None, "RunContinueWithAsyncStateCheckTests: Task<TResult>=>Task continuation leaks state"
    assert c4.async_state is None, "RunContinueWithAsyncStateCheckTests: Task<TResult>=>Task<TResult> continuation leaks state"


# Stresses on multiple continuations from a single antecedent.
# Upstream: [SkipOnCoreClr("Stress test", ~RuntimeConfiguration.Release)], i.e. it only runs
# in release builds; here it is a "stress" test (run with -m stress).
@pytest.mark.stress
def test_RunContinueWithStressTestsNoState() -> None:
    numIterations = 3
    for iteration in range(numIterations):
        numToCancel = 5000 * (iteration + 1)
        numToComplete = 10000

        # All "leftover" continuations will be immediately scheduled.
        # All "cancel" continuations will be immediately canceled.
        ContinueWithTortureTest(numToCancel, numToComplete, completeAfter=0, cancelAfter=0)

        # Some "leftover" continuations will be queued when antecedent completes
        # All "cancel" continuations will be immediately canceled
        ContinueWithTortureTest(numToCancel, numToComplete, completeAfter=100, cancelAfter=0)

        # Some "leftover" continuations will be queued when antecedent completes
        # Some "cancel" continuations will be queued when the token is signaled
        ContinueWithTortureTest(numToCancel, numToComplete, completeAfter=1000, cancelAfter=100)

        # All "leftover" continuations should be queued when antecedent completes
        # There may or may not be leftover "cancel" continuations when the antecedent completes
        ContinueWithTortureTest(numToCancel, numToComplete, completeAfter=10000, cancelAfter=9900)

        # All continuations should be queued when antecedent completes
        ContinueWithTortureTest(numToCancel, numToComplete, completeAfter=10000, cancelAfter=10000)


def test_RunContinueWithPreCancelTests() -> None:
    def EnsureCompletionStatus(task: Task[Any], shouldBeCompleted: bool, message: str) -> None:
        if task.done() != shouldBeCompleted:
            pytest.fail(f"    > FAILED.  {message}.")

    cts = CancellationTokenSource()
    cts.cancel()
    mres = ManualResetEvent(False)
    # Pre-increment the dontCounts for pre-canceled continuations to make final check easier
    # (i.e., all counts should be 1 at end).
    doneCount = [0, 0, 1, 0, 1, 0]

    def bump(index: int, wait: bool) -> Any:
        def action(*_: Any) -> None:
            if wait:
                mres.wait_one()
            doneCount[index] += 1
        return action

    t1 = ColdTask(bump(0, False))
    c1 = t1.task.continue_with(bump(1, False))
    c2 = c1.continue_with(bump(2, True), token=cts.token)
    c3 = c2.continue_with(bump(3, True))

    c4 = c3.continue_with(bump(4, True), token=cts.token, options=TCO.LAZY_CANCELLATION)

    c5 = c4.continue_with(bump(5, True))
    EnsureCompletionStatus(c2, True, "RunContinueWithPreCancelTests: c2 should have completed (canceled) upon construction")
    EnsureCompletionStatus(c4, False, "RunContinueWithPreCancelTests: c4 should NOT have completed (canceled) upon construction")
    EnsureCompletionStatus(t1.task, False, "RunContinueWithPreCancelTests: t1 should NOT have completed before being started")
    EnsureCompletionStatus(c1, False, "RunContinueWithPreCancelTests: c1 should NOT have completed before antecedent completed")
    EnsureCompletionStatus(c3, False, "RunContinueWithPreCancelTests: c3 should NOT have completed before mres was set")
    EnsureCompletionStatus(c5, False, "RunContinueWithPreCancelTests: c5 should NOT have completed before mres was set")

    # These should be done already.  And Faulted.
    EnsureTaskCanceledExceptionThrown(lambda: c2.wait(), "RunContinueWithPreCancelTests: Expected c2.Wait to throw AE/TCE")

    mres.set()
    c3.wait()
    EnsureTaskCanceledExceptionThrown(lambda: c4.wait(), "RunContinueWithPreCancelTests: Expected c4.Wait to throw AE/TCE")
    c5.wait()

    EnsureCompletionStatus(t1.task, False, "RunContinueWithPreCancelTests: t1 should NOT have completed (post-mres.Set()) before being started")
    EnsureCompletionStatus(c1, False, "RunContinueWithPreCancelTests: c1 should NOT have completed (post-mres.Set()) before antecedent completed")

    t1.start()
    c1.wait()

    for i in range(6):
        if doneCount[i] != 1:
            pytest.fail(f"RunContinueWithPreCancelTests: > FAILED.  doneCount[{i}] should be 1, is {doneCount[i]}")


@_SKIP_UNWRAP
def test_RunContinuationChainingTest() -> None:
    pass


def test_RunContinueWithParamsTest_Cancellation() -> None:
    #
    # Test whether parentage/cancellation is working correctly
    #
    c1b: Task[None] | None = None
    c1c: Task[None] | None = None
    c2b: Task[None] | None = None
    c2c: Task[None] | None = None

    def body() -> None:
        nonlocal c1b, c1c, c2b, c2c
        cts = CancellationTokenSource()
        child1 = ColdTask(lambda: None, cts.token)  # TaskCreationOptions.AttachedToParent
        child2 = ColdTask(lambda: None)  # TaskCreationOptions.AttachedToParent

        c1b = child1.task.continue_with(lambda _: None, options=TCO.NOT_ON_CANCELED | TCO.ATTACHED_TO_PARENT)
        c1c = child1.task.continue_with(lambda _: None, options=TCO.ATTACHED_TO_PARENT)

        c2b = child2.task.continue_with(lambda _: None, options=TCO.NOT_ON_RAN_TO_COMPLETION | TCO.ATTACHED_TO_PARENT)
        c2c = child2.task.continue_with(lambda _: None, options=TCO.ATTACHED_TO_PARENT)

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
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Continuation task w/NotOnCanceled should have been canceled when antecedent was canceled.")
    if c1c.status != Task.SUCCEEDED:
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Continuation task w/ canceled antecedent should have run to completion.")
    if c2b.status != Task.CANCELLED:
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Continuation task w/NotOnRanToCompletion should have been canceled when antecedent completed.")
    c2c.wait()
    if c2c.status != Task.SUCCEEDED:
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Continuation task w/ completed antecedent should have run to completion.")


def test_RunContinueWithParamsTest_IllegalArgs() -> None:
    # Upstream's catch { } would also swallow Assert.Fail; pytest.fail() raises a
    # BaseException, so a missing validation error does fail this port.
    t1 = ColdTask(lambda: None)

    try:
        t1.task.continue_with(lambda ooo: None, options=TaskContinuationOptions(0x1000000))
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Should have seen exception from illegal continuation options.")
    except Exception:
        pass

    try:
        t1.task.continue_with(lambda ooo: None, options=TCO.LONG_RUNNING | TCO.EXECUTE_SYNCHRONOUSLY)
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Should have seen exception when combining LongRunning and ExecuteSynchronously")
    except Exception:
        pass

    try:
        t1.task.continue_with(
            lambda ooo: None,
            options=TCO.NOT_ON_RAN_TO_COMPLETION | TCO.NOT_ON_FAULTED | TCO.NOT_ON_CANCELED,
        )
        pytest.fail("RunContinueWithParamsTest: > FAILED.  Should have seen exception from illegal NotOnAny continuation options.")
    except Exception:
        pass

    t1.start()
    t1.task.wait()


# Test what happens when you cancel a task in the middle of a continuation chain.
@pytest.mark.parametrize("useTimeSpan", [False, True])
def test_RunContinuationCancelTest(useTimeSpan: bool) -> None:
    t1Ran = False
    t3Ran = False

    def t1_body() -> None:
        nonlocal t1Ran
        t1Ran = True

    t1 = ColdTask(t1_body)

    ctsForT2 = CancellationTokenSource()

    def t2_body(ContinuedTask: Task[Any]) -> None:
        pytest.fail("RunContinuationCancelTest: > Failed!  t2 should not have run.")

    t2 = t1.task.continue_with(t2_body, token=ctsForT2.token)

    def t3_body(ContinuedTask: Task[Any]) -> None:
        nonlocal t3Ran
        t3Ran = True

    t3 = t2.continue_with(t3_body)

    # Cancel the middle task in the chain.  Should fire off t3.
    ctsForT2.cancel()

    # Start the first task in the chain.  Should hold off from kicking off (canceled) t2.
    t1.start()

    if useTimeSpan:
        timeout = timedelta(milliseconds=5000)
        t1.task.wait(timeout)
        t3.wait(timeout)
    else:
        t1.task.wait(5)  # should be more than enough time for either of these
        t3.wait(5)

    if not t1Ran:
        pytest.fail("RunContinuationCancelTest: > Failed!  t1 should have run.")

    if not t3Ran:
        pytest.fail("RunContinuationCancelTest: > Failed!  t3 should have run.")


def test_RunContinueWithExceptionTestsNoState() -> None:
    #
    # Test exceptional behavior for continuations off of Tasks
    #
    t1 = Task.run(lambda: None)
    t1.wait()

    with pytest.raises(ArgumentNullError) as info:
        t1.continue_with(None)  # type: ignore[arg-type]  # (Action<Task>)null
    assert type(info.value) is ArgumentNullError
    with pytest.raises(ArgumentNullError) as info:
        t1.continue_with(None)  # type: ignore[arg-type]  # (Func<Task, int>)null
    assert type(info.value) is ArgumentNullError
    # ContinueWith(..., (TaskScheduler)null) overloads: FlpIt has no TaskScheduler parameter.

    #
    # Test exceptional behavior for continuations off of Task<int>s
    #
    f1 = Task.run(lambda: 10)
    f1.wait()

    with pytest.raises(ArgumentNullError) as info:
        f1.continue_with(None)  # type: ignore[arg-type]  # (Action<Task<int>>)null
    assert type(info.value) is ArgumentNullError
    with pytest.raises(ArgumentNullError) as info:
        f1.continue_with(None)  # type: ignore[arg-type]  # (Func<Task<int>, int>)null
    assert type(info.value) is ArgumentNullError
    # ContinueWith(..., (TaskScheduler)null) overloads: FlpIt has no TaskScheduler parameter.


def _new_antecedent(antecedentHasResult: bool) -> ColdTask:
    return ColdTask((lambda: 5) if antecedentHasResult else (lambda: None))


def _run_and_wait(continuation: Task[Any], continuationHasResult: bool) -> tuple[Exception | None, int]:
    ex: Exception | None = None
    result = 0
    try:
        continuation.wait()
        if continuationHasResult:
            result = continuation.result()
    except Exception as e:
        ex = e
    return ex, result


def test_RunContinueWithAllParamsTestsNoState() -> None:
    for i in range(2):
        preCanceled = i == 0
        cts = CancellationTokenSource()
        ct = cts.token
        if preCanceled:
            cts.cancel()

        for j in range(2):
            longRunning = j == 0
            tco = TCO.LONG_RUNNING if longRunning else TCO.NONE

            for k in range(2):
                antecedentHasResult = k == 0
                antecedent: Task[Any] | None = None

                for z in range(2):
                    preCompletedTask = z == 0
                    if preCompletedTask:
                        antecedent = Task.run(lambda: 5) if antecedentHasResult else Task.run(lambda: None)
                        antecedent.wait()

                    for x in range(2):
                        continuationHasResult = x == 0
                        # Upstream: Action vs Func<..., int> continuations, Task vs Task<int> antecedents.
                        body: Any = (lambda _: 5) if continuationHasResult else (lambda _: None)

                        #
                        # Test ContinueWith() overloads that take all parameters
                        #
                        cold = None if preCompletedTask else _new_antecedent(antecedentHasResult)
                        source = antecedent if cold is None else cold.task
                        assert source is not None
                        continuation = source.continue_with(body, token=ct, options=tco)

                        # Start the antecedent, if necessary, or the continuation will never run.
                        if cold is not None:
                            cold.start()

                        ex, result = _run_and_wait(continuation, continuationHasResult)

                        assert continuation.status == Task.SUCCEEDED or preCanceled, \
                            "RunContinueWithAllParamsTestsNoState: Expected continuation end as RanToCompletion unless pre-canceled"
                        assert continuation.status == Task.CANCELLED or not preCanceled, \
                            "RunContinueWithAllParamsTestsNoState: Expected continuation to end as Canceled when pre-canceled"
                        assert ex is None or preCanceled, \
                            "RunContinueWithAllParamsTestsNoState: Got Wait() exception w/o pre-cancellation"
                        assert continuation.creation_options == TaskCreationOptions(tco), \
                            "RunContinueWithAllParamsTestsNoState: mis-matched CreationOptions"
                        assert result == 5 or (not continuationHasResult or preCanceled), \
                            "RunContinueWithAllParamsTestsNoState: Expected valid result from non-canceled Task<TResult> continuation"
                        if preCanceled:
                            assert (
                                ex is not None
                                and type(ex) is AggregateError
                                and type(ex.exceptions[0]) is TaskCanceledError
                            ), "RunContinueWithAllParamsTestsNoState: Expected AE(TCE) for Wait after pre-cancellation"

                        #
                        # Test ContinueWith() overloads that take CancellationToken
                        #
                        cold = None if preCompletedTask else _new_antecedent(antecedentHasResult)
                        source = antecedent if cold is None else cold.task
                        assert source is not None
                        continuation = source.continue_with(body, token=ct)

                        # Start the antecedent, if necessary, or the continuation will never run.
                        if cold is not None:
                            cold.start()

                        ex, result = _run_and_wait(continuation, continuationHasResult)

                        assert continuation.status == Task.SUCCEEDED or preCanceled, \
                            "RunContinueWithAllParamsTestsNoState overloads: Expected continuation end as RanToCompletion unless pre-canceled"
                        assert continuation.status == Task.CANCELLED or not preCanceled, \
                            "RunContinueWithAllParamsTestsNoState overloads: Expected continuation to end as Canceled when pre-canceled"
                        assert ex is None or preCanceled, \
                            "RunContinueWithAllParamsTestsNoState overloads: Got Wait() exception w/o pre-cancellation"
                        assert result == 5 or (not continuationHasResult or preCanceled), \
                            "RunContinueWithAllParamsTestsNoState overloads: Expected valid result from non-canceled Task<TResult> continuation"
                        if preCanceled:
                            assert (
                                ex is not None
                                and type(ex) is AggregateError
                                and type(ex.exceptions[0]) is TaskCanceledError
                            ), "RunContinueWithAllParamsTestsNoState overloads: Expected AE(TCE) for Wait after pre-cancellation"

                        #
                        # Test ContinueWith() overloads that take TaskCreationOptions
                        #
                        cold = None if preCompletedTask else _new_antecedent(antecedentHasResult)
                        source = antecedent if cold is None else cold.task
                        assert source is not None
                        continuation = source.continue_with(body, options=tco)

                        # Start the antecedent, if necessary, or the continuation will never run.
                        if cold is not None:
                            cold.start()

                        ex, result = _run_and_wait(continuation, continuationHasResult)

                        assert continuation.status == Task.SUCCEEDED, \
                            "RunContinueWithAllParamsTestsNoState: Expected continuation to end as RanToCompletion"
                        assert ex is None, "RunContinueWithAllParamsTestsNoState: Got Wait() exception"
                        assert continuation.creation_options == TaskCreationOptions(tco), \
                            "RunContinueWithAllParamsTestsNoState: Mis-matched CreationOptions"
                        assert result == 5 or not continuationHasResult, \
                            "RunContinueWithAllParamsTestsNoState: Expected valid result from Task<TResult> continuation"

                        #
                        # The ContinueWith overloads that take a TaskScheduler are already being tested in RunContinueWithTMTests().
                        # So I won't add a block of such tests here.
                        #


# Make sure that cancellation works for monadic versions of ContinueWith()
@_SKIP_UNWRAP
def test_RunUnwrapTests() -> None:
    pass


@_SKIP_UNWRAP
def test_RunUnwrapTests_ExceptionTests() -> None:
    pass


@_SKIP_UNWRAP
def test_RunUnwrapTests_CancellationTests() -> None:
    pass


# Test what happens when you cancel a task in the middle of a continuation chain.
def test_RunContinuationCancelTest_State() -> None:
    t1Ran = False
    t3Ran = False

    def t1_body() -> None:
        nonlocal t1Ran
        t1Ran = True

    t1 = ColdTask(t1_body)
    stateParam = "test"  # used as a state parameter for the continuation if the useStateParam is true
    ctsForT2 = CancellationTokenSource()

    def t2_body(ContinuedTask: Task[Any], obj: object) -> None:
        pytest.fail("RunContinuationCancelTest_State    > Failed!  t2 should not have run.")

    t2 = t1.task.continue_with(t2_body, stateParam, token=ctsForT2.token)

    def t3_body(ContinuedTask: Task[Any]) -> None:
        nonlocal t3Ran
        t3Ran = True

    t3 = t2.continue_with(t3_body)

    # Cancel the middle task in the chain.  Should fire off t3.
    ctsForT2.cancel()

    # Start the first task in the chain.  Should hold off from kicking off (canceled) t2.
    t1.start()

    t1.task.wait(5)  # should be more than enough time for either of these
    t3.wait(5)

    if not t1Ran:
        pytest.fail("RunContinuationCancelTest_State    > Failed!  t1 should have run.")

    if not t3Ran:
        pytest.fail("RunContinuationCancelTest_State    > Failed!  t3 should have run.")


@pytest.mark.skip(reason="its Choose() helper needs TaskFactory.ContinueWhenAll, which FlpIt does not have")
def test_TestNoDeadlockOnContinueWith() -> None:
    pass


def test_RunLazyCancellationTests() -> None:
    for i in range(2):
        useLazyCancellation = i == 0
        options = TCO.LAZY_CANCELLATION if useLazyCancellation else TCO.NONE

        # Upstream also loops over ContinueWhenAny / ContinueWhenAll (j == 1, 2); only the
        # ContinueWith variant (j == 0) is ported.
        cts = CancellationTokenSource()
        mres1 = ManualResetEvent(False)
        mres2 = ManualResetEvent(False)
        t1 = ColdTask(lambda: None)

        def continuation(_: Task[Any]) -> None:
            mres1.set()
            mres2.wait_one()

        c1 = t1.task.continue_with(continuation, token=cts.token, options=options)

        t1.start()
        mres1.wait_one()  # Wait for continuation to start
        cts.cancel()  # Cancel the continuation
        mres2.set()  # Allow continuation to end

        try:
            c1.wait()
        except Exception as e:
            pytest.fail(f"RunLazyCancellationTests: ERROR. Did not expect c1.Wait() to throw an exception, got {e!r}")


def test_RunLazyCancellationTests_Negative() -> None:
    for i in range(2):
        useLazyCancellation = i == 0
        options = TCO.LAZY_CANCELLATION if useLazyCancellation else TCO.NONE

        # Upstream also loops over ContinueWhenAny / ContinueWhenAll (j == 1, 2); only the
        # ContinueWith variant (j == 0) is ported.
        cts = CancellationTokenSource()
        t1 = ColdTask(lambda: None)
        cts.cancel()

        c1 = t1.task.continue_with(lambda _: None, token=cts.token, options=options)

        assert c1.done() != useLazyCancellation, f"RunLazyCancellationTests: Before t1.Start(), c1.IsCompleted = {c1.done()}"

        t1.start()
        EnsureTaskCanceledExceptionThrown(lambda: c1.wait(),
                                          "RunLazyCancellationTests:  Expected TCE on c1.Wait after antecedent started")

        cts = CancellationTokenSource()
        t1 = ColdTask(lambda: None)

        c1 = t1.task.continue_with(lambda _: None, token=cts.token, options=options)
        cts.cancel()

        assert c1.done() != useLazyCancellation, f"RunLazyCancellationTests: Before t1.Start(), c1.IsCompleted = {c1.done()}"

        t1.start()
        EnsureTaskCanceledExceptionThrown(lambda: c1.wait(),
                                          "RunLazyCancellationTests:  Expected TCE on c1.Wait after antecedent started")


def test_LongContinuationChain_ContinueWith_DoesNotStackOverflow() -> None:
    DiveDepth = 12_000

    tcs: TaskCompletionSource[None] = TaskCompletionSource()
    t: Task[Any] = tcs.task
    for _ in range(DiveDepth):
        t = t.continue_with(lambda _: None, options=TCO.EXECUTE_SYNCHRONOUSLY)
    tcs.try_set_result()
    t.wait()


@_SKIP_UNWRAP
def test_LongContinuationChain_Unwrap_DoesNotStackOverflow() -> None:
    pass


def test_LongContinuationChain_Await_DoesNotStackOverflow() -> None:
    DiveDepth = 12_000

    async def func(count: int) -> int:
        count += 1
        # Upstream: await await Task.Factory.StartNew(() => func(count)), a Task<Task<int>>.
        # Task.run unwraps the coroutine itself (like .NET's Task.Run), so one await.
        return await Task.run(func, count) if count < DiveDepth else count

    Task.run(func, 0).wait()


@pytest.mark.parametrize("useWaitAll", [False, True])
def test_TestNoDeadlockOnContinueWithExecuteSynchronously(useWaitAll: bool) -> None:
    # Verify that Task.Wait can return before all continuations scheduled
    # with ExecuteSynchronously complete

    task1 = ColdTask(lambda: None)

    barrier = threading.Barrier(2)

    def continuation(_task: Task[Any]) -> None:
        barrier.wait()  # alert caller that we've started running
        barrier.wait()  # wait for caller to be done waiting

    task2 = task1.task.continue_with(continuation, options=TCO.EXECUTE_SYNCHRONOUSLY)

    task1.start()
    barrier.wait()  # wait for task to start running

    # Wait should return once the task is complete, regardless of what other
    # continuations were scheduled off of it.
    if useWaitAll:
        Task.wait_all(task1.task)
    else:
        task1.task.wait()

    barrier.wait()  # alert task that we're done waiting
    task2.wait()


# =============================================================================
# Helper Methods
# =============================================================================

class _Counter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.value = 0

    def increment(self) -> None:
        with self._lock:
            self.value += 1


def ContinueWithTortureTest(numCanceled: int, numLeftover: int, completeAfter: int, cancelAfter: int) -> None:
    # The TCS mechanism gives us an easy way to start (and complete) antecedent
    antecedentTcs: TaskCompletionSource[None] = TaskCompletionSource()
    antecedent = antecedentTcs.task

    normalCount = _Counter()  # incremented by "normal" or "leftover" continuations
    canceledCount = _Counter()  # incremented by "cancel" continuations
    cts = CancellationTokenSource()  # CTS to cancel

    # These TCS/continuation combos will serve to initiate antecedent completion or CTS signaling asynchronously
    completionTcs: TaskCompletionSource[None] = TaskCompletionSource()
    completionTcs.task.continue_with(lambda _: antecedentTcs.try_set_result(), options=TCO.PREFER_FAIRNESS)
    cancellationTcs: TaskCompletionSource[None] = TaskCompletionSource()
    cancellationTcs.task.continue_with(lambda _: cts.cancel(), options=TCO.PREFER_FAIRNESS)

    # Keep track of continuations so that you can wait on them
    normalContinuations: list[Task[None]] = [Task.completed_task] * numLeftover
    cancelContinuations: list[Task[None]] = [Task.completed_task] * numCanceled

    # Take early action if either threshold is set at 0
    if completeAfter == 0:
        antecedentTcs.try_set_result()
    if cancelAfter == 0:
        cts.cancel()

    # These are the actions to take in "to be run" and "to be canceled" continuations, respectively
    def normalAction(task: Task[Any]) -> None:
        normalCount.increment()

    def cancelAction(task: Task[Any]) -> None:
        canceledCount.increment()

    # Simultaneously start adding both "to be run" continuations and "to be canceled" continuations
    def add_cancel_continuations() -> None:
        for i in range(numCanceled):
            # Use both synchronous and asynchronous continuations
            tco = TCO.NONE if i % 2 == 0 else TCO.EXECUTE_SYNCHRONOUSLY

            # The cancelAction should run exactly once per "to be canceled" continuation -- either in the first continuation or,
            # if the first continuation is canceled, in the second continuation.
            cancelContinuations[i] = antecedent.continue_with(cancelAction, token=cts.token, options=tco) \
                .continue_with(cancelAction, options=tco | TCO.ONLY_ON_CANCELED)

    def add_normal_continuations() -> None:
        for i in range(numLeftover):
            # Use both synchronous and asynchronous continuations
            tco = TCO.NONE if i % 2 == 0 else TCO.EXECUTE_SYNCHRONOUSLY
            normalContinuations[i] = antecedent.continue_with(normalAction, options=tco)

            # If you've hit completeAfter or cancelAfter, take the appropriate action
            if (i + 1) == completeAfter:
                completionTcs.try_set_result()  # Asynchronously completes the antecedent
            if (i + 1) == cancelAfter:
                cancellationTcs.try_set_result()  # Asynchronously initiates cancellation of "to be canceled" tasks

    taskA = Task.run(add_cancel_continuations)
    taskB = Task.run(add_normal_continuations)

    Task.wait_all(taskA, taskB)
    Task.wait_all(normalContinuations)

    try:
        Task.wait_all(cancelContinuations)
    except AggregateError as ae:
        # We may get AE<TCE> from WaitAll on cancelContinuations.  If so, just eat it.
        EnsureExceptionIsAEofTCE(ae, "ContinueWithTortureTest: > FAILED.  Did not expect anything exception AE<TCE> from cancelContinuations.Wait()")

    assert normalCount.value == numLeftover, \
        f"ContinueWithTortureTest: > FAILED! normalCount mismatch (exp {numLeftover} got {normalCount.value})"
    assert canceledCount.value == numCanceled, \
        f"ContinueWithTortureTest: > FAILED! canceledCount mismatch (exp + {numCanceled} got {canceledCount.value})"
