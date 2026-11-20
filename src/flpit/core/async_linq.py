"""
AsyncFlpIt: the ``IAsyncEnumerable<T>`` counterpart to ``FlpIt``.

A lazy asynchronous LINQ pipeline modelled on .NET 10's ``System.Linq.AsyncEnumerable``,
consumed with ``async for`` on the flpit task runtime (``flpit.task``).

Execution model
---------------
* Intermediate operators (``where``, ``select``, ``order_by`` ...) build a deferred pipeline and never
  touch the source. Each enumeration of the result enumerates the source again, so a re-enumerable
  source stays re-enumerable and a one-shot source (an async generator object) stays one-shot.
* Terminal operators (``to_list``, ``first``, ``count`` ...) return a ``flpit.task.Task``, the
  counterpart of .NET's ``ValueTask``: ``await query.to_list()`` inside a coroutine, or
  ``query.to_list().result()`` from synchronous code.
* Cancellation flows like .NET's ``[EnumeratorCancellation]`` token: ``get_async_enumerator(token)``
  hands the token to every operator and, through ``AsyncFlpIt.create``, to the source.
  ``with_cancellation(token)`` binds a token for ``async for``; terminal operators take ``token=``.
  As in .NET the operators themselves do not poll the token: they pass it to the source and to
  asynchronous callbacks, which decide when to observe it.
* Every enumerator an operator opens is closed (``aclose()``, .NET ``DisposeAsync``) when that operator
  finishes, fails or short-circuits. Enumerators the pipeline did not create (an async generator
  object or an iterator passed as the source itself) are borrowed and left open, like ``FlpIt.take``.

Callbacks
---------
Every predicate / selector / key selector / accumulator can be synchronous or asynchronous, mirroring the
``Func<..., TResult>`` and ``Func<..., CancellationToken, ValueTask<TResult>>`` overload pairs. An
asynchronous callback is an ``async def`` (detected once, when the operator is built) and receives the
enumeration's ``CancellationToken`` as its last argument::

    query.where(lambda x: x > 0)

    async def is_valid(x: int, token: CancellationToken) -> bool: ...
    query.where(is_valid)
"""
from __future__ import annotations

import builtins
import inspect
import sys
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable, Iterator
from functools import partial, wraps
from operator import itemgetter
from types import AsyncGeneratorType
from typing import Any, Type, Union, cast as typing_cast, overload, override

from flpit.core._index import IndexTuple
from flpit.core._join import JoinTuple
from flpit.core._zip import ZipTuple
from flpit.core.linq import (
    _EXTREME_CHUNK,
    _MISSING,
    _NONE_ORDER_KEY,
    _SENTINEL,
    _Sentinel,
    _extreme_by,
    _extreme_values,
    ArgumentError,
    ArgumentNullError,
    ArgumentOutOfRangeError,
    ElementSelectorNoneError,
    EmptySequenceError,
    FlpList,
    FuncNoneError,
    InnerNoneError,
    MultipleElementsError,
    MultipleMatchesError,
    NoMatchError,
    PredicateNoneError,
    ResultSelectorNoneError,
    SecondNoneError,
    SelectorNoneError,
    SourceNoneError,
    _validate_join_args,
    _decimal_mean,
    dotnet_context,
)
from decimal import Decimal, Inexact, Overflow
from flpit.core._grouping import Grouping
from flpit.core._lookup import Lookup
from flpit.task import CancellationToken, CancellationTokenSource, Task, _close_stream, _is_async_callable, _owner_scope

_NONE_TOKEN = CancellationToken.none()

# --- callback shapes: Func<..., TResult> | Func<..., CancellationToken, ValueTask<TResult>> ---------------
type AsyncPredicate[T] = Callable[[T], bool] | Callable[[T, CancellationToken], Awaitable[bool]]
type AsyncSelector[T, R] = Callable[[T], R] | Callable[[T, CancellationToken], Awaitable[R]]
type AsyncSelector2[T1, T2, R] = Callable[[T1, T2], R] | Callable[[T1, T2, CancellationToken], Awaitable[R]]
type AsyncSource[T] = AsyncIterable[T] | Iterable[T]


def _token(token: CancellationToken | None) -> CancellationToken:
    if token is None:
        return _NONE_TOKEN
    if not isinstance(token, CancellationToken):
        raise TypeError("token must be a CancellationToken")
    return token


async def _aclose(enumerator: Any) -> None:
    """``DisposeAsync``: close an enumerator if it can be closed (an ``@async_flpit`` one inner streams first)."""
    if type(enumerator) is AsyncGeneratorType:
        await _close_stream(enumerator)
        return
    close = getattr(enumerator, "aclose", None)
    if close is not None:
        await close()


# =============================================================================
# Sources
# =============================================================================
class AsyncEnumerator[T](AsyncIterator[T]):
    """
    The enumerator ``AsyncFlpIt.get_async_enumerator()`` returns (.NET ``IAsyncEnumerator<T>``).

    Iterate it with ``async for`` and close it with ``aclose()`` (.NET ``DisposeAsync``), or let
    ``async with`` close it when the block is left, however it is left (.NET ``await using``).
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: AsyncIterator[T]) -> None:
        self._inner = inner

    def __aiter__(self) -> AsyncEnumerator[T]:
        return self

    def __anext__(self) -> Awaitable[T]:
        return self._inner.__anext__()

    async def aclose(self) -> None:
        """Close the enumeration and everything it opened (.NET ``DisposeAsync``)."""
        await _aclose(self._inner)

    async def __aenter__(self) -> AsyncEnumerator[T]:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()


class _BorrowedAsyncIterator[T](AsyncIterator[T]):
    """An enumerator the pipeline did not create (``__aiter__`` returned the source itself): never closed."""
    __slots__ = ("_inner",)

    def __init__(self, inner: AsyncIterator[T]) -> None:
        self._inner = inner

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    def __anext__(self) -> Awaitable[T]:
        return self._inner.__anext__()

    async def aclose(self) -> None:
        pass


class _EmptyAsyncIterator(AsyncEnumerator[Any]):
    """The shared enumerator of ``AsyncFlpIt.empty()``; .NET hands out one singleton too."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(self)

    @override
    def __aiter__(self) -> AsyncEnumerator[Any]:
        return self

    @override
    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    @override
    async def aclose(self) -> None:
        pass


_EMPTY_ENUMERATOR = _EmptyAsyncIterator()



async def _from_iterable[T](source: Iterable[T], token: CancellationToken) -> AsyncIterator[T]:
    """``ToAsyncEnumerable``: each enumeration iterates ``source`` once; owned iterators are closed."""
    iterator = iter(source)
    try:
        for item in iterator:
            yield item
    finally:
        if iterator is not source:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()


def _from_async_iterable[T](source: AsyncIterable[T], token: CancellationToken) -> AsyncIterator[T]:
    enumerator = source.__aiter__()
    return _BorrowedAsyncIterator(enumerator) if enumerator is source else enumerator


def _factory_for[T](source: Any) -> Callable[[CancellationToken], AsyncIterator[T]]:
    if isinstance(source, AsyncFlpIt):
        return typing_cast(Callable[[CancellationToken], AsyncIterator[T]], source._factory)
    get_async_enumerator = getattr(source, "get_async_enumerator", None)
    if callable(get_async_enumerator):
        return typing_cast(Callable[[CancellationToken], AsyncIterator[T]], get_async_enumerator)
    if hasattr(type(source), "__aiter__"):
        return partial(_from_async_iterable, source)
    if hasattr(type(source), "__iter__"):
        return partial(_from_iterable, source)
    raise TypeError(f"'{type(source).__name__}' object is neither async iterable nor iterable")


def _as_async[T](source: AsyncSource[T]) -> AsyncFlpIt[T]:
    return source if isinstance(source, AsyncFlpIt) else AsyncFlpIt(source)


def _node[T](impl: Callable[..., AsyncIterator[T]], *args: Any) -> AsyncFlpIt[T]:
    """Deferred operator node: ``impl(*args, token)`` is called once per enumeration."""
    return AsyncFlpIt._wrap(partial(impl, *args))


async def _collect[T](source: AsyncFlpIt[T], token: CancellationToken) -> list[T]:
    enumerator = source._get_async_enumerator(token)
    try:
        return [item async for item in enumerator]
    finally:
        await _aclose(enumerator)


async def _keys_for(items: list[Any], selector: Any, is_async: bool, token: CancellationToken) -> list[Any]:
    if is_async:
        return [await selector(item, token) for item in items]
    return list(map(selector, items))


async def _join_lookup(
        inner: AsyncFlpIt[Any], key_selector: Any, token: CancellationToken, keep_none: bool = False
) -> dict[Any, list[Any]]:
    """Hash lookup key -> inner elements, keys in first-appearance order (``AsyncLookup.CreateForJoinAsync``)."""
    is_async = _is_async_callable(key_selector)
    lookup: dict[Any, list[Any]] = {}
    enumerator = inner._get_async_enumerator(token)
    try:
        async for item in enumerator:
            key = await key_selector(item, token) if is_async else key_selector(item)
            if key is not None or keep_none:
                lookup.setdefault(key, []).append(item)
    finally:
        await _aclose(enumerator)
    return lookup


# =============================================================================
# Deferred operator implementations (one async generator per enumeration)
# =============================================================================
async def _where_impl(source: AsyncFlpIt[Any], predicate: Any, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        if _is_async_callable(predicate):
            async for item in e:
                if await predicate(item, token):
                    yield item
        else:
            async for item in e:
                if predicate(item):
                    yield item
    finally:
        await _aclose(e)


async def _select_impl(source: AsyncFlpIt[Any], selector: Any, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        if _is_async_callable(selector):
            async for item in e:
                yield await selector(item, token)
        else:
            async for item in e:
                yield selector(item)
    finally:
        await _aclose(e)


async def _select_many_impl(source: AsyncFlpIt[Any], selector: Any, token: CancellationToken) -> AsyncIterator[Any]:
    is_async = _is_async_callable(selector)
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            inner = await selector(item, token) if is_async else selector(item)
            if inner is None:
                raise ArgumentNullError("source")
            if hasattr(type(inner), "__aiter__") or isinstance(inner, AsyncFlpIt):
                inner_e = _as_async(inner)._get_async_enumerator(token)
                try:
                    async for sub in inner_e:
                        yield sub
                finally:
                    await _aclose(inner_e)
            else:
                for sub in inner:
                    yield sub
    finally:
        await _aclose(e)


async def _index_impl(source: AsyncFlpIt[Any], token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        position = 0
        async for item in e:
            yield IndexTuple(position, item)
            position += 1
    finally:
        await _aclose(e)


async def _skip_impl(source: AsyncFlpIt[Any], count: int, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        remaining = count
        while remaining > 0:
            try:
                await e.__anext__()
            except StopAsyncIteration:
                return
            remaining -= 1
        async for item in e:
            yield item
    finally:
        await _aclose(e)


async def _take_impl(source: AsyncFlpIt[Any], count: int, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        remaining = count
        async for item in e:
            yield item
            remaining -= 1
            if remaining == 0:
                break
    finally:
        await _aclose(e)


async def _skip_last_impl(source: AsyncFlpIt[Any], count: int, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        queue: deque[Any] = deque()
        async for item in e:
            if len(queue) == count:
                yield queue.popleft()
            queue.append(item)
    finally:
        await _aclose(e)


async def _take_last_impl(source: AsyncFlpIt[Any], count: int, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        queue: deque[Any] = deque(maxlen=min(count, sys.maxsize))
        async for item in e:
            queue.append(item)
    finally:
        await _aclose(e)
    for item in queue:
        yield item


async def _default_if_empty_impl(source: AsyncFlpIt[Any], default: Any, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        empty = True
        async for item in e:
            empty = False
            yield item
        if empty:
            yield default
    finally:
        await _aclose(e)


_VALUE_TYPES = (int, float, bool, complex)


async def _cast_impl(source: AsyncFlpIt[Any], target_type: type, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            if item is None:
                if target_type in _VALUE_TYPES:
                    raise AttributeError("Cannot unbox None to a non-nullable value type")
            elif not isinstance(item, target_type):
                raise TypeError(
                    f"Cannot cast element {item!r} of type {type(item).__name__} to {target_type.__name__}"
                )
            yield item
    finally:
        await _aclose(e)


async def _of_type_impl(source: AsyncFlpIt[Any], target_type: type, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            if item is not None and isinstance(item, target_type):
                yield item
    finally:
        await _aclose(e)


async def _distinct_by_impl(source: AsyncFlpIt[Any], key_selector: Any, token: CancellationToken) -> AsyncIterator[Any]:
    is_async = key_selector is not None and _is_async_callable(key_selector)
    seen: set[Any] = set()
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            if key_selector is None:
                key = item
            else:
                key = await key_selector(item, token) if is_async else key_selector(item)
            if key not in seen:
                seen.add(key)
                yield item
    finally:
        await _aclose(e)


async def _except_by_impl(
        source: AsyncFlpIt[Any], second: AsyncFlpIt[Any], key_selector: Any, token: CancellationToken
) -> AsyncIterator[Any]:
    # .NET: the first element of `source` is requested before `second` is buffered.
    is_async = key_selector is not None and _is_async_callable(key_selector)
    e = source._get_async_enumerator(token)
    try:
        try:
            item = await e.__anext__()
        except StopAsyncIteration:
            return
        seen: set[Any] = set(await _collect(second, token))
        while True:
            if key_selector is None:
                key = item
            else:
                key = await key_selector(item, token) if is_async else key_selector(item)
            if key not in seen:
                seen.add(key)
                yield item
            try:
                item = await e.__anext__()
            except StopAsyncIteration:
                return
    finally:
        await _aclose(e)


async def _intersect_impl(source: AsyncFlpIt[Any], second: AsyncFlpIt[Any], token: CancellationToken) -> AsyncIterator[Any]:
    # .NET: `second` is buffered first; an empty `second` never enumerates `source`.
    remaining: set[Any] = set(await _collect(second, token))
    if not remaining:
        return
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            if item in remaining:
                remaining.remove(item)
                yield item
    finally:
        await _aclose(e)


async def _union_impl(source: AsyncFlpIt[Any], second: AsyncFlpIt[Any], token: CancellationToken) -> AsyncIterator[Any]:
    seen: set[Any] = set()
    for part in (source, second):
        e = part._get_async_enumerator(token)
        try:
            async for item in e:
                if item not in seen:
                    seen.add(item)
                    yield item
        finally:
            await _aclose(e)


class _Node:
    """Persistent single-linked list node (.NET ``SingleLinkedNode<T>``): O(1) extension, shared tails."""
    __slots__ = ("item", "next")

    def __init__(self, item: Any, next_node: _Node | None) -> None:
        self.item = item
        self.next = next_node

    def to_list_reversed(self) -> list[Any]:
        """Items from the oldest to the newest node."""
        items: list[Any] = []
        node: _Node | None = self
        while node is not None:
            items.append(node.item)
            node = node.next
        items.reverse()
        return items

    def to_list(self) -> list[Any]:
        """Items from the newest to the oldest node."""
        items = self.to_list_reversed()
        items.reverse()
        return items


async def _append_prepend_impl(
        source: AsyncFlpIt[Any], prepended: _Node | None, appended: _Node | None, token: CancellationToken
) -> AsyncIterator[Any]:
    if prepended is not None:
        for item in prepended.to_list():
            yield item
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            yield item
    finally:
        await _aclose(e)
    if appended is not None:
        for item in appended.to_list_reversed():
            yield item


async def _concat_impl(sources: _Node, token: CancellationToken) -> AsyncIterator[Any]:
    for part in sources.to_list_reversed():
        e = part._get_async_enumerator(token)
        try:
            async for item in e:
                yield item
        finally:
            await _aclose(e)


async def _reverse_impl(source: AsyncFlpIt[Any], token: CancellationToken) -> AsyncIterator[Any]:
    for item in reversed(await _collect(source, token)):
        yield item


async def _chunk_impl(source: AsyncFlpIt[Any], size: int, token: CancellationToken) -> AsyncIterator[Any]:
    e = source._get_async_enumerator(token)
    try:
        current: list[Any] = []
        async for item in e:
            current.append(item)
            if len(current) == size:
                yield FlpList(current)
                current = []
        if current:
            yield FlpList(current)
    finally:
        await _aclose(e)


async def _zip_impl(
        first: AsyncFlpIt[Any], second: AsyncFlpIt[Any], result_selector: Any, token: CancellationToken
) -> AsyncIterator[Any]:
    is_async = result_selector is not _SENTINEL and _is_async_callable(result_selector)
    e1 = first._get_async_enumerator(token)
    try:
        e2 = second._get_async_enumerator(token)
        try:
            while True:
                try:
                    a = await e1.__anext__()
                    b = await e2.__anext__()
                except StopAsyncIteration:
                    return
                if result_selector is _SENTINEL:
                    yield ZipTuple(a, b)
                elif is_async:
                    yield await result_selector(a, b, token)
                else:
                    yield result_selector(a, b)
        finally:
            await _aclose(e2)
    finally:
        await _aclose(e1)


async def _result(selector: Any, is_async: bool, a: Any, b: Any, token: CancellationToken) -> Any:
    return await selector(a, b, token) if is_async else selector(a, b)


async def _join_impl(
        outer: AsyncFlpIt[Any], inner: AsyncFlpIt[Any], outer_key: Any, inner_key: Any, result_selector: Any,
        token: CancellationToken,
) -> AsyncIterator[Any]:
    # .NET: the first outer element is requested before `inner` is buffered; an empty lookup stops.
    outer_async = _is_async_callable(outer_key)
    has_selector = result_selector is not _SENTINEL
    result_async = has_selector and _is_async_callable(result_selector)
    e = outer._get_async_enumerator(token)
    try:
        try:
            item = await e.__anext__()
        except StopAsyncIteration:
            return
        lookup = await _join_lookup(inner, inner_key, token)
        if not lookup:
            return
        while True:
            key = await outer_key(item, token) if outer_async else outer_key(item)
            matches = None if key is None else lookup.get(key)
            if matches is not None:
                for match in matches:
                    if has_selector:
                        yield await _result(result_selector, result_async, item, match, token)
                    else:
                        yield JoinTuple(item, match)
            try:
                item = await e.__anext__()
            except StopAsyncIteration:
                return
    finally:
        await _aclose(e)


async def _left_join_impl(
        outer: AsyncFlpIt[Any], inner: AsyncFlpIt[Any], outer_key: Any, inner_key: Any, result_selector: Any,
        token: CancellationToken,
) -> AsyncIterator[Any]:
    outer_async = _is_async_callable(outer_key)
    has_selector = result_selector is not _SENTINEL
    result_async = has_selector and _is_async_callable(result_selector)
    e = outer._get_async_enumerator(token)
    try:
        try:
            item = await e.__anext__()
        except StopAsyncIteration:
            return
        lookup = await _join_lookup(inner, inner_key, token)
        while True:
            key = await outer_key(item, token) if outer_async else outer_key(item)
            matches = None if key is None else lookup.get(key)
            for match in (None,) if matches is None else matches:
                if has_selector:
                    yield await _result(result_selector, result_async, item, match, token)
                else:
                    yield JoinTuple(item, match)
            try:
                item = await e.__anext__()
            except StopAsyncIteration:
                return
    finally:
        await _aclose(e)


async def _full_join_impl(
        outer: AsyncFlpIt[Any], inner: AsyncFlpIt[Any], outer_key: Any, inner_key: Any, result_selector: Any,
        token: CancellationToken,
) -> AsyncIterator[Any]:
    # .NET: `inner` is buffered first (None keys preserved, never matching); unmatched inner
    # elements follow the outer sequence, grouped by key in order of first key appearance.
    outer_async = _is_async_callable(outer_key)
    has_selector = result_selector is not _SENTINEL
    result_async = has_selector and _is_async_callable(result_selector)
    lookup = await _join_lookup(inner, inner_key, token, keep_none=True)
    matched: set[Any] = set()
    e = outer._get_async_enumerator(token)
    try:
        async for item in e:
            key = await outer_key(item, token) if outer_async else outer_key(item)
            matches = None if key is None else lookup.get(key)
            if matches is not None:
                matched.add(key)
            for match in (None,) if matches is None else matches:
                if has_selector:
                    yield await _result(result_selector, result_async, item, match, token)
                else:
                    yield JoinTuple(item, match)
    finally:
        await _aclose(e)
    for key, group in lookup.items():
        if key is None or key not in matched:
            for match in group:
                if has_selector:
                    yield await _result(result_selector, result_async, None, match, token)
                else:
                    yield JoinTuple(None, match)


async def _cross_join_impl(
        outer: AsyncFlpIt[Any], inner: AsyncFlpIt[Any], result_selector: Any, token: CancellationToken
) -> AsyncIterator[Any]:
    has_selector = result_selector is not _SENTINEL
    result_async = has_selector and _is_async_callable(result_selector)
    inner_items = await _collect(inner, token)
    if not inner_items:
        return
    e = outer._get_async_enumerator(token)
    try:
        async for item in e:
            for match in inner_items:
                if has_selector:
                    yield await _result(result_selector, result_async, item, match, token)
                else:
                    yield JoinTuple(item, match)
    finally:
        await _aclose(e)


async def _group_join_impl(
        outer: AsyncFlpIt[Any], inner: AsyncFlpIt[Any], outer_key: Any, inner_key: Any, result_selector: Any,
        token: CancellationToken,
) -> AsyncIterator[Any]:
    # .NET: `inner` is buffered once the outer sequence yields its first element.
    outer_async = _is_async_callable(outer_key)
    has_selector = result_selector is not _SENTINEL
    result_async = has_selector and _is_async_callable(result_selector)
    lookup: dict[Any, list[Any]] | None = None
    e = outer._get_async_enumerator(token)
    try:
        async for item in e:
            if lookup is None:
                lookup = await _join_lookup(inner, inner_key, token)
            key = await outer_key(item, token) if outer_async else outer_key(item)
            matches = () if key is None else lookup.get(key, ())
            if not has_selector:
                yield Grouping(item, matches)
            else:
                yield await _result(result_selector, result_async, item, FlpList(matches), token)
    finally:
        await _aclose(e)


async def _group_by_impl(source: AsyncFlpIt[Any], key_selector: Any, token: CancellationToken) -> AsyncIterator[Any]:
    groups = await _to_groups(source, key_selector, _SENTINEL, token)
    for key, items in groups.items():
        yield Grouping(key, items)


async def _to_groups(
        source: AsyncFlpIt[Any], key_selector: Any, element_selector: Any, token: CancellationToken
) -> dict[Any, list[Any]]:
    key_async = _is_async_callable(key_selector)
    has_element = element_selector is not _SENTINEL
    element_async = has_element and _is_async_callable(element_selector)
    groups: dict[Any, list[Any]] = {}
    e = source._get_async_enumerator(token)
    try:
        async for item in e:
            key = await key_selector(item, token) if key_async else key_selector(item)
            if has_element:
                item = await element_selector(item, token) if element_async else element_selector(item)
            groups.setdefault(key, []).append(item)
    finally:
        await _aclose(e)
    return groups


# =============================================================================
# AsyncFlpIt
# =============================================================================
class AsyncFlpIt[TItem](AsyncIterable[TItem]):
    """
    | Fluent Async Iterable
    Lazy asynchronous query over an async (or sync) iterable, inspired by .NET's
    ``IAsyncEnumerable<T>`` and ``System.Linq.AsyncEnumerable``.

    Consume it with ``async for`` on the flpit runtime; terminal operators return a ``Task``.
    Multiple enumeration is supported when the underlying source is re-enumerable;
    one-shot async generators remain one-shot.
    """
    __slots__ = ("_factory",)

    _factory: Callable[[CancellationToken], AsyncIterator[TItem]]

    def __init__(self, source: AsyncSource[TItem]) -> None:
        if source is None:
            raise SourceNoneError()
        self._factory = _factory_for(source)

    @classmethod
    def _wrap[T](cls, factory: Callable[[CancellationToken], AsyncIterator[T]]) -> AsyncFlpIt[T]:
        node: AsyncFlpIt[T] = object.__new__(AsyncFlpIt)
        node._factory = factory
        return node

    # --- construction --------------------------------------------------------------------------

    @staticmethod
    def create[T](factory: Callable[[CancellationToken], AsyncIterator[T]]) -> AsyncFlpIt[T]:
        """
        Creates a sequence from an enumerator factory that receives the enumeration's cancellation token
        (the counterpart of an ``async`` iterator with an ``[EnumeratorCancellation]`` parameter)::

            async def numbers(token: CancellationToken):
                for i in range(10):
                    await Task.delay(0.1, token=token)
                    yield i

            query = AsyncFlpIt.create(numbers)

        ``factory`` is called once per enumeration. ``@async_flpit`` does the same for an async
        generator function, with its ordinary parameters.
        """
        if factory is None:
            raise ArgumentNullError("factory")
        return AsyncFlpIt._wrap(factory)

    @staticmethod
    def empty() -> AsyncFlpIt[Any]:
        """Returns the shared empty sequence (.NET ``AsyncEnumerable.Empty<T>()``)."""
        return _EMPTY

    @staticmethod
    def range(start: int, count: int) -> AsyncFlpIt[int]:
        """Generates a sequence of ``count`` consecutive integers starting at ``start`` (``AsyncEnumerable.Range``)."""
        if count == 0:
            return _EMPTY
        if count < 0 or start + count - 1 > 2_147_483_647:
            raise ArgumentOutOfRangeError("count", "Specified argument was out of the range of valid values.")
        return AsyncFlpIt(builtins.range(start, start + count))

    @staticmethod
    def repeat[T](element: T, count: int) -> AsyncFlpIt[T]:
        """Generates a sequence that contains ``element`` ``count`` times (``AsyncEnumerable.Repeat``)."""
        if count == 0:
            return _EMPTY
        if count < 0:
            raise ArgumentOutOfRangeError("count", f"count ('{count}') must be a non-negative value.")

        def _generator() -> Iterator[T]:
            for _ in builtins.range(count):
                yield element

        return AsyncFlpIt(_ReIterable(_generator))

    # --- enumeration ---------------------------------------------------------------------------

    def get_async_enumerator(self, token: CancellationToken | None = None) -> AsyncEnumerator[TItem]:
        """
        Returns a new enumerator that observes ``token`` (.NET ``GetAsyncEnumerator(CancellationToken)``).

        Use it with ``async with`` to close the query, and its source, when the block is left
        (.NET ``await using``)::

            async with query.get_async_enumerator(token) as items:
                async for item in items:
                    if done(item):
                        break
            # closed here, finally blocks included
        """
        enumerator = self._factory(_NONE_TOKEN if token is None else token)
        return enumerator if isinstance(enumerator, AsyncEnumerator) else AsyncEnumerator(enumerator)

    def _get_async_enumerator(self, token: CancellationToken | None = None) -> AsyncIterator[TItem]:
        """``get_async_enumerator`` for the operators: the bare enumerator, no wrapper."""
        return self._factory(_NONE_TOKEN if token is None else token)

    def __aiter__(self) -> AsyncIterator[TItem]:
        return self._factory(_NONE_TOKEN)

    def with_cancellation(self, token: CancellationToken) -> AsyncFlpIt[TItem]:
        """
        Binds ``token`` to every enumeration of the returned sequence (.NET ``WithCancellation``)::

            async for item in query.with_cancellation(cts.token): ...
        """
        bound = _token(token)
        return AsyncFlpIt._wrap(lambda _ignored: self._factory(bound))

    # noinspection unused-parameter
    def as_type[TResult](self, target_type: Type[TResult]) -> AsyncFlpIt[TResult]:
        """Zero-cost static type hint update returning self directly without checks or allocations."""
        return self  # type: ignore[return-value]

    # =====================================================================
    # Deferred operators
    # =====================================================================

    def where(self, predicate: AsyncPredicate[TItem]) -> AsyncFlpIt[TItem]:
        """Filters elements based on a predicate (deferred)."""
        if predicate is None:
            raise PredicateNoneError()
        if self is _EMPTY:
            return self
        return _node(_where_impl, self, predicate)

    def select[TResult](self, selector: AsyncSelector[TItem, TResult]) -> AsyncFlpIt[TResult]:
        """Projects each element into a new form (deferred)."""
        if selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return _EMPTY
        return _node(_select_impl, self, selector)

    def select_many[TResult](
            self,
            selector: AsyncSelector[TItem, Iterable[TResult] | AsyncIterable[TResult]],
    ) -> AsyncFlpIt[TResult]:
        """Projects each element to a sync or async sequence and flattens the results (deferred)."""
        if selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return _EMPTY
        return _node(_select_many_impl, self, selector)

    def index(self) -> AsyncFlpIt[IndexTuple[TItem]]:
        """Pairs every element with its position: ``IndexTuple(index, item)`` (.NET 9 ``Index()``)."""
        if self is _EMPTY:
            return _EMPTY
        return _node(_index_impl, self)

    def skip(self, count: int) -> AsyncFlpIt[TItem]:
        """Bypasses ``count`` elements from the start (deferred)."""
        if self is _EMPTY or count <= 0:
            return self
        return _node(_skip_impl, self, count)

    def take(self, count: int) -> AsyncFlpIt[TItem]:
        """Returns ``count`` contiguous elements from the start; requests no more than ``count`` elements."""
        if self is _EMPTY or count <= 0:
            return _EMPTY
        return _node(_take_impl, self, count)

    def skip_last(self, count: int) -> AsyncFlpIt[TItem]:
        """Omits the last ``count`` elements; buffers at most ``count`` elements (deferred)."""
        if self is _EMPTY or count <= 0:
            return self
        return _node(_skip_last_impl, self, count)

    def take_last(self, count: int) -> AsyncFlpIt[TItem]:
        """Returns the last ``count`` elements; consumes the source and keeps at most ``count`` elements."""
        if self is _EMPTY or count <= 0:
            return _EMPTY
        return _node(_take_last_impl, self, count)

    def default_if_empty[TResult](self, default: TResult) -> AsyncFlpIt[TItem | TResult]:
        """Returns the elements, or a single ``default`` if the sequence is empty (deferred)."""
        return _node(_default_if_empty_impl, self, default)

    def cast[TResult](self, target_type: Type[TResult]) -> AsyncFlpIt[TResult]:
        """Casts elements to ``target_type`` or raises ``TypeError`` while enumerating."""
        if self is _EMPTY:
            return _EMPTY
        return _node(_cast_impl, self, target_type)

    def of_type[TResult](self, target_type: Type[TResult]) -> AsyncFlpIt[TResult]:
        """Filters the elements that are instances of ``target_type`` (``None`` never is)."""
        if self is _EMPTY:
            return _EMPTY
        return _node(_of_type_impl, self, target_type)

    def distinct(self) -> AsyncFlpIt[TItem]:
        """Returns distinct elements in encounter order (deferred)."""
        if self is _EMPTY:
            return self
        return _node(_distinct_by_impl, self, None)

    def distinct_by[TKey](self, key_selector: AsyncSelector[TItem, TKey]) -> AsyncFlpIt[TItem]:
        """Returns the first element of every distinct key, in encounter order (deferred)."""
        if key_selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return self
        return _node(_distinct_by_impl, self, key_selector)

    def except_(self, second: AsyncSource[TItem]) -> AsyncFlpIt[TItem]:
        """
        Set difference (named ``except_``: ``except`` is reserved). Like .NET, the first element of this
        sequence is requested before ``second`` is buffered, so an empty sequence never enumerates ``second``.
        """
        if second is None:
            raise SecondNoneError()
        if self is _EMPTY:
            return self
        return _node(_except_by_impl, self, _as_async(second), None)

    def except_by[TKey](
            self, second: AsyncSource[TKey], key_selector: AsyncSelector[TItem, TKey]
    ) -> AsyncFlpIt[TItem]:
        """Set difference by key: elements, distinct by key, whose key does not appear in ``second``."""
        if second is None:
            raise SecondNoneError()
        if key_selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return self
        return _node(_except_by_impl, self, _as_async(second), key_selector)

    def intersect(self, second: AsyncSource[TItem]) -> AsyncFlpIt[TItem]:
        """Set intersection; ``second`` is buffered first and an empty ``second`` never enumerates this sequence."""
        if second is None:
            raise SecondNoneError()
        second_it = _as_async(second)
        if self is _EMPTY or second_it is _EMPTY:
            return _EMPTY
        return _node(_intersect_impl, self, second_it)

    def union(self, second: AsyncSource[TItem]) -> AsyncFlpIt[TItem]:
        """Set union: distinct elements of this sequence followed by the new ones of ``second``; both streamed."""
        if second is None:
            raise SecondNoneError()
        second_it = _as_async(second)
        if self is _EMPTY and second_it is _EMPTY:
            return _EMPTY
        return _node(_union_impl, self, second_it)

    def concat(self, second: AsyncSource[TItem]) -> AsyncFlpIt[TItem]:
        """Concatenates two sequences (deferred)."""
        if second is None:
            raise SecondNoneError()
        second_it = _as_async(second)
        if self is _EMPTY:
            return second_it
        if second_it is _EMPTY:
            return self
        return _ConcatIt(_Node(second_it, _Node(self, None)))

    def append(self, element: TItem) -> AsyncFlpIt[TItem]:
        """Appends an element to the end of the sequence (deferred; chains of appends/prepends coalesce)."""
        return _AppendPrependIt(self, None, _Node(element, None))

    def prepend(self, element: TItem) -> AsyncFlpIt[TItem]:
        """Prepends an element to the beginning of the sequence (deferred; chains coalesce)."""
        return _AppendPrependIt(self, _Node(element, None), None)

    def reverse(self) -> AsyncFlpIt[TItem]:
        """Returns the elements in reverse order; buffers the source when enumerated."""
        if self is _EMPTY:
            return self
        return _node(_reverse_impl, self)

    def chunk(self, size: int) -> AsyncFlpIt[FlpList[TItem]]:
        """Splits the elements into ``FlpList`` chunks of at most ``size`` elements."""
        if size <= 0:
            raise ArgumentOutOfRangeError("Specified argument was out of the range of valid values. (Parameter 'size')")
        if self is _EMPTY:
            return _EMPTY
        return _node(_chunk_impl, self, size)

    @overload
    def zip[TOther](self, second: AsyncSource[TOther]) -> AsyncFlpIt[ZipTuple[TItem, TOther]]: ...

    @overload
    def zip[TOther, TResult](
            self, second: AsyncSource[TOther], result_selector: AsyncSelector2[TItem, TOther, TResult]
    ) -> AsyncFlpIt[TResult]: ...

    def zip(self, second: AsyncSource[Any], result_selector: Any = _SENTINEL) -> AsyncFlpIt[Any]:
        """Combines corresponding elements of two sequences; stops at the end of the shorter one."""
        if second is None:
            raise SecondNoneError()
        if result_selector is None:
            raise ResultSelectorNoneError()
        second_it = _as_async(second)
        if self is _EMPTY or second_it is _EMPTY:
            return _EMPTY
        return _node(_zip_impl, self, second_it, result_selector)

    @overload
    def join[TInner](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
    ) -> AsyncFlpIt[JoinTuple[TItem, TInner]]: ...

    @overload
    def join[TInner, TResult](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
            result_selector: AsyncSelector2[TItem, TInner, TResult],
    ) -> AsyncFlpIt[TResult]: ...

    def join(
            self, inner: AsyncSource[Any], outer_key_selector: Any, inner_key_selector: Any,
            result_selector: Any = _SENTINEL,
    ) -> AsyncFlpIt[Any]:
        """
        Inner join on matching keys (``None`` keys never match). Like .NET, the first outer element is
        requested before ``inner`` is buffered into a hash lookup; if the lookup is empty the outer
        sequence is not enumerated further.
        """
        _validate_join_args(inner, outer_key_selector, inner_key_selector, result_selector)
        inner_it = _as_async(inner)
        if self is _EMPTY or inner_it is _EMPTY:
            return _EMPTY
        return _node(_join_impl, self, inner_it, outer_key_selector, inner_key_selector, result_selector)

    @overload
    def left_join[TInner](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
    ) -> AsyncFlpIt[JoinTuple[TItem, TInner | None]]: ...

    @overload
    def left_join[TInner, TResult](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
            result_selector: AsyncSelector2[TItem, TInner | None, TResult],
    ) -> AsyncFlpIt[TResult]: ...

    def left_join(
            self, inner: AsyncSource[Any], outer_key_selector: Any, inner_key_selector: Any,
            result_selector: Any = _SENTINEL,
    ) -> AsyncFlpIt[Any]:
        """Left outer join (.NET ``LeftJoin``): unmatched outer elements are paired with ``None``."""
        _validate_join_args(inner, outer_key_selector, inner_key_selector, result_selector)
        if self is _EMPTY:
            return _EMPTY
        return _node(_left_join_impl, self, _as_async(inner), outer_key_selector, inner_key_selector, result_selector)

    @overload
    def full_join[TInner](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
    ) -> AsyncFlpIt[JoinTuple[TItem | None, TInner | None]]: ...

    @overload
    def full_join[TInner, TResult](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
            result_selector: AsyncSelector2[TItem | None, TInner | None, TResult],
    ) -> AsyncFlpIt[TResult]: ...

    def full_join(
            self, inner: AsyncSource[Any], outer_key_selector: Any, inner_key_selector: Any,
            result_selector: Any = _SENTINEL,
    ) -> AsyncFlpIt[Any]:
        """
        Full outer join (.NET ``FullJoin``): the left join, followed by the unmatched inner elements
        paired with ``None``. ``inner`` is buffered first; unmatched inner elements are produced grouped
        by key, in order of first key appearance (elements with a ``None`` key never match).
        """
        _validate_join_args(inner, outer_key_selector, inner_key_selector, result_selector)
        inner_it = _as_async(inner)
        if self is _EMPTY and inner_it is _EMPTY:
            return _EMPTY
        return _node(_full_join_impl, self, inner_it, outer_key_selector, inner_key_selector, result_selector)

    @overload
    def cross_join[TInner](self, inner: AsyncSource[TInner]) -> AsyncFlpIt[JoinTuple[TItem, TInner]]: ...

    @overload
    def cross_join[TInner, TResult](
            self, inner: AsyncSource[TInner], result_selector: AsyncSelector2[TItem, TInner, TResult]
    ) -> AsyncFlpIt[TResult]: ...

    def cross_join(self, inner: AsyncSource[Any], result_selector: Any = _SENTINEL) -> AsyncFlpIt[Any]:
        """Cartesian product (no .NET equivalent); ``inner`` is buffered once per enumeration."""
        if inner is None:
            raise InnerNoneError()
        if result_selector is None:
            raise ResultSelectorNoneError()
        return _node(_cross_join_impl, self, _as_async(inner), result_selector)

    @overload
    def group_join[TInner](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
    ) -> AsyncFlpIt[Grouping[TItem, TInner]]: ...

    @overload
    def group_join[TInner, TResult](
            self, inner: AsyncSource[TInner],
            outer_key_selector: AsyncSelector[TItem, Any], inner_key_selector: AsyncSelector[TInner, Any],
            result_selector: AsyncSelector2[TItem, FlpList[TInner], TResult],
    ) -> AsyncFlpIt[TResult]: ...

    def group_join(
            self, inner: AsyncSource[Any], outer_key_selector: Any, inner_key_selector: Any,
            result_selector: Any = _SENTINEL,
    ) -> AsyncFlpIt[Any]:
        """
        Group join (.NET ``GroupJoin``): one result per outer element with the group of its matches.
        Without a result selector a ``Grouping`` keyed by the outer element is yielded. ``inner`` is
        buffered once the outer sequence produces its first element.
        """
        _validate_join_args(inner, outer_key_selector, inner_key_selector, result_selector)
        if self is _EMPTY:
            return _EMPTY
        return _node(_group_join_impl, self, _as_async(inner), outer_key_selector, inner_key_selector, result_selector)

    def group_by[TKey](self, key_selector: AsyncSelector[TItem, TKey]) -> AsyncFlpIt[Grouping[TKey, TItem]]:
        """Groups the elements by key; groups appear in order of first key appearance (buffers when enumerated)."""
        if key_selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return _EMPTY
        return _node(_group_by_impl, self, key_selector)

    def order_by(self, key_selector: AsyncSelector[TItem, Any]) -> OrderedAsyncIt[TItem]:
        """Stable ascending sort by key (``None`` keys first); buffers when enumerated."""
        if key_selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return _EMPTY
        return OrderedAsyncIt(self, ((key_selector, False),))

    def order_by_descending(self, key_selector: AsyncSelector[TItem, Any]) -> OrderedAsyncIt[TItem]:
        """Stable descending sort by key; buffers when enumerated."""
        if key_selector is None:
            raise SelectorNoneError()
        if self is _EMPTY:
            return _EMPTY
        return OrderedAsyncIt(self, ((key_selector, True),))

    # =====================================================================
    # Terminal operators (return a Task)
    # =====================================================================

    def to_list(self, *, token: CancellationToken | None = None) -> Task[FlpList[TItem]]:
        """Materializes the sequence into a ``FlpList`` (.NET ``ToListAsync``)."""
        return Task.run(self._to_list, _token(token))

    async def _to_list(self, token: CancellationToken) -> FlpList[TItem]:
        return FlpList(await _collect(self, token))

    def any(
            self, predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL, *, token: CancellationToken | None = None
    ) -> Task[bool]:
        """Whether the sequence has any element / any element satisfies ``predicate``; stops at the first match."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._any, predicate, _token(token))

    async def _any(self, predicate: Any, token: CancellationToken) -> bool:
        e = self._get_async_enumerator(token)
        try:
            if predicate is _SENTINEL:
                try:
                    await e.__anext__()
                except StopAsyncIteration:
                    return False
                return True
            is_async = _is_async_callable(predicate)
            async for item in e:
                if (await predicate(item, token)) if is_async else predicate(item):
                    return True
            return False
        finally:
            await _aclose(e)

    def all(self, predicate: AsyncPredicate[TItem], *, token: CancellationToken | None = None) -> Task[bool]:
        """Whether every element satisfies ``predicate`` (``True`` when empty); stops at the first failure."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._all, predicate, _token(token))

    async def _all(self, predicate: Any, token: CancellationToken) -> bool:
        is_async = _is_async_callable(predicate)
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                if not ((await predicate(item, token)) if is_async else predicate(item)):
                    return False
            return True
        finally:
            await _aclose(e)

    def contains(self, value: TItem, *, token: CancellationToken | None = None) -> Task[bool]:
        """Whether the sequence contains ``value`` (``==``); stops at the first match."""
        return Task.run(self._contains, value, _token(token))

    async def _contains(self, value: Any, token: CancellationToken) -> bool:
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                if item == value:
                    return True
            return False
        finally:
            await _aclose(e)

    def count(
            self, predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL, *, token: CancellationToken | None = None
    ) -> Task[int]:
        """Counts the elements, optionally only those satisfying ``predicate``."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._count, predicate, _token(token))

    async def _count(self, predicate: Any, token: CancellationToken) -> int:
        count = 0
        e = self._get_async_enumerator(token)
        try:
            if predicate is _SENTINEL:
                async for _ in e:
                    count += 1
            elif _is_async_callable(predicate):
                async for item in e:
                    if await predicate(item, token):
                        count += 1
            else:
                async for item in e:
                    if predicate(item):
                        count += 1
        finally:
            await _aclose(e)
        return count

    def element_at(self, index: int, *, token: CancellationToken | None = None) -> Task[TItem]:
        """Returns the element at ``index``; requests no element beyond it."""
        return Task.run(self._element_at, index, _token(token))

    async def _element_at(self, index: int, token: CancellationToken) -> TItem:
        if index >= 0:
            e = self._get_async_enumerator(token)
            try:
                position = 0
                async for item in e:
                    if position == index:
                        return item
                    position += 1
            finally:
                await _aclose(e)
        raise ArgumentOutOfRangeError("index")

    async def _first_match(self, predicate: Any, token: CancellationToken) -> Any:
        e = self._get_async_enumerator(token)
        try:
            if predicate is _SENTINEL:
                try:
                    return await e.__anext__()
                except StopAsyncIteration:
                    return _MISSING
            is_async = _is_async_callable(predicate)
            async for item in e:
                if (await predicate(item, token)) if is_async else predicate(item):
                    return item
            return _MISSING
        finally:
            await _aclose(e)

    def first(
            self, predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL, *, token: CancellationToken | None = None
    ) -> Task[TItem]:
        """Returns the first element (matching ``predicate``); raises if there is none."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._first, predicate, _token(token))

    async def _first(self, predicate: Any, token: CancellationToken) -> TItem:
        found = await self._first_match(predicate, token)
        if found is _MISSING:
            raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()
        return found

    def first_or_default[TResult](
            self,
            default: TResult,
            predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL,
            *,
            token: CancellationToken | None = None,
    ) -> Task[TItem | TResult]:
        """Returns the first element (matching ``predicate``), or ``default``."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._first_or_default, default, predicate, _token(token))

    async def _first_or_default(self, default: Any, predicate: Any, token: CancellationToken) -> Any:
        found = await self._first_match(predicate, token)
        return default if found is _MISSING else found

    async def _last_match(self, predicate: Any, token: CancellationToken) -> Any:
        last: Any = _MISSING
        e = self._get_async_enumerator(token)
        try:
            if predicate is _SENTINEL:
                async for item in e:
                    last = item
            elif _is_async_callable(predicate):
                async for item in e:
                    if await predicate(item, token):
                        last = item
            else:
                async for item in e:
                    if predicate(item):
                        last = item
        finally:
            await _aclose(e)
        return last

    def last(
            self, predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL, *, token: CancellationToken | None = None
    ) -> Task[TItem]:
        """Returns the last element (matching ``predicate``); raises if there is none."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._last, predicate, _token(token))

    async def _last(self, predicate: Any, token: CancellationToken) -> TItem:
        found = await self._last_match(predicate, token)
        if found is _MISSING:
            raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()
        return found

    def last_or_default[TResult](
            self,
            default: TResult,
            predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL,
            *,
            token: CancellationToken | None = None,
    ) -> Task[TItem | TResult]:
        """Returns the last element (matching ``predicate``), or ``default``."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._last_or_default, default, predicate, _token(token))

    async def _last_or_default(self, default: Any, predicate: Any, token: CancellationToken) -> Any:
        found = await self._last_match(predicate, token)
        return default if found is _MISSING else found

    async def _single_match(self, predicate: Any, token: CancellationToken) -> Any:
        """The single (matching) element, ``_MISSING`` if none; raises on a second (matching) element."""
        found: Any = _MISSING
        is_async = predicate is not _SENTINEL and _is_async_callable(predicate)
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                if predicate is _SENTINEL or ((await predicate(item, token)) if is_async else predicate(item)):
                    if found is not _MISSING:
                        raise MultipleElementsError() if predicate is _SENTINEL else MultipleMatchesError()
                    found = item
                    if predicate is _SENTINEL:
                        try:
                            await e.__anext__()
                        except StopAsyncIteration:
                            return found
                        raise MultipleElementsError()
        finally:
            await _aclose(e)
        return found

    def single(
            self, predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL, *, token: CancellationToken | None = None
    ) -> Task[TItem]:
        """Returns the only element (matching ``predicate``); raises if there is none or more than one."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._single, predicate, _token(token))

    async def _single(self, predicate: Any, token: CancellationToken) -> TItem:
        found = await self._single_match(predicate, token)
        if found is _MISSING:
            raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()
        return found

    def single_or_default[TResult](
            self,
            default: TResult,
            predicate: AsyncPredicate[TItem] | _Sentinel = _SENTINEL,
            *,
            token: CancellationToken | None = None,
    ) -> Task[TItem | TResult]:
        """Returns the only element (matching ``predicate``) or ``default`` if there is none; raises on more than one."""
        if predicate is None:
            raise PredicateNoneError()
        return Task.run(self._single_or_default, default, predicate, _token(token))

    async def _single_or_default(self, default: Any, predicate: Any, token: CancellationToken) -> Any:
        found = await self._single_match(predicate, token)
        return default if found is _MISSING else found

    @overload
    def aggregate(
            self, func: AsyncSelector2[TItem, TItem, TItem], /, *, token: CancellationToken | None = None
    ) -> Task[TItem]: ...

    @overload
    def aggregate[TAcc](
            self, seed: TAcc, func: AsyncSelector2[TAcc, TItem, TAcc], /, *, token: CancellationToken | None = None
    ) -> Task[TAcc]: ...

    @overload
    def aggregate[TAcc, TResult](
            self,
            seed: TAcc,
            func: AsyncSelector2[TAcc, TItem, TAcc],
            result_selector: AsyncSelector[TAcc, TResult],
            /,
            *,
            token: CancellationToken | None = None,
    ) -> Task[TResult]: ...

    def aggregate(self, *args: Any, token: CancellationToken | None = None) -> Task[Any]:
        """
        Applies an accumulator over the sequence (.NET ``AggregateAsync``)::

            aggregate(func)                         first element is the seed; raises on an empty source
            aggregate(seed, func)
            aggregate(seed, func, result_selector)
        """
        if len(args) == 1:
            (func,) = args
            has_seed, seed, result_selector = False, None, _SENTINEL
        elif len(args) == 2:
            seed, func = args
            has_seed, result_selector = True, _SENTINEL
        elif len(args) == 3:
            seed, func, result_selector = args
            has_seed = True
        else:
            raise TypeError(f"aggregate() takes from 1 to 3 positional arguments but {len(args)} were given")
        if func is None:
            raise FuncNoneError()
        if result_selector is None:
            raise ResultSelectorNoneError()
        return Task.run(self._aggregate, has_seed, seed, func, result_selector, _token(token))

    async def _aggregate(
            self, has_seed: bool, seed: Any, func: Any, result_selector: Any, token: CancellationToken
    ) -> Any:
        is_async = _is_async_callable(func)
        e = self._get_async_enumerator(token)
        try:
            if has_seed:
                accumulator = seed
            else:
                try:
                    accumulator = await e.__anext__()
                except StopAsyncIteration:
                    raise EmptySequenceError() from None
            async for item in e:
                accumulator = (await func(accumulator, item, token)) if is_async else func(accumulator, item)
        finally:
            await _aclose(e)
        if result_selector is _SENTINEL:
            return accumulator
        if _is_async_callable(result_selector):
            return await result_selector(accumulator, token)
        return result_selector(accumulator)

    @overload
    def min(self, *, token: CancellationToken | None = None) -> Task[TItem]: ...

    @overload
    def min[TResult](
            self, selector: AsyncSelector[TItem, TResult], *, token: CancellationToken | None = None
    ) -> Task[TResult]: ...

    def min(self, selector: Any = _SENTINEL, *, token: CancellationToken | None = None) -> Task[Any]:
        """Minimum value (optionally of the projected values); same ``None`` / NaN rules as ``FlpIt.min``."""
        if selector is None:
            raise SelectorNoneError()
        return Task.run(self._extreme, selector, True, _token(token))

    @overload
    def max(self, *, token: CancellationToken | None = None) -> Task[TItem]: ...

    @overload
    def max[TResult](
            self, selector: AsyncSelector[TItem, TResult], *, token: CancellationToken | None = None
    ) -> Task[TResult]: ...

    def max(self, selector: Any = _SENTINEL, *, token: CancellationToken | None = None) -> Task[Any]:
        """Maximum value (optionally of the projected values); same ``None`` / NaN rules as ``FlpIt.max``."""
        if selector is None:
            raise SelectorNoneError()
        return Task.run(self._extreme, selector, False, _token(token))

    async def _extreme(self, selector: Any, is_min: bool, token: CancellationToken) -> Any:
        # Reduced in bounded chunks with the sync rules; the reduction is associative, so combining the
        # running result with each chunk's result gives the same answer as one pass over all values.
        best: Any = None
        is_async = selector is not _SENTINEL and _is_async_callable(selector)
        chunk: list[Any] = []
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                if selector is not _SENTINEL:
                    item = (await selector(item, token)) if is_async else selector(item)
                chunk.append(item)
                if len(chunk) == _EXTREME_CHUNK:
                    best = _extreme_values((best, _extreme_values(chunk, is_min)), is_min)
                    chunk = []
        finally:
            await _aclose(e)
        if chunk:
            best = _extreme_values((best, _extreme_values(chunk, is_min)), is_min)
        return best

    def min_by(self, key_selector: AsyncSelector[TItem, Any], *, token: CancellationToken | None = None) -> Task[TItem]:
        """Element with the minimum key (.NET ``MinByAsync``); ``None`` for an empty sequence."""
        return Task.run(self._extreme_by, key_selector, True, _token(token))

    def max_by(self, key_selector: AsyncSelector[TItem, Any], *, token: CancellationToken | None = None) -> Task[TItem]:
        """Element with the maximum key (.NET ``MaxByAsync``); ``None`` for an empty sequence."""
        return Task.run(self._extreme_by, key_selector, False, _token(token))

    async def _extreme_by(self, key_selector: Any, is_min: bool, token: CancellationToken) -> Any:
        if key_selector is None:
            e = self._get_async_enumerator(token)
            try:
                async for _ in e:
                    raise SelectorNoneError()
            finally:
                await _aclose(e)
            return None
        # (key, item) pairs reduced chunk-wise with the sync rules; the key selector runs once per element.
        is_async = _is_async_callable(key_selector)
        key = itemgetter(0)
        best: Any = _MISSING
        chunk: list[tuple[Any, Any]] = []
        e = self._get_async_enumerator(token)

        def reduce(pairs: list[tuple[Any, Any]]) -> Any:
            winner = _extreme_by(pairs, key, is_min)
            return winner if best is _MISSING else _extreme_by([best, winner], key, is_min)

        try:
            async for item in e:
                chunk.append(((await key_selector(item, token)) if is_async else key_selector(item), item))
                if len(chunk) == _EXTREME_CHUNK:
                    best = reduce(chunk)
                    chunk = []
        finally:
            await _aclose(e)
        if chunk:
            best = reduce(chunk)
        return None if best is _MISSING else best[1]

    def sum(
            self, selector: AsyncSelector[TItem, int | float | Decimal] | _Sentinel = _SENTINEL,
            *, token: CancellationToken | None = None,
    ) -> Task[Union[int, float, Decimal]]:
        """Sum of the (projected) values; ``None`` values are skipped; an empty sequence sums to ``0``."""
        if selector is None:
            raise SelectorNoneError()
        return Task.run(self._sum, selector, _token(token))

    async def _sum(self, selector: Any, token: CancellationToken) -> Any:
        total, count = await self._sum_and_count(selector, token)
        return 0 if count == 0 else total

    def average(
            self, selector: AsyncSelector[TItem, int | float | Decimal] | _Sentinel = _SENTINEL,
            *, token: CancellationToken | None = None,
    ) -> Task[float | int | Decimal | None]:
        """Arithmetic mean of the (projected) values; ``None`` values are skipped; ``None`` when there are none."""
        if selector is None:
            raise SelectorNoneError()
        return Task.run(self._average, selector, _token(token))

    avg = average

    async def _average(self, selector: Any, token: CancellationToken) -> Any:
        total, count = await self._sum_and_count(selector, token)
        if total is None:
            return None
        if isinstance(total, Decimal):
            return _decimal_mean(total, count)
        return total / count

    async def _sum_and_count(self, selector: Any, token: CancellationToken) -> tuple[Any, int]:
        total: Any = None
        count = 0
        is_async = selector is not _SENTINEL and _is_async_callable(selector)
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                if selector is not _SENTINEL:
                    item = (await selector(item, token)) if is_async else selector(item)
                if item is None:
                    continue
                if total is None:
                    total = item
                else:
                    with dotnet_context():
                        try:
                            total += item
                        except (Overflow, Inexact):
                            raise OverflowError(
                                "System.OverflowException: Value was either too large or too small for a Decimal."
                            ) from None
                count += 1
        finally:
            await _aclose(e)
        return total, count

    @overload
    def to_dictionary[TKey](
            self, key_selector: AsyncSelector[TItem, TKey], /, *, token: CancellationToken | None = None
    ) -> Task[dict[TKey, TItem]]: ...

    @overload
    def to_dictionary[TKey, TValue](
            self, key_selector: AsyncSelector[TItem, TKey], element_selector: AsyncSelector[TItem, TValue], /,
            *, token: CancellationToken | None = None,
    ) -> Task[dict[TKey, TValue]]: ...

    def to_dictionary(
            self, key_selector: Any, element_selector: Any = _SENTINEL, /, *, token: CancellationToken | None = None
    ) -> Task[dict[Any, Any]]:
        """Materializes a ``dict``; a ``None`` or duplicate key raises (.NET ``ToDictionaryAsync``)."""
        if key_selector is None:
            raise SelectorNoneError()
        if element_selector is None:
            raise ElementSelectorNoneError()
        return Task.run(self._to_dictionary, key_selector, element_selector, _token(token))

    async def _to_dictionary(self, key_selector: Any, element_selector: Any, token: CancellationToken) -> dict[Any, Any]:
        key_async = _is_async_callable(key_selector)
        has_element = element_selector is not _SENTINEL
        element_async = has_element and _is_async_callable(element_selector)
        result: dict[Any, Any] = {}
        e = self._get_async_enumerator(token)
        try:
            async for item in e:
                key = (await key_selector(item, token)) if key_async else key_selector(item)
                if key is None:
                    raise ArgumentNullError("Value cannot be null. (Parameter 'key')")
                if key in result:
                    raise ArgumentError(f"An item with the same key has already been added. Key: {key!r}")
                if has_element:
                    item = (await element_selector(item, token)) if element_async else element_selector(item)
                result[key] = item
        finally:
            await _aclose(e)
        return result

    @overload
    def to_lookup[TKey](
            self, key_selector: AsyncSelector[TItem, TKey], /, *, token: CancellationToken | None = None
    ) -> Task[Lookup[TKey, TItem]]: ...

    @overload
    def to_lookup[TKey, TElement](
            self, key_selector: AsyncSelector[TItem, TKey], element_selector: AsyncSelector[TItem, TElement], /,
            *, token: CancellationToken | None = None,
    ) -> Task[Lookup[TKey, TElement]]: ...

    def to_lookup(
            self, key_selector: Any, element_selector: Any = _SENTINEL, /, *, token: CancellationToken | None = None
    ) -> Task[Lookup[Any, Any]]:
        """Materializes a ``Lookup`` (.NET ``ToLookupAsync``); ``None`` is a valid key."""
        if key_selector is None:
            raise SelectorNoneError()
        if element_selector is None:
            raise ElementSelectorNoneError()
        return Task.run(self._to_lookup, key_selector, element_selector, _token(token))

    async def _to_lookup(self, key_selector: Any, element_selector: Any, token: CancellationToken) -> Lookup[Any, Any]:
        groups = await _to_groups(self, key_selector, element_selector, token)
        return Lookup({k: Grouping(k, v) for k, v in groups.items()})


class _AppendPrependIt[TItem](AsyncFlpIt[TItem]):
    """append/prepend chain over one source (.NET ``AppendPrependN``): extending it is O(1), never nested."""
    __slots__ = ("_source", "_prepended", "_appended")

    def __init__(self, source: AsyncFlpIt[TItem], prepended: _Node | None, appended: _Node | None) -> None:
        self._source = source
        self._prepended = prepended
        self._appended = appended
        self._factory = partial(_append_prepend_impl, source, prepended, appended)

    @override
    def append(self, element: TItem) -> AsyncFlpIt[TItem]:
        return _AppendPrependIt(self._source, self._prepended, _Node(element, self._appended))

    @override
    def prepend(self, element: TItem) -> AsyncFlpIt[TItem]:
        return _AppendPrependIt(self._source, _Node(element, self._prepended), self._appended)


class _ConcatIt[TItem](AsyncFlpIt[TItem]):
    """concat chain (.NET ``ConcatNAsyncIterator``): concatenating again is O(1), never nested."""
    __slots__ = ("_sources",)

    def __init__(self, sources: _Node) -> None:
        self._sources = sources
        self._factory = partial(_concat_impl, sources)

    @override
    def concat(self, second: AsyncSource[TItem]) -> AsyncFlpIt[TItem]:
        if second is None:
            raise SecondNoneError()
        second_it = _as_async(second)
        if second_it is _EMPTY:
            return self
        return _ConcatIt(_Node(second_it, self._sources))


def to_async_enumerable[T](source: AsyncSource[T]) -> AsyncFlpIt[T]:
    """
    .NET ``ToAsyncEnumerable``: an ``AsyncFlpIt`` is returned as is; an empty ``tuple`` or ``range``
    (immutable, like an empty .NET array) gives the shared empty sequence; anything else is wrapped.
    """
    if isinstance(source, AsyncFlpIt):
        return source
    if type(source) in (tuple, range) and not source:  # type: ignore[arg-type]
        return _EMPTY
    return AsyncFlpIt(source)


class _ReIterable[T](Iterable[T]):
    __slots__ = ("_factory",)

    def __init__(self, factory: Callable[[], Iterator[T]]) -> None:
        self._factory = factory

    def __iter__(self) -> Iterator[T]:
        return self._factory()


class OrderedAsyncIt[TItem](AsyncFlpIt[TItem]):
    """
    Sorted asynchronous sequence (.NET ``IOrderedAsyncEnumerable<T>``). Stable; ``then_by`` adds a
    subordinate key. Enumeration buffers the source, then computes the keys level by level
    (primary first, like .NET) before sorting.
    """
    __slots__ = ("_source", "_criteria")

    def __init__(self, source: AsyncFlpIt[TItem], criteria: tuple[tuple[Any, bool], ...]) -> None:
        self._source = source
        self._criteria = criteria
        self._factory = self._sorted

    async def _sorted(self, token: CancellationToken) -> AsyncIterator[TItem]:
        items = await _collect(self._source, token)
        keys = [
            (await _keys_for(items, selector, _is_async_callable(selector), token), descending)
            for selector, descending in self._criteria
        ]
        order = list(builtins.range(len(items)))
        for level_keys, descending in reversed(keys):
            order.sort(key=lambda i: _NONE_ORDER_KEY if level_keys[i] is None else level_keys[i], reverse=descending)
        for i in order:
            yield items[i]

    def then_by(self, key_selector: AsyncSelector[TItem, Any]) -> OrderedAsyncIt[TItem]:
        """Subsequent ascending ordering by key; preserves the existing ordering."""
        if key_selector is None:
            raise SelectorNoneError()
        return OrderedAsyncIt(self._source, self._criteria + ((key_selector, False),))

    def then_by_descending(self, key_selector: AsyncSelector[TItem, Any]) -> OrderedAsyncIt[TItem]:
        """Subsequent descending ordering by key; preserves the existing ordering."""
        if key_selector is None:
            raise SelectorNoneError()
        return OrderedAsyncIt(self._source, self._criteria + ((key_selector, True),))


class _EmptyAsyncIt(OrderedAsyncIt[Any]):
    """The shared empty sequence; ordering it again yields itself (.NET ``EmptyAsyncEnumerable``)."""
    __slots__ = ()

    def __init__(self) -> None:
        self._factory = lambda _token: _EMPTY_ENUMERATOR

    @override
    def then_by(self, key_selector: AsyncSelector[Any, Any]) -> OrderedAsyncIt[Any]:
        if key_selector is None:
            raise SelectorNoneError()
        return self

    @override
    def then_by_descending(self, key_selector: AsyncSelector[Any, Any]) -> OrderedAsyncIt[Any]:
        if key_selector is None:
            raise SelectorNoneError()
        return self


_EMPTY: Any = _EmptyAsyncIt()


# =============================================================================
# @async_flpit
# =============================================================================

def async_flpit[**P, T](function: Callable[P, AsyncIterator[T]]) -> Callable[P, AsyncFlpIt[T]]:
    """
    Turns an async generator function into one that returns an ``AsyncFlpIt`` (the C# ``async
    IAsyncEnumerable<T>`` method)::

        @async_flpit
        async def rows(n: int, token: CancellationToken = CancellationToken.none()):
            for i in range(n):
                await Task.delay(0.1, token=token)
                yield i

        async for row in rows(10): ...                            # await foreach
        async for row in rows(10).with_cancellation(cts.token): ...
        evens = await rows(10).where(lambda r: r % 2 == 0).to_list()

    The result is cold and can be enumerated again: each enumeration calls the generator
    function anew. Arguments are checked when the decorated function is called.

    A parameter named ``token`` receives the enumeration's cancellation token (the C#
    ``[EnumeratorCancellation]`` parameter): the one given to ``with_cancellation`` /
    ``get_async_enumerator`` or to a terminal operator. If the caller also passes ``token``
    explicitly, the generator sees a token linked to both, as in C#. Give it a default
    (``CancellationToken.none()``), as C# does with ``= default``.
    """
    if not inspect.isasyncgenfunction(function):
        raise TypeError("@async_flpit expects an async generator function (async def with yield)")
    signature = inspect.signature(function)
    takes_token = "token" in signature.parameters

    @wraps(function)
    def create(*args: P.args, **kwargs: P.kwargs) -> AsyncFlpIt[T]:
        explicit = signature.bind(*args, **kwargs).arguments.get("token")  # validates the call now
        if not takes_token:
            return AsyncFlpIt._wrap(lambda _token: _owned(function(*args, **kwargs)))
        if explicit is not None and not isinstance(explicit, CancellationToken):
            raise TypeError("token must be a CancellationToken")

        def enumerate_with(token: CancellationToken) -> AsyncIterator[T]:
            linked: CancellationTokenSource | None = None
            if explicit is not None and explicit.can_be_cancelled and explicit is not token:
                if token.can_be_cancelled:
                    linked = CancellationTokenSource.create_linked_token_source(explicit, token)
                    token = linked.token
                else:
                    token = explicit
            call = signature.bind(*args, **kwargs)
            call.arguments["token"] = token
            stream = function(*call.args, **call.kwargs)
            _owner_scope(stream)  # streams its body iterates are closed with it
            return stream if linked is None else _disposing(stream, linked)

        return AsyncFlpIt._wrap(enumerate_with)

    return create


def _owned[T](stream: Any) -> AsyncIterator[T]:
    _owner_scope(stream)  # streams its body iterates are closed with it
    return typing_cast(AsyncIterator[T], stream)


async def _disposing[T](stream: AsyncIterator[T], linked: CancellationTokenSource) -> AsyncIterator[T]:
    """Enumerate ``stream``; dispose the linked token source when the enumeration ends."""
    try:
        async for item in stream:
            yield item
    finally:
        try:
            await _aclose(stream)
        finally:
            linked.dispose()


__all__ = ["AsyncEnumerator", "AsyncFlpIt", "OrderedAsyncIt", "async_flpit", "to_async_enumerable"]
