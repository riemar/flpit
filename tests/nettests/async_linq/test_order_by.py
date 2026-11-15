"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable OrderByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/OrderByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

IOrderedAsyncEnumerable<T> maps to OrderedAsyncIt. The expected values come from FlpIt.order_by.
TaskCompletionSource<bool> gates map to flpit.task.TaskCompletionSource.

Adapted:
    * Order() / OrderDescending() and the IComparer overloads are not implemented (FlpIt has neither);
      the theories run with the default comparer and the rest is an explicitly skipped test.
    * FormatException -> ValueError.
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import random

import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from flpit.task import TaskCompletionSource
from nettests.async_linq.async_helpers import (
    assert_canceled, assert_equal, async_test, canceled_token, consume, create_source, create_sources,
    fill_random_ints, fill_random_strings, not_portable, track, unsupported,
)


async def _identity(i, ct):
    return i


def _sync_and_async(key):
    async def key_async(x, ct):
        return key(x)
    return key, key_async


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    empty = AsyncFlpIt.empty()
    for method in (empty.order_by, empty.order_by_descending,
                   empty.order_by(lambda i: i).then_by, empty.order_by(lambda i: i).then_by_descending):
        with pytest.raises(SelectorNoneError):
            method(None)
    ordered = flp.ait([1]).order_by(lambda i: i)
    with pytest.raises(SelectorNoneError):
        ordered.then_by(None)
    with pytest.raises(SelectorNoneError):
        ordered.then_by_descending(None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    for key in (lambda i: i, _identity):
        assert empty.order_by(key) is empty
        assert empty.order_by_descending(key) is empty
        assert empty.order_by(key).then_by(key) is empty
        assert empty.order_by_descending(key).then_by_descending(key) is empty


@async_test
async def test_VariousValues_MatchesEnumerable_Int32():
    rand = random.Random(42)
    for length in (0, 1, 2, 3, 4, 100, 1024):
        ints = fill_random_ints(rand, length)
        copy = list(ints)
        for source in create_sources(*ints):
            def key(i):
                return i if i % 2 == 0 else -1
            for selector in _sync_and_async(key):
                await assert_equal(list(flp.it(ints).order_by(key)), source.order_by(selector))
                await assert_equal(list(flp.it(ints).order_by_descending(key)), source.order_by_descending(selector))
        assert copy == ints


@async_test
async def test_VariousValues_MatchesEnumerable_String():
    def first_char(s):
        return s[0] if len(s) > 0 else " "

    rand = random.Random(42)
    for length in (0, 1, 2, 3, 4, 100, 1024):
        strings = fill_random_strings(rand, length)
        copy = list(strings)
        expected = flp.it(strings)
        for source in create_sources(*strings):
            for size in _sync_and_async(len):
                await assert_equal(list(expected.order_by(len)), source.order_by(size))
                await assert_equal(list(expected.order_by_descending(len)), source.order_by_descending(size))
            for size, first in zip(_sync_and_async(len), _sync_and_async(first_char)):
                await assert_equal(list(expected.order_by(len).then_by(first_char)),
                                   source.order_by(size).then_by(first))
                await assert_equal(list(expected.order_by_descending(len).then_by_descending(first_char)),
                                   source.order_by_descending(size).then_by_descending(first))
        assert copy == strings


def test_VariousValues_MatchesEnumerable_OrderAndComparers():
    unsupported("order() / order_descending() / comparer=...")


@pytest.mark.parametrize("descending, third_level", [(False, False), (False, True), (True, False), (True, True)])
@async_test
async def test_ThenBy_AsynchronousKeySelector_MatchesEnumerable(descending, third_level):
    gate = TaskCompletionSource()
    source = flp.ait([2, 1]).order_by(lambda i: 0)
    if third_level:
        source = source.then_by(lambda i: 0)

    async def key_selector(i, ct):
        await gate.task
        return i

    ordered = source.then_by_descending(key_selector) if descending else source.then_by(key_selector)
    result = ordered.to_list()
    gate.set_result(True)
    assert list(await result) == ([2, 1] if descending else [1, 2])


@pytest.mark.parametrize("descending, third_level, suspend", [
    (d, t, s) for d in (False, True) for t in (False, True) for s in (False, True)
])
@async_test
async def test_ThenBy_KeySelectorThrows_PropagatesException(descending, third_level, suspend):
    gate = TaskCompletionSource()
    exception = ValueError("Key selector failed.")
    source = flp.ait([2, 1]).order_by(lambda i: i)
    if third_level:
        source = source.then_by(lambda i: i)

    async def key_selector(i, ct):
        if suspend:
            await gate.task
        raise exception

    ordered = source.then_by_descending(key_selector) if descending else source.then_by(key_selector)
    result = ordered.to_list()
    gate.set_result(True)
    with pytest.raises(ValueError) as caught:
        await result
    assert caught.value is exception


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    for ordered in (source.order_by(lambda i: i), source.order_by(_identity),
                    source.order_by_descending(lambda i: i), source.order_by_descending(_identity)):
        await assert_canceled(ordered, canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for factory in (lambda s: s.order_by(lambda i: i), lambda s: s.order_by(_identity),
                    lambda s: s.order_by_descending(lambda i: i), lambda s: s.order_by_descending(_identity)):
        source = track(create_source(*range(100)))
        await consume(factory(source))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (101, 100, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
