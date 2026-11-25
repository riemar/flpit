"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of the faulted and canceled Task.WhenAll tests from current dotnet/runtime MethodCoverage.cs.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/MethodCoverage.cs

Those tests check the combined task's Status and Exception: Exception.InnerException is the single failure,
Exception.InnerExceptions holds every failure, and a failure wins over a cancellation. FlpIt's ``exception()``
is .NET's ``Task.Exception``; ``status`` and ``cancelled()`` are its ``Status``. The original PascalCase names
are kept with a ``test_`` prefix; the generic ``Task<int>`` variants run the same body with results.
"""
from __future__ import annotations

import pytest

from flpit.task import AggregateError, CancellationTokenSource, Task, TaskCompletionSource


def _faulted(error: Exception) -> Task[int]:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_exception(error)
    return source.task


def _succeeded(value: int) -> Task[int]:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_result(value)
    return source.task


def _canceled() -> Task[int]:
    source: TaskCompletionSource[int] = TaskCompletionSource()
    source.set_canceled()
    return source.task


def _inner_exceptions(task: Task[object]) -> tuple[Exception, ...]:
    exception = task.exception()
    assert isinstance(exception, AggregateError)  # .NET: Task.Exception is an AggregateException
    return exception.exceptions


@pytest.mark.parametrize("first_faulted", [True, False])
def test_Task_WhenAll_TwoTasks_WhenPreCompletedFromException(first_faulted: bool) -> None:
    error = ValueError("expected")
    other = _succeeded(1)
    combined = Task.when_all(_faulted(error), other) if first_faulted else Task.when_all(other, _faulted(error))

    assert combined.status == Task.FAILED
    assert _inner_exceptions(combined)[0] is error  # Exception.InnerException


def test_Task_WhenAll_TwoTasks_WhenBothPreCompletedFromException() -> None:
    first, second = ValueError("first"), KeyError("second")
    combined = Task.when_all(_faulted(first), _faulted(second))

    assert combined.status == Task.FAILED
    assert _inner_exceptions(combined) == (first, second)  # InnerExceptions, in argument order


@pytest.mark.parametrize("faulted_first", [True, False])
def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithException(faulted_first: bool) -> None:
    error = ValueError("expected")
    first: TaskCompletionSource[int] = TaskCompletionSource()
    second: TaskCompletionSource[int] = TaskCompletionSource()
    combined = Task.when_all(first.task, second.task)

    failing, succeeding = (first, second) if faulted_first else (second, first)
    failing.set_exception(error)
    assert not combined.done()  # faulted only after both complete
    succeeding.set_result(1)

    assert combined.status == Task.FAILED
    assert _inner_exceptions(combined)[0] is error


def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithExceptionForBoth() -> None:
    first_error, second_error = ValueError("first"), KeyError("second")
    first: TaskCompletionSource[int] = TaskCompletionSource()
    second: TaskCompletionSource[int] = TaskCompletionSource()
    combined = Task.when_all(first.task, second.task)

    second.set_exception(second_error)
    assert not combined.done()
    first.set_exception(first_error)

    assert combined.status == Task.FAILED
    assert set(_inner_exceptions(combined)) == {first_error, second_error}  # the original checks no order


@pytest.mark.parametrize("canceled_first", [True, False])
def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithCancellation(canceled_first: bool) -> None:
    first: TaskCompletionSource[int] = TaskCompletionSource()
    second: TaskCompletionSource[int] = TaskCompletionSource()
    combined = Task.when_all(first.task, second.task)

    canceling, succeeding = (first, second) if canceled_first else (second, first)
    canceling.set_canceled()
    assert not combined.done()
    succeeding.set_result(1)

    assert combined.cancelled()


def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithCancellationForBoth() -> None:
    first: TaskCompletionSource[int] = TaskCompletionSource()
    second: TaskCompletionSource[int] = TaskCompletionSource()
    combined = Task.when_all(first.task, second.task)

    first.set_canceled()
    assert not combined.done()
    second.set_canceled()

    assert combined.cancelled()


def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithSameCancellationForBoth() -> None:
    with CancellationTokenSource() as source:
        first = Task.delay(30, token=source.token)
        second = Task.delay(30, token=source.token)
        combined = Task.when_all(first, second)
        assert not combined.done()
        source.cancel()
        try:
            combined.wait(5)
        except AggregateError:
            pass

    assert combined.cancelled()


@pytest.mark.parametrize("faulted_first", [True, False])
def test_Task_WhenAll_TwoTasks_WakesOnBothCompletionWithExceptionAndCancellation(faulted_first: bool) -> None:
    error = ValueError("expected")
    first: TaskCompletionSource[int] = TaskCompletionSource()
    second: TaskCompletionSource[int] = TaskCompletionSource()
    combined = Task.when_all(first.task, second.task)

    if faulted_first:
        first.set_exception(error)
        second.set_canceled()
    else:
        second.set_canceled()
        first.set_exception(error)

    assert combined.status == Task.FAILED  # faulted takes precedence over canceled
    assert _inner_exceptions(combined)[0] is error


def test_Task_WhenAll_PreCanceledAndPreFaulted_FaultWins() -> None:
    """FlpIt addition: the precedence rule with both inputs already complete."""
    error = ValueError("expected")
    combined = Task.when_all(_canceled(), _faulted(error))

    assert combined.status == Task.FAILED
    assert _inner_exceptions(combined) == (error,)
