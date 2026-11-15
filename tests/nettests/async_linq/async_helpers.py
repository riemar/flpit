"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Shared helpers for the migrated System.Linq.AsyncEnumerable tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/AsyncEnumerableTests.cs

.NET -> Python mapping used throughout tests/nettests/async_linq:
    [Fact] public async Task X()             -> @async_test def test_X() (runs on the flpit runtime)
    IAsyncEnumerable<T>                       -> AsyncFlpIt[T]
    items.ToAsyncEnumerable()                 -> flp.ait(items)
    AsyncEnumerable.Empty<T>()                -> AsyncFlpIt.empty()
    source.Yield()                            -> yield_(source) (Task.yield_now() before every element,
                                                 observes the enumeration token like .NET's Yield)
    source.Track()                            -> track(source) (move_next_count / current_count / dispose_count)
    source.AppendException(e)                 -> append_exception(source, e)
    await x.FooAsync(...)                     -> await x.foo(...) (terminal operators return a Task)
    x.WithCancellation(ct)                    -> x.with_cancellation(ct)
    await foreach (var i in x) { }            -> await consume(x)
    Func<T, CancellationToken, ValueTask<R>>  -> async def f(x, ct)
    MoveNextAsync / Current / DisposeAsync    -> __anext__ / value returned by __anext__ / aclose
    ArgumentNullException("source")           -> SourceNoneError (AsyncFlpIt(None))
    OperationCanceledException                -> OperationCanceledError
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

import pytest

from flpit import AsyncFlpIt, flp
from flpit.task import CancellationToken, Task


def async_test(function: Callable[..., Any]) -> Callable[..., Any]:
    """Runs an ``async def`` test (or a sync test wrapping one) to completion on the flpit runtime."""
    if not inspect.iscoroutinefunction(function):
        return function

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return Task.run(function, *args, **kwargs).result()

    return wrapper


def unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


def not_portable(reason: str) -> None:
    pytest.skip(f"Not portable to Python: {reason}")


# --- sources -------------------------------------------------------------------------------------

def yield_(source: AsyncFlpIt[Any]) -> AsyncFlpIt[Any]:
    """.NET ``Yield()``: forces an asynchronous step before each element and observes the token."""

    async def _factory(token: CancellationToken) -> AsyncIterator[Any]:
        enumerator = source.get_async_enumerator(token)
        try:
            async for item in enumerator:
                token.throw_if_cancellation_requested()
                await Task.yield_now()
                yield item
        finally:
            await enumerator.aclose()

    return AsyncFlpIt.create(_factory)


def create_source(*items: Any) -> AsyncFlpIt[Any]:
    return yield_(flp.ait(list(items)))


def create_sources(*items: Any) -> list[AsyncFlpIt[Any]]:
    sources: list[AsyncFlpIt[Any]] = []
    if not items:
        sources.append(flp.ait([]))
        sources.append(AsyncFlpIt.empty())
    sources.append(flp.ait(list(items)))
    sources.append(yield_(flp.ait(list(items))))
    return sources


def append_exception(source: AsyncFlpIt[Any], exception: BaseException) -> AsyncFlpIt[Any]:
    async def _factory(token: CancellationToken) -> AsyncIterator[Any]:
        async for item in source.with_cancellation(token):
            yield item
        raise exception

    return AsyncFlpIt.create(_factory)


class TrackingAsyncEnumerable(AsyncFlpIt[Any]):
    """.NET ``TrackingAsyncEnumerable<T>``: counts MoveNextAsync / Current / DisposeAsync calls."""

    __slots__ = ("_inner", "move_next_count", "current_count", "dispose_count")

    def __init__(self, source: AsyncFlpIt[Any]) -> None:
        self._inner = source
        self.move_next_count = 0
        self.current_count = 0
        self.dispose_count = 0
        super().__init__(_TrackingFactory(self))


class _TrackingFactory:
    def __init__(self, parent: TrackingAsyncEnumerable) -> None:
        self._parent = parent

    def get_async_enumerator(self, token: CancellationToken | None = None) -> AsyncIterator[Any]:
        return _TrackingEnumerator(self._parent, self._parent._inner.get_async_enumerator(token))


class _TrackingEnumerator:
    def __init__(self, parent: TrackingAsyncEnumerable, inner: Any) -> None:
        self._parent = parent
        self._inner = inner

    def __aiter__(self) -> "_TrackingEnumerator":
        return self

    async def __anext__(self) -> Any:
        self._parent.move_next_count += 1
        item = await self._inner.__anext__()
        self._parent.current_count += 1
        return item

    async def aclose(self) -> None:
        self._parent.dispose_count += 1
        await self._inner.aclose()


def track(source: AsyncFlpIt[Any]) -> TrackingAsyncEnumerable:
    return TrackingAsyncEnumerable(source)


# --- assertions ----------------------------------------------------------------------------------

async def consume(source: AsyncFlpIt[Any]) -> None:
    """.NET ``await foreach``: unlike Python's ``async for``, it disposes (``aclose``) the enumerator."""
    enumerator = source.get_async_enumerator()
    try:
        async for _ in enumerator:
            pass
    finally:
        await enumerator.aclose()


async def to_pylist(source: AsyncFlpIt[Any]) -> list[Any]:
    return list(await source.to_list())


async def assert_equal(expected: Iterable[Any] | AsyncFlpIt[Any], actual: AsyncFlpIt[Any]) -> None:
    if isinstance(expected, AsyncFlpIt):
        expected = await to_pylist(expected)
    assert list(expected) == await to_pylist(actual)


async def assert_canceled(source: AsyncFlpIt[Any], token: CancellationToken | None = None) -> None:
    from flpit.task import OperationCanceledError
    with pytest.raises(OperationCanceledError):
        await consume(source if token is None else source.with_cancellation(token))


TRUE_FALSE_BOOLS = [True, False]


def fill_random_ints(rand: Any, count: int) -> list[int]:
    return [rand.randint(0, 2_147_483_646) for _ in range(count)]


def fill_random_strings(rand: Any, count: int) -> list[str]:
    import uuid
    values = []
    for _ in range(count):
        s = uuid.uuid4().hex
        values.append(s[: rand.randint(0, len(s) - 1)])
    return values


INT_MIN = -2_147_483_648
INT_MAX = 2_147_483_647

# The [InlineData] rows shared by most VariousValues_MatchesEnumerable theories.
INT_CASES = [
    [],
    [42],
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    [-1, 1, -2, 2, -10, 10],
    [INT_MIN, INT_MAX],
]


def canceled_token() -> CancellationToken:
    """.NET ``new CancellationToken(true)``."""
    from flpit.task import CancellationTokenSource
    source = CancellationTokenSource()
    source.cancel()
    return source.token


async def cancel_while_enumerating(source: AsyncFlpIt[Any]) -> None:
    """.NET: ``await foreach (var _ in source.WithCancellation(cts.Token)) cts.Cancel();`` must throw."""
    from flpit.task import CancellationTokenSource, OperationCanceledError
    cts = CancellationTokenSource()
    with pytest.raises(OperationCanceledError):
        async for _ in source.with_cancellation(cts.token):
            cts.cancel()
