"""What each way of observing a failed or cancelled task raises or returns.

The contract (docs/task/exceptions.md), .NET's with one deviation:

* ``result()`` and ``await`` raise the first failure as it is, like ``GetAwaiter().GetResult()`` and ``await``
  (not like ``Task.Result``, which always wraps);
* ``wait()`` and ``Task.wait_all()`` raise an ``AggregateError`` with every failure, like ``Wait()``;
* ``exception()`` returns an ``AggregateError`` with every failure, like ``Task.Exception``; for a cancelled task
  it raises the cancellation (.NET returns null; ``asyncio.Future.exception()`` raises too);
* a ``KeyboardInterrupt`` or ``SystemExit`` from a task is never put inside an ``AggregateError``.
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
    TaskCompletionSource,
)


def boom(message: str = "boom") -> Any:
    raise ValueError(message)


def other(message: str = "other") -> Any:
    raise KeyError(message)


def interrupted() -> Any:
    raise KeyboardInterrupt


def exiting() -> Any:
    raise SystemExit(3)


def cancelled_task() -> Task[Any]:
    source = CancellationTokenSource()
    task = Task.delay(30, token=source.token)
    source.cancel()
    settle(task)
    return task


def settle(task: Task[Any]) -> Task[Any]:
    try:
        task.wait()
    except BaseException:  # noqa: BLE001 - only the outcome matters here
        pass
    return task


def raised(observe: Callable[[], Any]) -> BaseException | None:
    try:
        observe()
    except BaseException as error:  # noqa: BLE001
        return error
    return None


def by_await(task: Task[Any]) -> Callable[[], Any]:
    async def observe() -> Any:
        return await task

    def run() -> Any:
        return settle(Task.run(observe)).result()

    return run


def inner(error: BaseException | None) -> list[type[BaseException]]:
    assert isinstance(error, AggregateError), error
    return [type(e) for e in error.exceptions]


# -- one failure ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("make", [
    pytest.param(lambda: Task.run(boom), id="plain task"),
    pytest.param(lambda: Task.when_all(Task.run(boom), Task.run(lambda: 1)), id="when_all, one fails"),
    pytest.param(lambda: Task.when_all(Task.run(boom), cancelled_task()), id="when_all, one fails, one cancelled"),
])
def test_one_failure(make: Callable[[], Task[Any]]) -> None:
    task = settle(make())
    assert type(raised(task.result)) is ValueError
    assert type(raised(by_await(task))) is ValueError
    assert inner(raised(task.wait)) == [ValueError]
    exception = task.exception()
    assert inner(exception) == [ValueError]
    assert task.exception() is exception  # the same instance each time, like Task.Exception
    assert raised(task.result) is exception.exceptions[0]  # result() raises what exception() holds


# -- several failures -------------------------------------------------------------------------------------

def test_several_failures_result_and_await_raise_the_first_in_argument_order() -> None:
    task = settle(Task.when_all(Task.run(boom), Task.run(other), Task.run(lambda: 1)))
    first = raised(task.result)
    assert type(first) is ValueError
    assert type(raised(by_await(task))) is ValueError
    assert inner(raised(task.wait)) == [ValueError, KeyError]
    assert inner(task.exception()) == [ValueError, KeyError]
    assert task.exception().exceptions[0] is first


def test_nested_when_all_and_several_completion_source_failures_are_kept_flat() -> None:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_exception([ValueError("a"), KeyError("b")])
    inner_all = settle(Task.when_all(Task.run(other), source.task))
    outer = settle(Task.when_all(inner_all, Task.run(boom)))
    # .NET WhenAll gathers each child's Exception.InnerExceptions.
    assert inner(outer.exception()) == [KeyError, ValueError, KeyError, ValueError]
    assert type(raised(outer.result)) is KeyError


def test_wait_all_holds_every_failure_of_every_task() -> None:
    first = settle(Task.when_all(Task.run(boom), Task.run(other)))
    second = settle(Task.run(boom))
    assert inner(raised(lambda: Task.wait_all(first, second))) == [ValueError, KeyError, ValueError]


def test_an_aggregate_error_raised_by_the_task_itself_is_kept_as_it_is() -> None:
    own = AggregateError([ValueError("mine")])

    def raise_own() -> None:
        raise own

    task = settle(Task.run(raise_own))
    assert raised(task.result) is own  # GetResult rethrows the exception the body threw
    assert task.exception().exceptions == (own,)  # .NET nests it: Exception.InnerException is the thrown one


# -- cancellation -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("make", [
    pytest.param(cancelled_task, id="plain task"),
    pytest.param(lambda: Task.when_all(cancelled_task()), id="when_all, all cancelled"),
])
def test_cancellation(make: Callable[[], Task[Any]]) -> None:
    task = settle(make())
    for observe in (task.result, by_await(task), task.exception):
        error = raised(observe)
        assert isinstance(error, OperationCanceledError)
    assert inner(raised(task.wait)) == [TaskCanceledError]


def test_when_all_cancellation_is_a_task_canceled_error_of_the_combined_task() -> None:
    task = settle(Task.when_all(cancelled_task()))
    error = raised(task.result)
    assert isinstance(error, TaskCanceledError) and error.task is task


def test_a_task_cancelled_before_it_starts_reports_a_task_canceled_error() -> None:
    source = CancellationTokenSource()
    source.cancel()
    task = settle(Task.run(lambda: 1, token=source.token))
    error = raised(task.result)
    assert isinstance(error, TaskCanceledError)
    assert error.task is task and error.token is source.token


# -- KeyboardInterrupt and SystemExit never hide in an AggregateError --------------------------------------

@pytest.mark.parametrize("body, kind", [(interrupted, KeyboardInterrupt), (exiting, SystemExit)])
@pytest.mark.parametrize("combined", [False, True], ids=["plain task", "when_all"])
def test_interrupts_stay_unwrapped(body: Callable[[], Any], kind: type[BaseException], combined: bool) -> None:
    task = Task.when_all(Task.run(body), Task.run(boom)) if combined else Task.run(body)
    task = settle(task)
    assert type(raised(task.result)) is kind
    assert type(raised(task.wait)) is kind
    assert type(raised(lambda: Task.wait_all(task))) is kind
    assert type(task.exception()) is kind
