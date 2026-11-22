"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the Ix.NET System.Linq.Async WhereAwait tests (Where.cs):
https://github.com/dotnet/reactive/blob/main/Ix.NET/Source/System.Linq.Async.Tests/System/Linq/Operators/Where.cs

Original source attribution: .NET Foundation / dotnet/reactive, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).
System.Linq.Async is the library that has ``WhereAwait``; .NET 10's System.Linq.AsyncEnumerable folds it into
``Where`` (already ported in test_where.py).

Adapted:
    * ``new ValueTask<bool>(value)`` -> an already completed ``Task`` (``_done``).
    * The (value, index) overloads are not implemented (``where`` has no index overload either): skipped.
    * The ``...WithCancellation`` overloads (predicate takes a CancellationToken) are not implemented:
      ``where_await`` takes a one-argument callback. ``where(async def f(x, ct))`` covers that case: skipped.
"""
import pytest

from flpit import AsyncFlpIt, PredicateNoneError, SourceNoneError, flp
from flpit.task import TaskCompletionSource
from nettests.async_linq.async_helpers import (
    append_exception, assert_equal, async_test, to_pylist, unsupported,
)

INTS = [8, 5, 7, 4, 6, 9, 2, 1, 0]


def _done(value):
    """``new ValueTask<bool>(value)``: an awaitable that is already completed."""
    source = TaskCompletionSource()
    source.set_result(value)
    return source.task


def test_WhereAwait_Null():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().where_await(None)
    with pytest.raises(PredicateNoneError):
        flp.ait(INTS).where_await(None)


@async_test
async def test_WhereAwait_Simple():
    ys = flp.ait(INTS).where_await(lambda x: _done(x % 2 == 0))
    await assert_equal([8, 4, 6, 2, 0], ys)


def test_WhereAwait_Indexed():
    unsupported("WhereAwait((x, i) => ...): where_await has no index overload")


@async_test
async def test_WhereAwait_Throws_Predicate():
    ex = Exception("Bang")

    def predicate(x):
        if x == 4:
            raise ex
        return _done(True)

    e = flp.ait(INTS).where_await(predicate).get_async_enumerator()
    try:
        assert [await e.__anext__() for _ in range(3)] == [8, 5, 7]
        with pytest.raises(Exception) as raised:
            await e.__anext__()
        assert raised.value is ex
    finally:
        await e.aclose()


def test_WhereAwait_Indexed_Throws_Predicate():
    unsupported("WhereAwait((x, i) => ...): where_await has no index overload")


@async_test
async def test_WhereAwait_Throws_Source():
    ex = Exception("Bang")
    ys = append_exception(flp.ait([]), ex).where_await(lambda x: _done(True))
    e = ys.get_async_enumerator()
    try:
        with pytest.raises(Exception) as raised:
            await e.__anext__()
        assert raised.value is ex
    finally:
        await e.aclose()


def test_WhereAwait_Indexed_Throws_Source():
    unsupported("WhereAwait((x, i) => ...): where_await has no index overload")


@async_test
async def test_WhereAwait_WhereWhere():
    ys = (flp.ait(INTS)
          .where_await(lambda x: _done(x % 2 == 0))
          .where_await(lambda x: _done(x > 5)))
    await assert_equal([8, 6], ys)


@async_test
async def test_WhereAwait_SequenceIdentity():
    ys = flp.ait(INTS).where_await(lambda x: _done(x % 2 == 0))
    assert await to_pylist(ys) == await to_pylist(ys) == [8, 4, 6, 2, 0]


def test_WhereAwait_Indexed_SequenceIdentity():
    unsupported("WhereAwait((x, i) => ...): where_await has no index overload")


def test_WhereAwaitWithCancellation():
    unsupported("WhereAwaitWithCancellation: where_await takes a one-argument callback, "
                "use where(async def f(x, ct)) for a token")
