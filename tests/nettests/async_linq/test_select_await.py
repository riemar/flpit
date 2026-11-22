"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the Ix.NET System.Linq.Async SelectAwait tests (Select.cs):
https://github.com/dotnet/reactive/blob/main/Ix.NET/Source/System.Linq.Async.Tests/System/Linq/Operators/Select.cs

Original source attribution: .NET Foundation / dotnet/reactive, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).
System.Linq.Async is the library that has ``SelectAwait``; .NET 10's System.Linq.AsyncEnumerable folds it into
``Select`` (already ported in test_select.py).

Adapted:
    * ``new ValueTask<T>(value)`` -> an already completed ``Task`` (``_done``).
    * The three source kinds (ToAsyncEnumerable, ToAsyncEnumerableIList, iterator) -> ``create_sources``.
    * The (value, index) overloads are not implemented (``select`` has no index overload either): skipped.
    * The ``...WithCancellation`` overloads (selector takes a CancellationToken) are not implemented:
      ``select_await`` takes a one-argument callback. ``select(async def f(x, ct))`` covers that case: skipped.
    * ``select_await(None)`` is not an error: no selector means the identity (the elements are awaited), so the
      upstream ArgumentNullException assertion for the selector is replaced by an identity assertion.
    * The enumerator type comparison in SequenceIdentity and the ToArrayAsync tests have no Python equivalent.
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from flpit.task import Task, TaskCompletionSource
from nettests.async_linq.async_helpers import (
    append_exception, assert_equal, async_test, create_sources, not_portable, to_pylist, unsupported,
)


def _done(value):
    """``new ValueTask<T>(value)``: an awaitable that is already completed."""
    source = TaskCompletionSource()
    source.set_result(value)
    return source.task


def _letter(i):
    return chr(ord("a") + i)


async def _no_next(enumerator):
    with pytest.raises(StopAsyncIteration):
        await enumerator.__anext__()


def test_SelectAwait_Null():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_SelectAwait_NullSelector_IsTheIdentity():
    assert AsyncFlpIt.empty().select_await(None) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().select_await() is AsyncFlpIt.empty()


@async_test
async def test_SelectAwait_NullSelector_AwaitsTheElements():
    tasks = [_done(1), _done(2)]
    await assert_equal([1, 2], flp.ait(tasks).select_await(None))
    await assert_equal([1, 2], flp.ait(tasks).select_await())


@async_test
async def test_SelectAwait_Simple():
    for source in create_sources(0, 1, 2):
        await assert_equal(["a", "b", "c"], source.select_await(lambda x: _done(_letter(x))))


def test_SelectAwait_Indexed():
    unsupported("SelectAwait((x, i) => ...): select_await has no index overload")


@async_test
async def test_SelectAwait_Throws_Selector():
    for source in create_sources(0, 1, 2):
        ys = source.select_await(lambda x: _done(1 // x))
        e = ys.get_async_enumerator()
        try:
            with pytest.raises(ZeroDivisionError):
                await e.__anext__()
        finally:
            await e.aclose()


def test_SelectAwait_Indexed_Throws_Selector():
    unsupported("SelectAwait((x, i) => ...): select_await has no index overload")


@async_test
async def test_SelectAwait_SelectSelect():
    for source in create_sources(0, 1, 2):
        ys = source.select_await(lambda i: _done(i + 3)).select_await(lambda x: _done(_letter(x)))
        await assert_equal(["d", "e", "f"], ys)


@async_test
async def test_SelectAwait_SequenceIdentity():
    for source in create_sources(1, 2, 3):
        ys = source.select_await(lambda x: _done(_letter(x)))
        assert await to_pylist(ys) == await to_pylist(ys) == ["b", "c", "d"]


def test_SelectAwait_Indexed_SequenceIdentity():
    unsupported("SelectAwait((x, i) => ...): select_await has no index overload")


@async_test
async def test_SelectAwait_IList_Count():
    ys = flp.ait([1, 2, 3, 4, 5]).select_await(lambda x: _done(x * 2))
    assert await ys.count() == 5


@async_test
async def test_SelectAwait_IList_ToList():
    ys = flp.ait([1, 2, 3, 4, 5]).select_await(lambda x: _done(x * 2))
    assert list(await ys.to_list()) == [2, 4, 6, 8, 10]


def test_SelectAwait_IList_ToArray():
    not_portable("ToArrayAsync: Python has no array type, to_list covers it")


@async_test
async def test_SelectAwait_Throws_Source():
    """Not in the upstream SelectAwait section (it has it for Select): an exception of the source surfaces."""
    ex = Exception("Bang")
    ys = append_exception(flp.ait([]), ex).select_await(lambda x: _done(x))
    e = ys.get_async_enumerator()
    try:
        with pytest.raises(Exception) as raised:
            await e.__anext__()
        assert raised.value is ex
    finally:
        await e.aclose()


def test_SelectAwaitWithCancellation():
    unsupported("SelectAwaitWithCancellation: select_await takes a one-argument callback, "
                "use select(async def f(x, ct)) for a token")
