"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Shared helpers for the migrated System.Threading.Channels tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/TestBase.cs

.NET -> Python mapping used throughout tests/nettests/channels:
    [Fact] public async Task X()          -> @async_test async def test_X(self) (runs on the flpit runtime)
    ValueTask / ValueTask<T>              -> flpit Task (multi-await; see the skipped ValueTask-only tests)
    vt.IsCompleted / IsCompletedSuccessfully / IsCanceled / IsFaulted
                                          -> t.done() / t.status == Task.SUCCEEDED / t.cancelled() /
                                             t.status == Task.FAILED
    vt.Result / vt.AsTask()               -> t.result() / t
    TryRead(out T item)                   -> ok, item = reader.try_read() (item is None on failure)
    new CancellationToken(true)           -> canceled_token()
    AssertExtensions.CanceledAsync(ct, t) -> await assert_canceled_async(ct, t)
    e.MoveNextAsync() checked for synchronous completion
                                          -> Started(e.__anext__()) (see Started)
    FormatException / FieldAccessException / ... -> local exception classes
    Interlocked                           -> a lock-guarded counter
"""
from __future__ import annotations

import itertools
import threading
from collections.abc import AsyncIterator, Awaitable, Generator
from typing import Any, cast

import pytest

from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task

from nettests.async_linq.async_helpers import async_test

__all__ = [
    "AsyncEnumeratorSteps",
    "Counter",
    "FormatError",
    "Started",
    "THREE_BOOLS",
    "assert_canceled_async",
    "assert_synchronous_success",
    "assert_synchronous_true",
    "assert_synchronously_canceled",
    "async_test",
    "canceled_token",
    "not_portable",
]

THREE_BOOLS = list(itertools.product([False, True], repeat=3))


class FormatError(Exception):
    """.NET ``FormatException``: an arbitrary error to complete channels with."""


def not_portable(reason: str) -> None:
    pytest.skip(f"Not portable to Python: {reason}")


def canceled_token() -> CancellationToken:
    """.NET ``new CancellationToken(true)``."""
    source = CancellationTokenSource()
    source.cancel()
    return source.token


def assert_synchronous_success(task: Task[Any]) -> None:
    assert task.status == Task.SUCCEEDED


def assert_synchronous_true(task: Task[bool]) -> None:
    assert_synchronous_success(task)
    assert task.result() is True


def assert_synchronously_canceled(task: Task[Any], token: CancellationToken) -> None:
    assert task.cancelled()
    with pytest.raises(OperationCanceledError) as raised:
        task.result()
    assert raised.value.token is token


async def assert_canceled_async(token: CancellationToken, awaitable: Awaitable[Any]) -> None:
    """.NET ``AssertExtensions.CanceledAsync``: awaiting raises a cancellation error for ``token``."""
    with pytest.raises(OperationCanceledError) as raised:
        await awaitable
    assert raised.value.token is token


class Counter:
    """.NET ``Interlocked`` on an int/long field."""

    def __init__(self, value: int = 0) -> None:
        self._lock = threading.Lock()
        self.value = value

    def add(self, amount: int) -> int:
        with self._lock:
            self.value += amount
            return self.value

    def increment(self) -> int:
        return self.add(1)

    def decrement(self) -> int:
        return self.add(-1)


class Started:
    """An awaitable started right away, as .NET's ``ValueTask`` already is.

    ``MoveNextAsync()`` returns a ``ValueTask<bool>`` whose ``IsCompletedSuccessfully`` tells
    whether the step finished without waiting. A Python ``__anext__()`` does nothing until
    awaited, so ``Started`` runs it at once: awaiting a completed flpit task does not suspend,
    so the step only stops where it would really wait. From there it goes on in a task of its
    own, as a .NET async method does, and awaiting ``Started`` awaits that task.
    """

    def __init__(self, awaitable: Awaitable[Any]) -> None:
        steps = awaitable.__await__()
        self._task: Task[Any] | None = None
        self._value: Any = None
        self._error: BaseException | None = None
        try:
            operation = steps.send(None)
        except StopIteration as stop:
            self._value = stop.value
        except BaseException as error:  # noqa: BLE001 - recorded, raised on await
            self._error = error
        else:
            self._task = Task.run(_continue, steps, operation)

    @property
    def is_completed(self) -> bool:
        return self._task is None or self._task.done()

    @property
    def is_completed_successfully(self) -> bool:
        if self._task is not None:
            return self._task.status == Task.SUCCEEDED
        return self._error is None

    @property
    def result(self) -> Any:
        """The value of a completed step (.NET ``vt.Result``)."""
        assert self.is_completed, "the step has not completed"
        if self._task is not None:
            return self._task.result()
        if self._error is not None:
            raise self._error
        return self._value

    def __await__(self) -> Generator[Any, Any, Any]:
        if self._task is not None:
            return (yield from self._task.__await__())
        return self.result


async def _continue(steps: Generator[Any, Any, Any], operation: Any) -> Any:
    return await _Resume(steps, operation)


class _Resume:
    """Hands a step's pending operation to the task awaiting this, then drives the rest of the step."""

    def __init__(self, steps: Generator[Any, Any, Any], operation: Any) -> None:
        self._steps = steps
        self._operation = operation

    def __await__(self) -> Generator[Any, Any, Any]:
        operation = self._operation
        while True:
            try:
                sent = yield operation
            except BaseException as error:  # noqa: BLE001 - forwarded to the step
                try:
                    operation = self._steps.throw(error)
                except StopIteration as stop:
                    return stop.value
                continue
            try:
                operation = self._steps.send(sent)
            except StopIteration as stop:
                return stop.value


class AsyncEnumeratorSteps:
    """.NET ``IAsyncEnumerator<T>``: ``move_next_async()`` / ``current`` / ``dispose_async()``,
    each step ``Started`` so its synchronous completion can be checked."""

    def __init__(self, enumerator: AsyncIterator[Any]) -> None:
        self.enumerator = enumerator
        self.current: Any = None

    def move_next_async(self) -> Started:
        return Started(self._move_next())

    async def _move_next(self) -> bool:
        try:
            self.current = await anext(self.enumerator)
        except StopAsyncIteration:
            return False
        return True

    def dispose_async(self) -> Started:
        return Started(cast(Any, self.enumerator).aclose())
