"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable JoinTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/JoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

The tuple overloads (Join(inner, outerKey, innerKey) -> (Outer, Inner)) map to JoinTuple(outer, inner).
ArgumentNullException("outer") is the None source (SourceNoneError).

Adapted:
    * The expected values come from the sync FlpIt.join (itself migrated against System.Linq).
    * C# string concatenation treats null as "" and default(int) is 0; the projections spell that out
      with `or ''` / `or 0` (Python has no default(T): unmatched sides are None).
"""
import random

import pytest

from flpit import (
    AsyncFlpIt, InnerKeySelectorNoneError, InnerNoneError, OuterKeySelectorNoneError, ResultSelectorNoneError,
    SourceNoneError, flp,
)
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, consume, create_source, create_sources, fill_random_strings, track,
)


async def _identity(s, ct):
    return s


async def _first(a, b, ct):
    return a


async def _concat(a, b, ct):
    return a + b


_KEY_OVERLOADS = (lambda s: s, _identity)


def _outer_key(s):
    return s[0] if len(s) > 0 else " "


def _inner_key(s):
    return s[1] if len(s) > 1 else " "


async def _outer_key_async(s, ct):
    return _outer_key(s)


async def _inner_key_async(s, ct):
    return _inner_key(s)


def test_InvalidInputs_Throws():
    empty = AsyncFlpIt.empty()
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    for keys, result in ((lambda s: s, lambda a, b: (a or 0) + (b or 0)), (_identity, _concat)):
        with pytest.raises(InnerNoneError):
            empty.join(None, keys, keys, result)
        with pytest.raises(OuterKeySelectorNoneError):
            empty.join(empty, None, keys, result)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.join(empty, keys, None, result)
        with pytest.raises(ResultSelectorNoneError):
            empty.join(empty, keys, keys, None)


def test_TupleJoin_InvalidInputs_Throws():
    empty = AsyncFlpIt.empty()
    for keys in _KEY_OVERLOADS:
        with pytest.raises(InnerNoneError):
            empty.join(None, keys, keys)
        with pytest.raises(OuterKeySelectorNoneError):
            empty.join(empty, None, keys)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.join(empty, keys, None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    non_empty = create_source("1", "2", "3")
    for keys in _KEY_OVERLOADS:
        for result in (lambda a, b: a, _first):
            assert empty.join(empty, keys, keys, result) is empty
            assert non_empty.join(empty, keys, keys, result) is empty
            assert empty.join(non_empty, keys, keys, result) is empty


def test_TupleJoin_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    non_empty = create_source("1", "2", "3")
    for keys in _KEY_OVERLOADS:
        assert empty.join(empty, keys, keys) is empty
        assert non_empty.join(empty, keys, keys) is empty
        assert empty.join(non_empty, keys, keys) is empty


@async_test
async def test_VariousValues_MatchesEnumerable_String():
    rand = random.Random(42)
    for length in (0, 1, 2, 1000):
        values = fill_random_strings(rand, length)
        expected = list(flp.it(values).join(values, _outer_key, _inner_key, lambda o, i: (o or "") + (i or "")))
        for source in create_sources(*values):
            await assert_equal(expected, source.join(source, _outer_key, _inner_key, lambda o, i: (o or "") + (i or "")))

            async def concat(o, i, ct):
                return (o or "") + (i or "")

            await assert_equal(expected, source.join(source, _outer_key_async, _inner_key_async, concat))


@async_test
async def test_TupleJoin_VariousValues_MatchesEnumerable_String():
    rand = random.Random(42)
    for length in (0, 1, 2, 1000):
        values = fill_random_strings(rand, length)
        expected = [t.outer + t.inner for t in flp.it(values).join(values, _outer_key, _inner_key)]
        for source in create_sources(*values):
            await assert_equal(expected, source.join(source, _outer_key, _inner_key).select(lambda t: t.outer + t.inner))
            await assert_equal(
                expected, source.join(source, _outer_key_async, _inner_key_async).select(lambda t: t.outer + t.inner))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)

    async def plain(x, ct):
        return x

    async def add(a, b, ct):
        return (a or 0) + (b or 0)

    def cancelling(cts):
        async def f(*args):
            assert args[-1] is cts.token
            await Task.yield_now()
            cts.cancel()
            return args[0] if len(args) == 2 else (args[0] or 0) + (args[1] or 0)
        return f

    cts = CancellationTokenSource()

    def cancel_then_key(x):
        cts.cancel()
        return x

    with pytest.raises(OperationCanceledError):
        await consume(source.join(source, cancel_then_key, lambda x: x, lambda a, b: (a or 0) + (b or 0)).with_cancellation(cts.token))

    for position in range(3):
        cts = CancellationTokenSource()
        callbacks = [plain, plain, add]
        callbacks[position] = cancelling(cts)
        with pytest.raises(OperationCanceledError):
            await consume(source.join(source, *callbacks).with_cancellation(cts.token))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    async def add(a, b, ct):
        return (a or 0) + (b or 0)

    for factory in (
            lambda o, i: o.join(i, lambda x: x, lambda x: x, lambda a, b: (a or 0) + (b or 0)),
            lambda o, i: o.join(i, _identity, _identity, add),
    ):
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(factory(outer, inner))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)


@async_test
async def test_TupleJoin_InterfaceCalls_ExpectedCounts():
    for keys in _KEY_OVERLOADS:
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(outer.join(inner, keys, keys))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)
