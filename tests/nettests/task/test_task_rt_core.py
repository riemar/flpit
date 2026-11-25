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
from typing import Any

import pytest

from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError, InvalidOperationError
from flpit.task import (
    AggregateError,
    CancellationToken,
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
def _tcs_completion_state_test(kind: str) -> None:
    """RunTCSCompletionStateTests: 50 contenders race to complete one TCS, 20 times.

    Exactly one wins, and every contender sees the winner's outcome right after its own attempt.
    """
    concurrency_level = 50
    # ManualResetEvent: the contenders start together.
    mres = ManualResetEvent(False)

    # May take a few runs to actually see a problem
    for _repeats in range(20):
        tcs: TaskCompletionSource[int] = TaskCompletionSource()
        counts = {"failure": 0, "error": 0}
        lock = threading.Lock()
        mres.reset()

        def contender() -> None:
            mres.wait_one()
            if kind == "result":
                saw_failure = not tcs.try_set_result(10)
                saw_error = tcs.task.result() != 10
            elif kind == "cancel":
                saw_failure = not tcs.try_set_canceled()
                saw_error = not tcs.task.cancelled()
            else:
                saw_failure = not tcs.try_set_exception(Exception("some exception"))
                saw_error = tcs.task.exception() is None
            with lock:
                counts["failure"] += saw_failure
                counts["error"] += saw_error

        threads = [Task.run(contender) for _ in range(concurrency_level)]
        mres.set()
        Task.wait_all(threads)

        assert counts["failure"] == concurrency_level - 1, (
            f"RunTCSCompletionStateTests ({kind}): expected {concurrency_level - 1} failures, got {counts['failure']}")
        assert counts["error"] == 0, (
            f"RunTCSCompletionStateTests ({kind}): {counts['error']} contenders did not see the outcome")


def test_RunTCSCompletionStateTests() -> None:
    # Testing competing SetResults
    _tcs_completion_state_test("result")


def test_RunTCSCompletionStateTests_SetCancel() -> None:
    # Testing competing SetCancels
    _tcs_completion_state_test("cancel")


def test_RunTCSCompletionStateTests_SetException() -> None:
    # Testing competing SetExceptions
    _tcs_completion_state_test("exception")


def test_RunTaskCompletionSourceTests() -> None:
    cts = CancellationTokenSource()
    tcs: TaskCompletionSource[int] = TaskCompletionSource(cts.token)  # the token is only the state object
    tcs.set_result(5)
    assert tcs.task.status == Task.SUCCEEDED
    cts.cancel()
    assert tcs.task.status == Task.SUCCEEDED
    assert not tcs.try_set_exception(Exception("some exception")), "Set result, Canceled, TrySetException succeeded"
    assert not tcs.try_set_result(10), "Set result, Canceled, TrySetResult succeeded"
    assert not tcs.try_set_canceled(), "Set result, Canceled, TrySetCanceled succeeded"
    assert tcs.task.result() == 5
    fake = Exception("blah!")
    # TrySet* after completion must not throw.
    tcs.try_set_result(10)
    tcs.try_set_canceled()
    tcs.try_set_exception(fake)


def test_RunTaskCompletionSourceTests_Negative() -> None:
    # Test that recorded Result is persistent.
    cts = CancellationTokenSource()
    tcs: TaskCompletionSource[int] = TaskCompletionSource(cts.token)  # the token is only the state object
    tcs.set_result(5)
    cts.cancel()

    # .NET InvalidOperationException: FlpIt raises InvalidStateError for a completion source already completed.
    with pytest.raises(InvalidStateError):
        tcs.set_result(10)
    with pytest.raises(InvalidStateError):
        tcs.set_canceled()
    with pytest.raises(InvalidStateError):
        tcs.set_canceled()
    with pytest.raises(InvalidStateError):
        tcs.set_exception(Exception("some other exception"))
    with pytest.raises(InvalidStateError):
        tcs.set_exception([Exception("some other exception")])
    assert tcs.task.result() == 5


def test_RunTaskCompletionSourceTests_SetException() -> None:
    # Test that recorded exception is persistent
    cts = CancellationTokenSource()
    tcs: TaskCompletionSource[int] = TaskCompletionSource(cts.token)  # the token is only the state object
    tcs.set_exception(Exception("Some recorded exception"))
    assert tcs.task.status == Task.FAILED, f"Set exception, Status should be Faulted, is {tcs.task.status}"
    cts.cancel()
    assert tcs.task.status == Task.FAILED, f"Set exception, canceled, Status should be Faulted, is {tcs.task.status}"
    assert not tcs.try_set_result(15), "Set exception, canceled, TrySetResult succeeded"
    assert not tcs.try_set_exception(Exception("blah")), "Set exception, canceled, TrySetException succeeded"
    assert not tcs.try_set_canceled(), "Set exception, canceled, TrySetCanceled succeeded"
    with pytest.raises(Exception):  # noqa: B017 - the original accepts any exception
        tcs.set_result(10)
    with pytest.raises(Exception):  # noqa: B017
        tcs.set_exception(Exception("bar"))
    with pytest.raises(Exception):  # noqa: B017
        tcs.set_canceled()
    assert tcs.task.status == Task.FAILED, f"Set exception, final Status should be Faulted, is {tcs.task.status}"
    with pytest.raises(Exception):  # noqa: B017 - Wait()-ed, expected exception
        tcs.task.wait()

    # Test that setting multiple exceptions works correctly
    tcs = TaskCompletionSource()
    succeeded = tcs.try_set_exception([Exception("Exception A"), Exception("Exception B")])
    assert succeeded, "TrySetException() attempt did not succeed"
    assert tcs.task.status == Task.FAILED, f"TrySetException() did not result in Faulted status (got {tcs.task.status})"
    with pytest.raises(AggregateError) as caught:  # any other exception type fails the test
        tcs.task.wait()
    assert len(caught.value.exceptions) == 2, (
        f"Expected TrySetException() to result in 2 inner exceptions, got {len(caught.value.exceptions)}")

    tcs = TaskCompletionSource()
    # null array element: ArgumentException (and not its ArgumentNullException subtype in .NET either)
    with pytest.raises(ArgumentError) as element:
        tcs.try_set_exception([Exception("Exception A"), None])  # type: ignore[list-item]
    assert not isinstance(element.value, ArgumentNullError)

    with pytest.raises(ArgumentNullError):  # null IEnumerable
        tcs.try_set_exception(None)  # type: ignore[arg-type]

    with pytest.raises(ArgumentError):  # no elements
        tcs.try_set_exception([])

    # Technically, these last two aren't for multiple exceptions, but we'll test them as well.
    with pytest.raises(ArgumentNullError):
        tcs.try_set_exception(None)  # type: ignore[arg-type]  # (Exception)null
    with pytest.raises(ArgumentNullError):
        tcs.set_exception(None)  # type: ignore[arg-type]


def test_RunTaskCompletionSourceTests_SetCanceled() -> None:
    cts = CancellationTokenSource()
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    tcs.set_canceled(cts.token)
    assert tcs.task.status == Task.CANCELLED
    # .NET: Result throws an AggregateException around a TaskCanceledException carrying the token. FlpIt's
    # result() is GetAwaiter().GetResult() (docs/task/exceptions.md): the TaskCanceledError itself; wait() gives
    # the AggregateException form.
    with pytest.raises(AggregateError) as ae:
        tcs.task.wait()
    tce = ae.value.exceptions[0]
    assert type(tce) is TaskCanceledError
    assert tce.token is cts.token
    with pytest.raises(TaskCanceledError) as direct:
        tcs.task.result()
    assert direct.value.token is cts.token
    with pytest.raises(InvalidStateError):  # .NET InvalidOperationException
        tcs.set_canceled(cts.token)


def test_RunTaskCompletionSourceTests_CancellationTests() -> None:
    cts = CancellationTokenSource()
    ct = cts.token
    tcs: TaskCompletionSource[int] = TaskCompletionSource(ct)  # the token is only the state object
    cts.cancel()
    assert tcs.task.status != Task.CANCELLED, "Task Canceled, Should not have seen status = Canceled, did"
    tcs.set_canceled()  # cancel it for real
    assert tcs.task.status == Task.CANCELLED, f"Canceled, Status should be Canceled, is {tcs.task.status}"
    assert not tcs.try_set_exception(Exception("spam")), "Canceled, TrySetException succeeded"
    assert not tcs.try_set_result(10), "Canceled, TrySetResult succeeded"
    assert not tcs.try_set_canceled(), "Canceled, TrySetCanceled succeeded"
    with pytest.raises(Exception):  # noqa: B017 - the original accepts any exception
        tcs.set_result(15)
    with pytest.raises(Exception):  # noqa: B017
        tcs.set_exception(Exception("yet another exception"))
    with pytest.raises(Exception):  # noqa: B017
        tcs.set_canceled()
    with pytest.raises(Exception):  # noqa: B017 - get-Result must throw
        tcs.task.result()
    assert tcs.task.status == Task.CANCELLED, f"Canceled, final status should be Canceled, is {tcs.task.status}"


def test_RunTaskCreateTests() -> None:
    _unsupported("Task constructor, Task.Start, and TaskCreationOptions")


def test_TestTaskTConstruction_bare() -> None:
    # useCtor (new Task<int>(...) + Start()) has no FlpIt counterpart: tasks start when created, so only the
    # Task<int>.Factory.StartNew half of the matrix is ported. AsyncState: Task.run passes the state object as
    # an argument but does not record it as task.async_state, unlike StartNew(func, state); not asserted.
    for use_obj in (True, False):
        ref_obj = object()
        side_effect: list[bool] = []

        def with_obj(obj: object) -> int:
            assert obj is ref_obj
            side_effect.append(True)
            return 42

        def without_obj() -> int:
            side_effect.append(True)
            return 42

        f1 = Task.run(with_obj, ref_obj) if use_obj else Task.run(without_obj)
        result = 0
        ex: BaseException | None = None
        try:
            f1.wait()
            result = f1.result()
        except Exception as e:  # noqa: BLE001
            ex = e
        assert ex is None, "TestTaskTConstruction_bare: Did not expect an exception"
        assert side_effect, "TestTaskTConstruction_bare: The func delegate apparently did not run"
        assert result == 42 and f1.result() == 42, "TestTaskTConstruction_bare: Expected Task<int> result to be 42"
        assert f1.status == Task.SUCCEEDED, "TestTaskTConstruction_bare: Expected RanToCompletion status"


def test_TestTaskTConstruction_ct() -> None:
    # Only the Factory.StartNew half (see TestTaskTConstruction_bare); AsyncState is not asserted either.
    for use_obj in (True, False):
        ref_obj = object()
        for pre_canceled_token in (True, False):
            cts = CancellationTokenSource()
            ct = cts.token
            if pre_canceled_token:
                cts.cancel()
            f1 = Task.run(lambda obj: 42, ref_obj, token=ct) if use_obj else Task.run(lambda: 42, token=ct)

            ex: BaseException | None = None
            result = 0
            try:
                result = f1.result()
            except Exception as e:  # noqa: BLE001
                ex = e
            assert ex is not None or result == 42, "Expected either a valid result or an exception"
            assert pre_canceled_token == (f1.status == Task.CANCELLED), (
                "Expected Task<int> cancellation only with pre-canceled token")
            assert pre_canceled_token != (f1.status == Task.SUCCEEDED), (
                "Expected Task<int> to complete only with un-canceled token")
            assert pre_canceled_token != (result == 42), "Expected valid result only with non-canceled token"
            assert pre_canceled_token == (ex is not None), "Expected exception only with pre-canceled token"
            if pre_canceled_token:
                # .NET: Result throws AggregateException(TaskCanceledException). FlpIt's result() is
                # GetAwaiter().GetResult(): the TaskCanceledError itself; wait() gives the aggregate form.
                assert type(ex) is TaskCanceledError, f"Wrong exception type thrown on pre-canceled token: {ex!r}"
                with pytest.raises(AggregateError) as aggregate:
                    f1.wait()
                assert type(aggregate.value.exceptions[0]) is TaskCanceledError


def test_TestTaskTConstruction_tco() -> None:
    _unsupported("TaskCreationOptions and Task<T> constructor/Factory.StartNew overloads")


def test_TestTaskTConstruction_ct_tco() -> None:
    _unsupported("TaskCreationOptions combined with Task<T> constructor/factory overloads")


def test_RunBasicTaskWithResultTest() -> None:
    # The TaskCreationOptions overloads of the TaskCompletionSource constructor (testOptions =
    # AttachedToParent) do not exist in FlpIt; the state overloads are ported.
    test_state = object()
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    assert tcs.task.async_state is None, "non-null state when not spec'd in empty tcs ctor"
    assert tcs.task.creation_options == TaskCreationOptions.NONE, "non-None TCO in tcs ctor when not spec'd"
    tcs.set_result(10)
    tcs = TaskCompletionSource(test_state)
    assert tcs.task.async_state is test_state, "state in tcs ctor not persistent"
    assert tcs.task.creation_options == TaskCreationOptions.NONE, "non-None TCO in tcs ctor when not spec'd in ctor"
    tcs.set_result(10)


def test_RunBasicTaskWithResultTest_Negative() -> None:
    # The Task<int> constructor overloads have no FlpIt counterpart; Task<int>.Factory.StartNew is Task.run.
    with pytest.raises(ArgumentNullError):
        Task.run(None)  # type: ignore[arg-type]  # StartNew((Func<int>)null)
    with pytest.raises(ArgumentNullError):
        Task.run(None, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE)  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError):
        Task.run(None, object())  # type: ignore[arg-type]  # StartNew((Func<object, int>)null, new object())
    # StartNew(func, state, ..., (TaskScheduler)null): FlpIt has no task schedulers.


def test_RunBasicTaskWithResultTest_PromiseTestsAndCancellation() -> None:
    unexpected_state_observed = False
    promise1: TaskCompletionSource[int] = TaskCompletionSource()  # will be used for explicit wait testing
    promise2: TaskCompletionSource[int] = TaskCompletionSource()  # will be used for implicit wait testing
    promise3: TaskCompletionSource[int] = TaskCompletionSource()  # will be used for cancellation testing

    def t2_body() -> None:
        nonlocal unexpected_state_observed
        unexpected_state_observed |= promise1.task.done()
        promise1.set_result(1234)
        unexpected_state_observed |= not promise1.task.done()
        promise2.set_result(5678)
        promise3.set_canceled()

    Task.run(t2_body)
    promise1.task.wait()

    observed = {"value": 0, "cancellation": False, "other": False}

    def t3_body() -> None:
        observed["value"] = promise2.task.result()
        try:
            promise3.task.result()
        # .NET catches AggregateException from Result; FlpIt's result() is GetAwaiter().GetResult() and raises
        # the TaskCanceledError itself (docs/task/exceptions.md).
        except TaskCanceledError:
            observed["cancellation"] = True
        except Exception:  # noqa: BLE001
            observed["other"] = True

    Task.run(t3_body).wait()

    assert promise2.task.result() == 5678, "Promise value unblocked, but wrong value was read"
    assert observed["value"] == 5678
    assert observed["cancellation"] and not observed["other"], (
        "Cancel()ed promise didn't throw TaskCanceledException on value accessor")
    assert not unexpected_state_observed, "unexpected state observed in Promise test"
    # new TaskCompletionSource<int>(TaskCreationOptions.PreferFairness) -> ArgumentOutOfRangeException:
    # FlpIt's TaskCompletionSource takes no creation options.


def test_RunSynchronouslyTest() -> None:
    # Task.Factory.StartNew(CoreRunSynchronouslyTest).Wait(): the core test from a pool thread.
    Task.run(_core_run_synchronously_test).wait()
    # The rest calls RunSynchronously() on a cancelled cold task, a continuation and a promise and expects
    # InvalidOperationException: FlpIt has no cold tasks and no RunSynchronously() on an existing task.


def _core_run_synchronously_test() -> None:
    # t.RunSynchronously() on a new task: Task.run_inline runs new work on the calling thread.
    executed: list[int] = []
    caller = threading.get_ident()

    def body() -> None:
        executed.append(threading.get_ident())

    t = Task.run_inline(body)
    assert executed and t.status == Task.SUCCEEDED, (
        "task invoked through RunSynchronously() didn't execute or ended up in wrong state")
    assert executed[0] == caller, "task invoked through RunSynchronously() did not run on the calling thread"
    # TaskScheduler.Current: FlpIt has no task schedulers.
    assert t.wait(0.5), "Wait timed out on a task which was previously RunSynchronously()"


def test_CoreRunSynchronouslyTest() -> None:
    _core_run_synchronously_test()


def test_CoreRunSynchronouslyTest_NegativeTests() -> None:
    _unsupported("Task.RunSynchronously, Task.Start, and invalid task-state transitions")


def test_RunTaskExceptionTest() -> None:
    t = Task.run(lambda: None)
    t.wait()
    # Exception of a cleanly completed task: None, and retrieving it must not throw.
    assert t.exception() is None, "non-null Exception from cleanly completed task."

    # Not ported: an outer task with an AttachedToParent child, checking that outer.Exception is null while the
    # child still runs. FlpIt has no attached child tasks, and its exception() waits for the task to complete
    # (.NET's Exception property returns null at once for a task that is still running).

    e = Exception("foobomb")

    def throw_e() -> None:
        raise e

    t = Task.run(throw_e)
    with pytest.raises(AggregateError) as ae:
        t.wait()
    assert len(ae.value.exceptions) == 1 and ae.value.exceptions[0] is e, (
        "expected an AggregateException w/ a single InnerException to be thrown")


# .NET WaitHandle.WaitTimeout. FlpIt's wait_any returns -1 on timeout, but the original also checks that a
# real winner at index 258 comes back as 258.
_WAIT_TIMEOUT = 258


def _cold() -> TaskCompletionSource[None]:
    """Stand-in for an unstarted .NET task (``new Task(delegate { })``).

    FlpIt has no cold tasks: a task runs once created. A pending TaskCompletionSource task cannot complete
    either until it is "started" with ``set_result``.
    """
    return TaskCompletionSource()


def _core_wait_any_test(filler_tasks: int, finish_me_first: list[bool], expected: int) -> None:
    """CoreWaitAnyTest: fillers never run, unfinished workers block on a gate; WaitAny returns the finisher."""
    fillers = [_cold() for _ in range(filler_tasks)]
    tasks: list[Task[Any]] = [filler.task for filler in fillers]

    # Create a MRES to gate the finishers
    mres = ManualResetEvent(False)

    def work(finish_me: bool) -> None:
        if not finish_me:
            mres.wait_one()

    tasks += [Task.run(work, flag) for flag in finish_me_first]

    ret_code = Task.wait_any(tasks)
    # The original repeats the wait from a second (STA) thread; FlpIt has no apartments, a task does.
    other_thread = Task.run(lambda: Task.wait_any(tasks))
    other_thread.wait()
    sta_ret_code = other_thread.result()

    # Release the waiters.
    mres.set()
    try:
        # get rid of the filler tasks by starting them and doing a WaitAll
        for filler in fillers:
            filler.set_result(None)
        Task.wait_all(tasks)
    except AggregateError:
        if filler_tasks == 0:
            raise  # we shouldn't see an exception if we don't have filler tasks.

    assert ret_code == expected, (
        f"CoreWaitAnyTest: WaitAny() with {len(tasks)} tasks returned {ret_code}, expected {expected}")
    assert sta_ret_code == expected, (
        f"CoreWaitAnyTest: WaitAny() from another thread returned {sta_ret_code}, expected {expected}")


def test_RunTaskWaitAnyTests() -> None:
    num_cores = os.cpu_count() or 1

    # Basic tests w/ <64 tasks
    _core_wait_any_test(0, [], -1)
    _core_wait_any_test(0, [True], 0)
    _core_wait_any_test(0, [True, False, False, False], 0)

    if num_cores > 1:
        _core_wait_any_test(0, [False, True, False, False], 1)

    # Tests w/ >64 tasks, w/ winning index >= 64
    _core_wait_any_test(100, [True], 100)
    _core_wait_any_test(100, [True, False, False, False], 100)
    if num_cores > 1:
        _core_wait_any_test(100, [False, True, False, False], 101)

    # Test w/ >64 tasks, w/ winning index < 64
    _core_wait_any_test(62, [True, False, False, False], 62)

    # Test w/ >64 tasks, w/ winning index = WaitHandle.WaitTimeout
    _core_wait_any_test(_WAIT_TIMEOUT, [True, False, False, False], _WAIT_TIMEOUT)

    # Test that already-completed task is returned
    t1 = Task.run(lambda: None)
    t1.wait()
    # these are cold tasks... should not have started or run at all.
    t2, t3, t4 = _cold(), _cold(), _cold()

    assert Task.wait_any(t2.task, t1, t3.task, t4.task) == 1, (
        "RunTaskWaitAnyTests: FAILED pre-completed task test. Wrong index returned.")


def test_RunTaskWaitAnyTests_WithCancellationTokenTests() -> None:
    # Test stuck tasks + a cancellation token
    mre = ManualResetEvent(False)
    token_src = CancellationTokenSource()
    task1 = Task.run(mre.wait_one)
    task2 = Task.run(mre.wait_one)
    waiter_task = Task.run(lambda: Task.wait_any([task1, task2], token=token_src.token))
    token_src.cancel()
    with pytest.raises(AggregateError):
        waiter_task.wait()
    mre.set()

    def test_wait_any_with_ct(n_tasks: int, use_sta: bool, pre_cancel: bool) -> None:
        cts_for_task_cancellation = CancellationTokenSource()
        tasks = [_cold() for _ in range(n_tasks)]

        cts_for_wait_any = CancellationTokenSource()
        if pre_cancel:
            cts_for_wait_any.cancel()
        ct_for_wait_any = cts_for_wait_any.token
        outcome: list[str] = []

        def thread() -> None:
            try:
                Task.wait_any([t.task for t in tasks], token=ct_for_wait_any)
                outcome.append("no exception")
            except OperationCanceledError:
                outcome.append("canceled")
            except Exception as error:  # noqa: BLE001 - the original fails on any other exception
                outcome.append(f"different exception: {error!r}")

        if not pre_cancel:
            def cancel() -> None:
                for _ in range(200):
                    pass
                cts_for_wait_any.cancel()

            Task.run(cancel)
        Task.wait_all(Task.run(thread))

        assert outcome == ["canceled"], (
            f"WaitAny() w/ {n_tasks} tasks (STA={use_sta}, preCancel={pre_cancel}) should have thrown OCE: {outcome}")
        try:
            for t in tasks:  # get rid of all tasks we created
                t.set_result(None)
            Task.wait_all([t.task for t in tasks])
        except Exception:  # noqa: BLE001, S110 - ignore any exceptions, as the original does
            pass
        cts_for_task_cancellation.dispose()

    # Test some small number of tasks
    for n_tasks in (2, 63, 100):  # 63: max w/o overflowing w/ CT; 100: overflows WaitAny()
        test_wait_any_with_ct(n_tasks, False, True)
        test_wait_any_with_ct(n_tasks, False, False)
        test_wait_any_with_ct(n_tasks, True, True)
        test_wait_any_with_ct(n_tasks, True, False)


def test_RunTaskWaitAnyTests_Negative() -> None:
    with pytest.raises(ValueError):
        Task.when_any()
    with pytest.raises(TypeError):
        Task.when_any([object()])


def _wait_on_token(token: Any) -> None:
    """``ct.WaitHandle.WaitOne()``: FlpIt's CancellationToken has no wait handle; a registration does the same."""
    cancelled = threading.Event()
    with token.register(cancelled.set):
        cancelled.wait()


def _do_run_task_wait_all_test(
        num_tasks_type1: int, task_action1: Any, wait_on_act1: bool, cancel_act1: bool,
        num_tasks_type2: int, task_action2: Any,
) -> BaseException | None:
    """DoRunTaskWaitAllTest: WaitAll() on a mix of already completed tasks and yet blocked tasks."""
    tasks: list[Task[Any]] = []
    for i in range(num_tasks_type1 + num_tasks_type2):
        if i < num_tasks_type1:
            task_cts = CancellationTokenSource()
            # Both setting the token on the new task, and passing it in as the state object so that the
            # delegate can acknowledge using it
            tasks.append(Task.run(task_action1, task_cts.token, token=task_cts.token))
            if cancel_act1:
                task_cts.cancel()
            try:
                if wait_on_act1:
                    tasks[i].wait()
            except Exception:  # noqa: BLE001, S110
                pass
        else:
            tasks.append(Task.run(task_action2, None))

    wait_all_exception: list[BaseException] = []

    def wait_all() -> None:
        try:
            Task.wait_all(tasks)
        except Exception as error:  # noqa: BLE001
            wait_all_exception.append(error)

    Task.run(wait_all).wait()
    return wait_all_exception[0] if wait_all_exception else None


def _do_run_task_wait_all_test_with_cancellation_token(
        num_tasks: int, wait_on_act1: bool, cancel_act1: bool, time_to_signal_cancellation_token: int,
) -> BaseException | None:
    """DoRunTaskWaitAllTestWithCancellationToken; ``time_to_signal``: -1 never, 0 beforehand, >0 a delay."""
    cts = CancellationTokenSource()
    ct = cts.token
    if time_to_signal_cancellation_token == 0:
        cts.cancel()

    mres = ManualResetEvent(False)
    # Either way (never, or beforehand) it is OK for the tasks to complete ASAP.
    if time_to_signal_cancellation_token <= 0:
        mres.set()

    tasks: list[Task[Any]] = []
    for i in range(num_tasks):
        task_cts = CancellationTokenSource()
        tasks.append(Task.run(lambda _token: mres.wait_one(), task_cts.token, token=task_cts.token))
        if wait_on_act1:
            tasks[i].wait()
        if cancel_act1:
            task_cts.cancel()

    if time_to_signal_cancellation_token > 0:
        def cancel_thread() -> None:
            Task.delay(time_to_signal_cancellation_token / 1000)  # not awaited, as in the original
            cts.cancel()

        Task.run(cancel_thread)

    wait_all_exception: list[BaseException] = []

    def wait_all() -> None:
        try:
            Task.wait_all(tasks, token=ct)
        except Exception as error:  # noqa: BLE001
            wait_all_exception.append(error)

    Task.run(wait_all).wait()

    # If we delay-signalled the cancellation token, then it is OK to let the tasks complete now.
    if time_to_signal_cancellation_token > 0:
        mres.set()
        Task.wait_all(tasks)
    return wait_all_exception[0] if wait_all_exception else None


def _run_task_wait_all_test(sta_thread: bool, n_task_count: int) -> None:
    method_input = f"RunTaskWaitAllTest: WaitAll() tests for STA={sta_thread}, task count={n_task_count}"
    excp_msg = "foo"

    n_first_half_count = (n_task_count + 1) // 2
    n_second_half_count = n_task_count - n_first_half_count

    def empty_action(_o: object) -> None:
        pass

    def sleep_action(_o: object) -> None:
        for _ in range(200):
            pass

    def sleep_and_ack_cancel_action(ct: Any) -> None:
        if not ct.is_cancellation_requested:
            _wait_on_token(ct)
        raise OperationCanceledError(token=ct)  # acknowledge

    def exception_throw_action(_o: object) -> None:
        raise Exception(excp_msg)

    # test case 1: WaitAll() on a group of already completed tasks
    e = _do_run_task_wait_all_test(n_task_count, empty_action, True, False, 0, None)
    assert e is None, f"{method_input}: WaitAll() threw exception unexpectedly: {e!r}"

    # test case 2: WaitAll() on a group of tasks half of which is already completed, half of which is blocked
    e = _do_run_task_wait_all_test(n_first_half_count, empty_action, True, False, n_second_half_count, sleep_action)
    assert e is None, f"{method_input}: WaitAll() threw exception unexpectedly: {e!r}"

    # test case 3: WaitAll() on a group of tasks half of which is Canceled, half of which is blocked
    e = _do_run_task_wait_all_test(
        n_first_half_count, sleep_and_ack_cancel_action, False, True, n_second_half_count, empty_action)
    assert isinstance(e, AggregateError) and isinstance(e.exceptions[0], TaskCanceledError), (
        f"{method_input}: WaitAll() didn't throw TaskCanceledException for canceled tasks: {e!r}")

    # test case 4: WaitAll() on a group of tasks some of which throws an exception
    e = _do_run_task_wait_all_test(
        n_first_half_count, exception_throw_action, False, False, n_second_half_count, sleep_action)
    assert isinstance(e, AggregateError) and str(e.exceptions[0]) == excp_msg, (
        f"{method_input}: WaitAll() didn't throw AggregateException for tasks that throw: {e!r}")

    # WaitAll with CancellationToken tests

    # test case 5: already completed tasks with an unsignaled token: completes cleanly with no exception
    e = _do_run_task_wait_all_test_with_cancellation_token(n_task_count, True, False, -1)
    assert e is None, f"{method_input}: WaitAll() threw exception unexpectedly: {e!r}"

    # test case 6: already completed tasks with an already signaled token: throws OCE
    e = _do_run_task_wait_all_test_with_cancellation_token(n_task_count, True, False, 0)
    assert isinstance(e, OperationCanceledError), f"{method_input}: WaitAll() should have thrown OCE: {e!r}"

    # test case 7: long tasks with a token that gets canceled after a delay: throws OCE
    e = _do_run_task_wait_all_test_with_cancellation_token(n_task_count, False, False, 25)
    assert isinstance(e, OperationCanceledError), f"{method_input}: WaitAll() should have thrown OCE: {e!r}"


def test_RunTaskWaitAllTests() -> None:
    # ThreadPoolHelpers.EnsureMinThreadsAtLeast(10): FlpIt's pool adds workers for blocked ones by itself.
    _run_task_wait_all_test(False, 1)
    _run_task_wait_all_test(False, 10)


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
    # The Task.Factory.StartNew / Task<int>.Factory.StartNew / Task.Factory.StartNew<int> overloads map onto
    # Task.run; every call creates its task in the same way, so each variant is one Task.run call here.
    # Not ported: the new Task(...)/new Task<int>(...) constructors with Start() (Status Created) and the
    # TaskScheduler arguments: FlpIt has neither cold tasks nor task schedulers.
    temp = 0

    def set_one() -> None:
        nonlocal temp
        temp = 1

    def set_value(i: int) -> None:
        nonlocal temp
        temp = i

    action_variants = {
        "Task.Factory.StartNew(action)": lambda: Task.run(set_one),
        "Task.Factory.StartNew(action, options)": lambda: Task.run(set_one, creation_options=TaskCreationOptions.NONE),
        "Task.Factory.StartNew(action, CT, options, TaskScheduler)": lambda: Task.run(
            set_one, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE),
        "Task.Factory.StartNew(action<object>, object)": lambda: Task.run(set_value, 1),
        "Task.Factory.StartNew(action<object>, object, options)": lambda: Task.run(
            set_value, 1, creation_options=TaskCreationOptions.NONE),
        "Task.Factory.StartNew(action<object>, object, CT, options, TaskScheduler)": lambda: Task.run(
            set_value, 1, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE),
    }
    for label, start in action_variants.items():
        temp = 0
        start().wait()
        assert temp == 1, f"RunRefactoringTests - {label}: FAILED. Delegate failed to execute."

    temp = 0
    tr: TaskCompletionSource[int] = TaskCompletionSource()
    assert tr.task.status == Task.PENDING, "new TaskCompletionSource<int>(): Status after ctor != WaitingForActivation."
    tr.set_result(1)
    temp = tr.task.result()
    assert temp == 1, "new TaskCompletionSource<int>(): FAILED. Delegate failed to execute."

    func_variants = {
        "Task<int>.Factory.StartNew(Func<int>)": lambda: Task.run(lambda: 1),
        "Task<int>.Factory.StartNew(Func<int>, options)": lambda: Task.run(
            lambda: 1, creation_options=TaskCreationOptions.NONE),
        "Task<int>.Factory.StartNew(Func<int>, CT, options, TaskScheduler)": lambda: Task.run(
            lambda: 1, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE),
        "Task<int>.Factory.StartNew(Func<object, int>, object)": lambda: Task.run(lambda i: i, 1),
        "Task<int>.Factory.StartNew(Func<object, int>, object, options)": lambda: Task.run(
            lambda i: i, 1, creation_options=TaskCreationOptions.NONE),
        "Task<int>.Factory.StartNew(Func<object, int>, object, CT, options, TaskScheduler)": lambda: Task.run(
            lambda i: i, 1, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE),
    }
    for label, start in func_variants.items():
        temp = 0
        temp = start().result()
        assert temp == 1, f"RunRefactoringTests - {label}: FAILED. Delegate failed to execute."


def test_RunRefactoringTests_NegativeTests() -> None:
    temp = 0
    f = Task.run(lambda i: i, 1, token=CancellationToken.none(), creation_options=TaskCreationOptions.NONE)
    temp = f.result()
    assert temp == 1, "Task.Factory.StartNew<int>(Func<object, int>, object, CT, options, TaskScheduler): FAILED."

    # Not ported: Start() on a TaskCompletionSource task, on a continuation and twice on one task,
    # new Task(null), and Start/StartNew with a null TaskScheduler: FlpIt has no Start(), no task constructor
    # and no task schedulers.

    with pytest.raises(Exception):  # noqa: B017 - Illegal Options: any exception, as in the original
        Task.run(lambda: None, creation_options=TaskCreationOptions(10000))

    with pytest.raises(Exception):  # noqa: B017 - Task.Factory.StartNew() w/ Null Action
        Task.run(None)  # type: ignore[arg-type]

    tr: TaskCompletionSource[int] = TaskCompletionSource()
    tr.set_exception(Exception("some exception"))
    try:
        with pytest.raises(Exception):  # noqa: B017 - set Result after setting Exception
            tr.set_result(5)
    finally:
        tr.task.exception()

    tr = TaskCompletionSource()
    tr.set_result(5)
    try:
        with pytest.raises(Exception):  # noqa: B017 - set Exception after setting Result
            tr.set_exception(Exception("some exception"))
    finally:
        temp = tr.task.result()
    assert temp == 5


def test_RunTaskStatusTests() -> None:
    # FlpIt has four states (pending, succeeded, failed, cancelled). .NET's Created, WaitingForActivation,
    # WaitingToRun, Running and WaitingForChildrenToComplete are all "pending" here: those checks become
    # "pending and not completed". Not ported: the cold-task cases (new Task(...), and a token cancelled after
    # its constructor) and WaitingForChildrenToComplete (AttachedToParent children).
    mre = ManualResetEvent(False)

    # TaskStatus.WaitingForActivation (continuation of a task that has not completed)
    gate: TaskCompletionSource[None] = TaskCompletionSource()
    ct = gate.task.continue_with(lambda _: None)
    assert ct.status == Task.PENDING, f"Expected WaitingForActivation status (continuation), got {ct.status}"
    assert not ct.done(), "Expected IsCompleted to be false."
    tcs: TaskCompletionSource[object] = TaskCompletionSource()
    assert tcs.task.status == Task.PENDING, f"Expected WaitingForActivation status (TCS), got {tcs.task.status}"
    assert not tcs.task.done(), "Expected IsCompleted to be false."
    tcs.try_set_canceled()
    gate.set_result(None)

    # TaskStatus.Canceled (already signaled CTS): should immediately transition into cancelled state
    cts = CancellationTokenSource()
    token = cts.token
    cts.cancel()
    t = Task.run(lambda: None, token=token)
    assert t.status == Task.CANCELLED, f"Canceled (already signaled CTS): Expected Canceled status, got {t.status}"

    # Internal Cancellation: cancel but don't acknowledge
    ctsource = CancellationTokenSource()
    ctoken = ctsource.token
    t = Task.run(lambda: ctsource.cancel(), token=ctoken)
    try:
        t.wait()
    except Exception:  # noqa: BLE001, S110
        pass
    assert t.status == Task.SUCCEEDED, f"Internal Cancellation: Expected RanToCompletion status, got {t.status}"
    assert t.done(), "Internal Cancellation: Expected IsCompleted to be true."

    # TaskStatus.Running
    mre.reset()
    mre2 = ManualResetEvent(False)

    def running() -> None:
        mre2.set()
        mre.wait_one()

    t = Task.run(running)
    mre2.wait_one()
    mre2.reset()
    assert t.status == Task.PENDING, f"Running: Expected Running status, got {t.status}"
    assert not t.done(), "Running: Expected IsCompleted to be false."
    mre.set()
    t.wait()

    # TaskStatus.RanToCompletion
    t = Task.run(lambda: None)
    t.wait()
    assert t.status == Task.SUCCEEDED, f"RanToCompletion: Expected RanToCompletion status, got {t.status}"
    assert t.done(), "RanToCompletion: Expected IsCompleted to be true."


def test_RunTaskStatusTests_NegativeTests() -> None:
    # Not ported: the three AttachedToParent cases (WaitingForChildrenToComplete for a canceled and a faulted
    # parent, and a faulted child trumping the parent's cancellation): FlpIt has no attached child tasks.

    # TaskStatus.Canceled: cancelled while running, acknowledged with the task's own token
    task_start_mre = ManualResetEvent(False)
    cts = CancellationTokenSource()

    def spin_then_acknowledge() -> None:
        task_start_mre.set()
        while not cts.token.is_cancellation_requested:
            pass
        raise OperationCanceledError(token=cts.token)

    t = Task.run(spin_then_acknowledge, token=cts.token)
    task_start_mre.wait_one()  # make sure the task starts running before we cancel it
    cts.cancel()
    try:
        t.wait()
    except Exception:  # noqa: BLE001, S110
        pass
    assert t.status == Task.CANCELLED, f"TaskStatus.Canceled: Expected Canceled status, got {t.status}"
    assert t.done(), "TaskStatus.Canceled: Expected IsCompleted to be true."

    # AcknowledgeCancellation
    ctsource = CancellationTokenSource()
    ctoken = ctsource.token

    def acknowledge() -> None:
        while not ctoken.is_cancellation_requested:
            pass
        raise OperationCanceledError(token=ctoken)

    t = Task.run(acknowledge, token=ctoken)
    ctsource.cancel()
    try:
        t.wait()
    except Exception:  # noqa: BLE001, S110
        pass
    assert t.status == Task.CANCELLED, f"AcknowledgeCancellation: Expected Canceled, got {t.status}"

    # TaskStatus.Faulted: cancelling afterwards should have NO EFFECT, since the task already faulted.
    cts = CancellationTokenSource()

    def unhandled() -> None:
        raise Exception("Some Unhandled Exception")

    t = Task.run(unhandled, token=cts.token)
    try:
        t.wait()
    except Exception:  # noqa: BLE001, S110
        pass
    cts.cancel()
    assert t.status == Task.FAILED, f"TaskStatus.Faulted: Expected Faulted status, got {t.status}"
    assert t.done(), "TaskStatus.Faulted: Expected IsCompleted to be true."


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
