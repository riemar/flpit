"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ZipTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ZipTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

(First, Second) tuples map to ZipTuple (a tuple subclass, equal to the plain tuple).

Adapted:
    * Zip(first, second, third) is not implemented (FlpIt.zip has no three-way overload either); its
      assertions are split into explicitly skipped tests.
    * IAsyncEnumerator.Current has no Python equivalent; current_count counts successful moves. .NET's Zip
      moves the first enumerator and only reads Current once the second one moved too, so when the second
      sequence is shorter the first reports one more "current" here (4 instead of 3).
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, ResultSelectorNoneError, SecondNoneError, SourceNoneError, flp
from nettests.async_linq._set_cases import PAIRS
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, not_portable,
    track, unsupported,
)


async def _pair(f, s, ct):
    return f, s


async def _add(a, b, ct):
    return a + b


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SecondNoneError):
        AsyncFlpIt.empty().zip(None)
    with pytest.raises(SecondNoneError):
        AsyncFlpIt.empty().zip(None, lambda s, i: (s, i))
    with pytest.raises(ResultSelectorNoneError):
        AsyncFlpIt.empty().zip(AsyncFlpIt.empty(), None)


def test_InvalidInputs_Throws_ThreeWay():
    # The Zip(first, second, third) half of upstream InvalidInputs_Throws ("first", "second", "third").
    unsupported("zip(second, third)")


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    non_empty = create_source(1, 2, 3)
    assert empty.zip(empty) is empty
    assert empty.zip(non_empty) is empty
    assert non_empty.zip(empty) is empty
    assert non_empty.zip(non_empty) is not empty
    for selector in (lambda a, b: a + b, _add):
        assert empty.zip(empty, selector) is empty
        assert non_empty.zip(empty, selector) is empty
        assert empty.zip(non_empty, selector) is empty
        assert non_empty.zip(non_empty, selector) is not empty


def test_Empty_ProducesEmpty_ThreeWay():
    unsupported("zip(second, third)")


@pytest.mark.parametrize("first, second", PAIRS)
@async_test
async def test_VariousValues_MatchesEnumerable(first, second):
    expected = list(zip(first, second))
    for first_source in create_sources(*first):
        for second_source in create_sources(*second):
            await assert_equal(expected, first_source.zip(second_source, lambda f, s: (f, s)))
            await assert_equal(expected, first_source.zip(second_source, _pair))
            await assert_equal(list(flp.it(first).zip(second)), first_source.zip(second_source))


def test_VariousValues_MatchesEnumerable_ThreeWay():
    unsupported("zip(second, third)")


@async_test
async def test_Cancellation_Cancels():
    for factory in (
            lambda first, second: first.zip(second, lambda f, s: (f, s)),
            lambda first, second: first.zip(second, _pair),
            lambda first, second: first.zip(second),
    ):
        await cancel_while_enumerating(factory(create_source(2, 4, 8, 16), create_source(1, 3, 5)))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for factory in (lambda f, s: f.zip(s), lambda f, s: f.zip(s, lambda a, b: (a, b))):
        first = track(create_source(2, 4, 8, 16))
        second = track(create_source(1, 3, 5))
        await consume(factory(first, second))
        assert (first.move_next_count, first.current_count, first.dispose_count) == (4, 4, 1)  # .NET: (4, 3, 1)
        assert (second.move_next_count, second.current_count, second.dispose_count) == (4, 3, 1)

    first = track(create_source(1, 3, 5))
    second = track(create_source(2, 4, 8, 16))
    await consume(first.zip(second, _pair))
    assert (first.move_next_count, first.current_count, first.dispose_count) == (4, 3, 1)
    assert (second.move_next_count, second.current_count, second.dispose_count) == (3, 3, 1)


def test_InterfaceCalls_ExpectedCounts_ThreeWay():
    unsupported("zip(second, third)")


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
