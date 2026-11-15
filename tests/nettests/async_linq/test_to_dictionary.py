"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ToDictionaryAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ToDictionaryAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Dictionary<K, V> maps to dict; ArgumentException (duplicate key) maps to ArgumentError.

Adapted:
    * The IEqualityComparer overloads and ToDictionaryAsync() over KeyValuePair / tuple elements are not
      implemented (FlpIt.to_dictionary always takes a key selector and has no comparer); those assertions
      are split into an explicitly skipped test.
    * (char)('A' + i) -> chr(ord("A") + i); s.Substring(1) -> s[1:].
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import random

import pytest

from flpit import AsyncFlpIt, ArgumentError, ElementSelectorNoneError, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, fill_random_strings, not_portable, track,
    unsupported,
)


async def _length(s, ct):
    return len(s)


async def _identity(s, ct):
    return s


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    empty = AsyncFlpIt.empty()
    with pytest.raises(SelectorNoneError):
        empty.to_dictionary(None)
    with pytest.raises(SelectorNoneError):
        empty.to_dictionary(None, lambda s: s)
    with pytest.raises(SelectorNoneError):
        empty.to_dictionary(None, _identity)
    with pytest.raises(ElementSelectorNoneError):
        empty.to_dictionary(len, None)
    with pytest.raises(ElementSelectorNoneError):
        empty.to_dictionary(_length, None)


@async_test
async def test_Duplicates_Throws():
    async def const_a(s, ct):
        return "a"

    for task in (
            lambda: create_source("a", "b", "a").to_dictionary(lambda s: s),
            lambda: create_source("a", "b", "c").to_dictionary(lambda s: "a"),
            lambda: create_source("a", "b", "c").to_dictionary(const_a),
            lambda: create_source("a", "b", "c").to_dictionary(lambda s: "a", lambda s: s),
            lambda: create_source("a", "b", "c").to_dictionary(const_a, _identity),
    ):
        result = task()
        with pytest.raises(ArgumentError):
            await result


@async_test
async def test_VariousValues_MatchesEnumerable():
    def key(s):
        return s + s

    def element(s):
        return s[1:] if len(s) > 0 else ""

    async def key_async(s, ct):
        await Task.yield_now()
        return key(s)

    async def element_async(s, ct):
        await Task.yield_now()
        return element(s)

    rand = random.Random(42)
    for length in (0, 1, 2, 100):
        values = [s + chr(ord("A") + i) for i, s in enumerate(fill_random_strings(rand, length))]
        for source in create_sources(*values):
            assert await source.to_dictionary(key) == flp.it(values).to_dictionary(key)
            assert await source.to_dictionary(key_async) == flp.it(values).to_dictionary(key)
            assert await source.to_dictionary(key, element) == flp.it(values).to_dictionary(key, element)
            assert await source.to_dictionary(key_async, element_async) == flp.it(values).to_dictionary(key, element)


def test_VariousValues_MatchesEnumerable_PairsAndComparers():
    unsupported("to_dictionary() over pairs / comparer=...")


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.to_dictionary(lambda i: i, token=canceled_token())

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
            lambda cts: source.to_dictionary(cancelling(cts), token=cts.token),
            lambda cts: source.to_dictionary(cancelling(cts), lambda i: i, token=cts.token),
            lambda cts: source.to_dictionary(lambda i: i, cancelling(cts), token=cts.token),
            lambda cts: source.to_dictionary(cancelling_async(cts), token=cts.token),
            lambda cts: source.to_dictionary(cancelling_async(cts), _identity, token=cts.token),
            lambda cts: source.to_dictionary(checking(cts), cancelling_async(cts), token=cts.token),
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
        await source.to_dictionary(*args)
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
        assert key_count == 4
        assert element_count == (4 if len(args) == 2 else 0)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
