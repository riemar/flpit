"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ToLookupAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ToLookupAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

ILookup<K, T> maps to Lookup (len, lookup[key], lookup.contains(key)); the oracle is FlpIt.to_lookup.

Adapted:
    * The IEqualityComparer overloads are not implemented (FlpIt.to_lookup has no comparer either); the
      OddEvenComparer assertions are split into an explicitly skipped test.
"""
import random

import pytest

from flpit import AsyncFlpIt, ElementSelectorNoneError, Lookup, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, fill_random_strings, track, unsupported,
)


async def _length(s, ct):
    return len(s)


async def _identity(s, ct):
    return s


def _assert_lookup_equal(expected, actual):
    assert isinstance(actual, Lookup)
    assert len(expected) == len(actual)
    assert list(expected.select_many(lambda g: g)) == list(actual.select_many(lambda g: g))
    for g in expected:
        assert actual.contains(g.key)
        assert list(g) == list(actual[g.key])
    for g in actual:
        assert expected.contains(g.key)
        assert list(g) == list(expected[g.key])


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    empty = AsyncFlpIt.empty()
    with pytest.raises(SelectorNoneError):
        empty.to_lookup(None)
    with pytest.raises(SelectorNoneError):
        empty.to_lookup(None, lambda s: s)
    with pytest.raises(SelectorNoneError):
        empty.to_lookup(None, _identity)
    with pytest.raises(ElementSelectorNoneError):
        empty.to_lookup(len, None)
    with pytest.raises(ElementSelectorNoneError):
        empty.to_lookup(_length, None)


@async_test
async def test_VariousValues_MatchesEnumerable():
    def element(s):
        return s[1:] if len(s) > 0 else ""

    async def key_async(s, ct):
        await Task.yield_now()
        return len(s)

    async def element_async(s, ct):
        await Task.yield_now()
        return element(s)

    rand = random.Random(42)
    for length in (0, 1, 2, 100):
        values = fill_random_strings(rand, length)
        expected = flp.it(values)
        for source in create_sources(*values):
            _assert_lookup_equal(expected.to_lookup(len), await source.to_lookup(len))
            _assert_lookup_equal(expected.to_lookup(len), await source.to_lookup(key_async))
            _assert_lookup_equal(expected.to_lookup(len, element), await source.to_lookup(len, element))
            _assert_lookup_equal(expected.to_lookup(len, element), await source.to_lookup(key_async, element_async))


def test_VariousValues_MatchesEnumerable_Comparer():
    unsupported("to_lookup(..., comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.to_lookup(lambda i: i, token=canceled_token())

    def cancelling(cts):
        def f(i):
            cts.cancel()
            return i
        return f

    def cancelling_async(cts):
        async def f(i, ct):
            assert ct is cts.token
            await Task.yield_now()
            cts.cancel()
            return i
        return f

    def checking(cts):
        async def f(i, ct):
            assert ct is cts.token
            return i
        return f

    for call in (
            lambda cts: source.to_lookup(cancelling(cts), token=cts.token),
            lambda cts: source.to_lookup(cancelling(cts), lambda i: i, token=cts.token),
            lambda cts: source.to_lookup(lambda i: i, cancelling(cts), token=cts.token),
            lambda cts: source.to_lookup(cancelling_async(cts), token=cts.token),
            lambda cts: source.to_lookup(cancelling_async(cts), _identity, token=cts.token),
            lambda cts: source.to_lookup(checking(cts), cancelling_async(cts), token=cts.token),
    ):
        with pytest.raises(OperationCanceledError):
            await call(CancellationTokenSource())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    key_count = element_count = 0

    def key(i):
        nonlocal key_count
        key_count += 1
        return i

    def element(i):
        nonlocal element_count
        element_count += 1
        return i

    async def key_async(i, ct):
        return key(i)

    async def element_async(i, ct):
        return element(i)

    for args in ((key,), (key_async,), (key, element), (key_async, element_async)):
        key_count = element_count = 0
        source = track(create_source(2, 4, 8, 16))
        await source.to_lookup(*args)
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
        assert key_count == 4
        assert element_count == (4 if len(args) == 2 else 0)
