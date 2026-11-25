"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of dotnet/runtime MethodCoverage.cs, except the faulted and canceled Task.WhenAll tests,
which are in test_method_coverage_when_all.py.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/MethodCoverage.cs

The original PascalCase names are kept with a ``test_`` prefix. Mapping:
- ``Task.Factory.StartNew`` is ``Task.run``; ``Task.FromResult(v)`` is a completed ``TaskCompletionSource``.
- Timeouts are seconds in FlpIt: ``30_000`` ms is ``30``, ``-2`` ms is ``-0.002``.
- The array, ``ReadOnlySpan`` and ``IEnumerable`` overloads are a list, a tuple and a generator; FlpIt has one
  variadic form per method, so the generic ``Task<int>`` overloads run the same call.
- ``Task.CurrentId`` / ``Task.Id``: FlpIt has no public task ids. ``_current_id()`` reads the running task
  and compares identities, which is what the original uses the ids for.
- ``await`` on a combinator task is ``result()``.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError
from flpit.task import (
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskCompletionSource,
    _current_task,
)
from flpit.threading import ManualResetEvent


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


def _current_id() -> int | None:
    """``Task.CurrentId``: FlpIt has no public one, so the running task's identity stands in."""
    task = _current_task.value
    return None if task is None else id(task)


def _from_result(value: int) -> Task[int]:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_result(value)
    return source.task


def _null_element_iterator() -> Iterator[Any]:
    yield None


def _empty_iterator() -> Iterator[Any]:
    yield from ()


# ------------------------------------------------------------------------------------------------
# Wait / WaitAny / WhenAny scenarios
# ------------------------------------------------------------------------------------------------

def test_TaskWait_MaxInt32() -> None:
    # Regression test: Validates that tasks can wait on int.MaxValue without assertion.
    t = Task.delay(0.001)
    Task.wait_all([t], timeout=2_147_483_647 / 1000)  # int.MaxValue ms


def test_TaskContinuation() -> None:
    _unsupported("ConcurrentExclusiveSchedulerPair, new Task(...).Start(scheduler) and TaskScheduler ids")


def test_TaskWaitWithCTS() -> None:
    """Test various Task.WhenAll and Wait overloads - EH"""
    mre = ManualResetEvent(False)
    mre_cont = ManualResetEvent(False)
    cts = CancellationTokenSource()

    ids: dict[str, int | None] = {"taskId1": 0, "taskId2": 0, "taskId12": 0, "taskId22": 0}

    def body1() -> None:
        mre.wait_one()
        ids["taskId1"] = _current_id()

    def body2() -> None:
        mre.wait_one()
        ids["taskId2"] = _current_id()
        cts.cancel()

    t1 = Task.run(body1)
    t2 = Task.run(body2)

    when_all_task = [t1, t2]

    def cont(task: Task[Any]) -> int:
        # when task1 ends, the token will be cancelled
        # move the continuation task in cancellation state
        if cts.is_cancellation_requested:
            raise OperationCanceledError(token=cts.token)
        return 0

    cont_task = Task.when_all(when_all_task).continue_with(cont, token=cts.token)
    cont_task.continue_with(lambda task: mre_cont.set())

    def result_body(o: int) -> int | None:
        mre.wait_one(o / 1000)
        return _current_id()

    # Task<int?>.Factory.StartNew((o) => ..., 10): Task.run has no state argument, so the state is bound here.
    when_all_task_result = [Task.run(lambda: result_body(10)), Task.run(lambda: result_body(10))]

    t1.wait(0.005, cts.token)

    def all_done(task: Task[list[int | None]]) -> None:
        ids["taskId12"] = task.result()[0]
        ids["taskId22"] = task.result()[1]
        mre.set()

    Task.when_all(when_all_task_result).continue_with(all_done)
    # Task 2 calls CancellationTokenSource.Cancel. Thus, expect and not fail for OperationCanceledError being thrown.
    try:
        t2.wait(cts.token)
    except OperationCanceledError:
        pass  # expected, do nothing

    assert ids["taskId1"] != ids["taskId2"]
    assert ids["taskId12"] != ids["taskId22"]

    # Waiting on continuation task that should move into the cancelled state.
    mre_cont.wait_one()
    assert cont_task.status == Task.CANCELLED, "Task status is not correct"


def test_TaskWaitAny_WhenAny() -> None:
    """test WaitAny and when Any overloads"""
    mre = ManualResetEvent(False)
    mre2 = ManualResetEvent(False)

    cts = CancellationTokenSource()

    t1 = Task.run(lambda: mre.wait_one())
    t2 = Task.run(lambda: mre.wait_one())

    def result_body() -> int | None:
        mre2.wait_one()
        return _current_id()

    t11 = Task.run(result_body)
    t21 = Task.run(result_body)

    # waitAny with token and timeout
    wait_any = [t1, t2]
    timeout = Task.wait_any(wait_any, timeout=0.001, token=cts.token)

    # task whenany
    def release() -> None:
        Task.delay(0.02)  # not waited on, as in the original
        mre.set()

    Task.run(release)
    when_any_task = [t1, t2]
    when_any_task_result = [t11, t21]

    # task<tresult> whenany
    task_id: dict[str, int | None] = {"value": 0}  # this will be set to the first task<int?> ID that ends

    def first_done(task: Task[Task[int | None]]) -> None:
        task_id["value"] = task.result().result()

    wait_on_it = Task.when_any(when_any_task_result).continue_with(first_done)
    Task.when_any(when_any_task).continue_with(lambda task: mre2.set())

    # Wait on the scenario to finish
    wait_on_it.wait()
    assert timeout == -1
    assert t11.result() == id(t11)
    assert t21.result() == id(t21)

    when_any_verification = task_id["value"] == id(t11) or task_id["value"] == id(t21)

    assert when_any_verification, (
        f"The id for whenAny is not correct expected to be {id(t11)} or {id(t21)} and it is {task_id['value']}")


def test_Task_WhenAny_TwoTasks_InvalidArgs_Throws() -> None:
    # .NET's WhenAny(Task, Task) overload raises ArgumentNullException for "task1" / "task2". FlpIt has one
    # variadic when_any, so the null is reported as an element of "tasks": ArgumentError, of which FlpIt's
    # ArgumentNullError is a subclass.
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any(None, Task.completed_task)
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any(Task.completed_task, None)

    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any(None, _from_result(1))
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any(_from_result(2), None)


def test_Task_WhenAny_NullTaskElement_Throws() -> None:
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any([None])
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any((None,))
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_any(_null_element_iterator())


@pytest.mark.parametrize("tasks", [[], (), "list", "iterator", "no arguments"])
def test_Task_WhenAny_NoTasks_Throws(tasks: Any) -> None:
    with pytest.raises(ArgumentError, match="tasks"):
        if tasks == "no arguments":
            Task.when_any()
        elif tasks == "list":
            Task.when_any(list[Task[Any]]())
        elif tasks == "iterator":
            Task.when_any(_empty_iterator())
        else:
            Task.when_any(tasks)


def test_Task_WhenAny_TwoTasks_OnePreCompleted() -> None:
    t1 = _from_result(1)
    t2: Task[int] = TaskCompletionSource[int]().task

    assert Task.when_any(t1, t2).result() is t1
    assert Task.when_any(t2, t1).result() is t1


def test_Task_WhenAny_TwoTasks_BothPreCompleted() -> None:
    t1 = _from_result(1)
    t2 = _from_result(2)

    assert Task.when_any(t1, t2).result() is t1
    assert Task.when_any(t1, t1).result() is t1
    assert Task.when_any(t2, t1).result() is t2


@pytest.mark.parametrize("first_completes", [True, False])
def test_Task_WhenAny_TwoTasks_WakesOnFirstCompletion(first_completes: bool) -> None:
    t1: TaskCompletionSource[int] = TaskCompletionSource()
    t2: TaskCompletionSource[int] = TaskCompletionSource()

    twa = Task.when_any(t1.task, t2.task)
    assert not twa.done()
    winner = t1 if first_completes else t2
    winner.set_result(42)
    assert twa.result() is winner.task


def test_CancellationTokenRegitration() -> None:
    mre = ManualResetEvent(False)

    cts = CancellationTokenSource()
    # Register((o) => mre.Set(), 1, useSynchronizationContext: true): FlpIt's register takes the callback only.
    cts.token.register(lambda: mre.set())

    cts.cancel_after(0.005)
    # Wait on the scenario to finish
    mre.wait_one()


def test_TaskAwaiter() -> None:
    _unsupported("Task.GetAwaiter().UnsafeOnCompleted")


def test_TaskConfigurableAwaiter() -> None:
    _unsupported("Task.ConfigureAwait(false).GetAwaiter().UnsafeOnCompleted")


def test_FromAsync() -> None:
    _unsupported("Task.Factory.FromAsync and cold tasks (new Task(...).Start())")


# ------------------------------------------------------------------------------------------------
# WaitAll / WhenAll argument validation and completion
# ------------------------------------------------------------------------------------------------

def test_Task_WaitAll_NullArgument_Throws() -> None:
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.wait_all(None)  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.wait_all(None, token=CancellationToken.none())  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.wait_all(None, timeout=30)  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.wait_all(None, timeout=timedelta(seconds=30))  # type: ignore[arg-type]
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.wait_all(None, timeout=30, token=CancellationToken.none())  # type: ignore[arg-type]


def test_Task_WaitAll_NullTaskElement_Throws() -> None:
    null_element = [None]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(null_element)  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(tuple(null_element))  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(null_element, token=CancellationToken.none())  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(null_element, timeout=30)  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(null_element, timeout=timedelta(seconds=30))  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.wait_all(null_element, timeout=30, token=CancellationToken.none())  # type: ignore[arg-type]


def test_Task_WaitAll_InvalidArgument_Throws() -> None:
    with pytest.raises(ArgumentOutOfRangeError):
        Task.wait_all([Task.run(lambda: None)], timeout=-0.002)
    with pytest.raises(ArgumentOutOfRangeError):
        Task.wait_all([Task.run(lambda: None)], timeout=-0.002, token=CancellationToken.none())
    with pytest.raises(ArgumentOutOfRangeError):
        Task.wait_all([Task.run(lambda: None)], timeout=timedelta(milliseconds=-2))


def test_Task_WhenAll_NullArgument_Throws() -> None:
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.when_all(None)  # type: ignore[arg-type]


def test_Task_WhenAll_NullTaskElement_Throws() -> None:
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_all([None])
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_all((None,))
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_all(_null_element_iterator())


def test_Task_WhenAll_NoTasks_IsCompletedSuccessfully() -> None:
    def assert_is_completed_with_empty_result(task: Task[list[Any]]) -> None:
        assert task.status == Task.SUCCEEDED
        assert task.result() == []

    assert_is_completed_with_empty_result(Task.when_all([]))
    assert_is_completed_with_empty_result(Task.when_all(()))
    assert_is_completed_with_empty_result(Task.when_all(list[Task[Any]]()))
    assert_is_completed_with_empty_result(Task.when_all(_empty_iterator()))
    assert_is_completed_with_empty_result(Task.when_all())


def test_Task_WhenAll_TwoTasks_BothPreCompleted() -> None:
    t1 = _from_result(1)
    t2 = _from_result(2)

    def assert_is_completed_successfully_with_result(expected: list[int], task: Task[list[Any]]) -> None:
        assert task.status == Task.SUCCEEDED
        assert task.result() == expected

    assert_is_completed_successfully_with_result([1, 2], Task.when_all(t1, t2))
    assert_is_completed_successfully_with_result([1, 1], Task.when_all(t1, t1))
    assert_is_completed_successfully_with_result([2, 1], Task.when_all(t2, t1))


def test_Task_WhenAll_TwoTasks_OnePreCompleted() -> None:
    t1: Task[int] = TaskCompletionSource[int]().task
    t2 = _from_result(2)

    assert Task.when_all(t1, t2).status != Task.SUCCEEDED
    assert Task.when_all(t1, t1).status != Task.SUCCEEDED
    assert Task.when_all(t2, t1).status != Task.SUCCEEDED


@pytest.mark.parametrize("first_completes_first", [True, False])
def test_Task_WhenAll_TwoTasks_WakesOnBothCompletion(first_completes_first: bool) -> None:
    t1: TaskCompletionSource[int] = TaskCompletionSource()
    t2: TaskCompletionSource[int] = TaskCompletionSource()

    twa = Task.when_all(t1.task, t2.task)
    assert not twa.done()
    if first_completes_first:
        t1.set_result(1)
        assert not twa.done()
        t2.set_result(2)
    else:
        t2.set_result(2)
        assert not twa.done()
        t1.set_result(1)
    assert twa.status == Task.SUCCEEDED
    assert twa.result() == [1, 2]


# ------------------------------------------------------------------------------------------------
# WhenEach
# ------------------------------------------------------------------------------------------------

_END = object()


def _move_next_now(enumerator: Any) -> Any:
    """``MoveNextAsync()`` that must complete synchronously (``IsCompletedSuccessfully``): its result, or _END."""
    awaitable = enumerator.__anext__()
    try:
        awaitable.send(None)
    except StopIteration as stop:
        return stop.value
    except StopAsyncIteration:
        return _END
    awaitable.close()
    pytest.fail("MoveNextAsync did not complete synchronously")


def test_Task_WhenEach_NullsTriggerExceptions() -> None:
    with pytest.raises(ArgumentNullError, match="tasks"):
        Task.when_each(None)  # type: ignore[arg-type]

    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_each([None])  # type: ignore[list-item]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_each((None,))  # type: ignore[arg-type]
    with pytest.raises(ArgumentError, match="tasks"):
        Task.when_each(_null_element_iterator())


def test_Task_WhenEach_EmptyInputsCompleteImmediately() -> None:
    for tasks in ([], (), _empty_iterator()):
        assert _move_next_now(Task.when_each(tasks).__aiter__()) is _END
    assert _move_next_now(Task.when_each().__aiter__()) is _END


@pytest.mark.xfail(strict=True, reason="Task.when_each can be enumerated more than once; .NET's WhenEach only once")
def test_Task_WhenEach_TasksOnlyEnumerableOnce() -> None:
    enumerables = [
        Task.when_each([Task.completed_task, Task.completed_task]),
        Task.when_each((Task.completed_task, Task.completed_task)),
        Task.when_each(iter([Task.completed_task, Task.completed_task])),
        Task.when_each([_from_result(0), _from_result(0)]),
    ]

    async def check(e: Any) -> None:
        e1 = e.__aiter__()
        e2 = e.__aiter__()
        e3 = e.__aiter__()

        assert await anext(e1, _END) is not _END
        assert await anext(e2, _END) is _END
        assert await anext(e3, _END) is _END

        count = 1
        while await anext(e1, _END) is not _END:
            count += 1
        assert count == 2

        assert await anext(e.__aiter__(), _END) is _END

    for e in enumerables:
        Task.run(lambda e=e: check(e)).result()


@pytest.mark.parametrize("mode", ["positional", "list", "iterator"])
def test_Task_WhenEach_IteratesThroughCompleteAndIncompleteTasks(mode: str) -> None:
    tcs1: TaskCompletionSource[int] = TaskCompletionSource()
    tcs2: TaskCompletionSource[int] = TaskCompletionSource()
    tcs3: TaskCompletionSource[int] = TaskCompletionSource()
    array = [_from_result(1), tcs1.task, _from_result(2), tcs2.task, _from_result(3), tcs3.task]

    if mode == "positional":
        tasks = Task.when_each(*array)
    elif mode == "list":
        tasks = Task.when_each(array)
    else:
        tasks = Task.when_each(iter(array))

    assert tasks is not None

    e = tasks.__aiter__()
    assert tasks is not None

    for i in range(1, 4):
        assert _move_next_now(e) is array[2 * (i - 1)]  # Task.FromResult(i)

    async def move_next() -> Any:
        return await anext(e, _END)

    for tcs in (tcs2, tcs1, tcs3):
        pending = Task.run(move_next)
        assert not pending.done()
        tcs.set_result(42)
        assert pending.result() is tcs.task

    assert _move_next_now(e) is _END
