"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest port of current dotnet/runtime TaskCompletionSource<TResult> tests.

Upstream source (current .NET runtime; no Mono sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskCompletionSourceTResultTests.cs

FlpIt has one TaskCompletionSource for both .NET types. Nine of the twelve tests are the same as in
TaskCompletionSourceTests.cs except for the type argument; they run in test_task_completion_source.py.
These are the three that check the result value.
"""
from __future__ import annotations

import pytest
from nettests.task.test_task_completion_source import (
    _assert_completed_tcs_fails_to_complete_again,
)

from flpit.task import (
    CancellationTokenSource,
    InvalidStateError,
    Task,
    TaskCompletionSource,
)


def _from_result(value: object) -> Task[object]:
    source: TaskCompletionSource[object] = TaskCompletionSource()
    source.set_result(value)
    return source.task


def _from_exception(error: Exception) -> Task[object]:
    source: TaskCompletionSource[object] = TaskCompletionSource()
    source.set_exception(error)
    return source.task


def _from_canceled() -> Task[object]:
    cts = CancellationTokenSource()
    cts.cancel()
    source: TaskCompletionSource[object] = TaskCompletionSource()
    source.set_canceled(cts.token)
    return source.task


@pytest.mark.parametrize("try_method", [False, True])
def test_SetResult_CompletesSuccessfully(try_method: bool) -> None:
    result = object()
    tcs: TaskCompletionSource[object] = TaskCompletionSource()
    assert tcs.task.status == Task.PENDING

    if try_method:
        assert tcs.try_set_result(result)
    else:
        tcs.set_result(result)
    assert tcs.task.status == Task.SUCCEEDED
    assert tcs.task.result() is result

    _assert_completed_tcs_fails_to_complete_again(tcs)


def test_SetFromTask_AlreadyCompleted_ReturnsFalseOrThrows() -> None:
    result = object()
    tcs: TaskCompletionSource[object] = TaskCompletionSource()
    tcs.set_result(result)

    assert not tcs.try_set_from_task(_from_result(object()))
    assert not tcs.try_set_from_task(_from_exception(Exception()))
    assert not tcs.try_set_from_task(_from_canceled())

    with pytest.raises(InvalidStateError):
        tcs.set_from_task(_from_result(object()))
    with pytest.raises(InvalidStateError):
        tcs.set_from_task(_from_exception(Exception()))
    with pytest.raises(InvalidStateError):
        tcs.set_from_task(_from_canceled())

    assert tcs.task.status == Task.SUCCEEDED
    assert tcs.task.result() is result


@pytest.mark.parametrize("try_method", [False, True])
def test_SetFromTask_CompletedSuccessfully(try_method: bool) -> None:
    tcs: TaskCompletionSource[object] = TaskCompletionSource()
    source = _from_result(object())

    if try_method:
        assert tcs.try_set_from_task(source)
    else:
        tcs.set_from_task(source)

    assert tcs.task.result() is source.result()
