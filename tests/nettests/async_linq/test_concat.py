"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ConcatTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ConcatTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

ArgumentNullException("first") is the None source (SourceNoneError); "second" is SecondNoneError.
"""
import pytest

from flpit import AsyncFlpIt, SecondNoneError, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    INT_MAX, INT_MIN, assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources,
    to_pylist, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SecondNoneError):
        AsyncFlpIt.empty().concat(None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    non_empty = create_source(1, 3, 5)
    assert empty.concat(empty) is empty
    assert non_empty.concat(empty) is non_empty
    assert empty.concat(non_empty) is non_empty


@pytest.mark.parametrize("first, second", [
    ([], []), ([], [42]), ([42, 43], []), ([1], [2, 3]), ([2, 4, 8], [3, 5]), ([2, 4, 8], [2, 4, 8]),
    ([2, 4, 8], [2, 5, 8]), ([-1, 2, 5, 6, 7, 8], [INT_MIN, INT_MAX]),
])
@async_test
async def test_VariousValues_MatchesEnumerable(first, second):
    for first_source in create_sources(*first):
        for second_source in create_sources(*second):
            await assert_equal(first + second, first_source.concat(second_source))
            await assert_equal(second + first, second_source.concat(first_source))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).concat(create_source(1, 3, 5)))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    first = track(create_source(2, 4, 8, 16))
    second = track(create_source(1, 3, 5))
    await consume(first.concat(second))
    assert (first.move_next_count, first.current_count, first.dispose_count) == (5, 4, 1)
    assert (second.move_next_count, second.current_count, second.dispose_count) == (4, 3, 1)


@async_test
async def test_MultipleConcat_Coalesced():
    result = create_source(1, 2).concat(create_source(3, 4)).concat(create_source(5, 6))
    await assert_equal([1, 2, 3, 4, 5, 6], result)


@pytest.mark.parametrize("concat_count", [2, 3, 5, 10])
@async_test
async def test_ChainedConcat_ProducesCorrectSequence(concat_count):
    result = AsyncFlpIt.empty()
    expected = []
    for i in range(concat_count):
        start = i * 2
        result = result.concat(create_source(start, start + 1))
        expected += [start, start + 1]
    await assert_equal(expected, result)


@async_test
async def test_LongConcatChain_WorksCorrectly():
    enumerable = AsyncFlpIt.empty()
    for i in range(100):
        enumerable = enumerable.concat(create_source(i))
    total = 0
    async for item in enumerable:
        total += item
    assert total == sum(range(100))


@async_test
async def test_ConcatWithAppendPrepend_WorksCorrectly():
    result = create_source(2, 3).append(4).concat(create_source(5, 6)).prepend(1).append(7)
    await assert_equal([1, 2, 3, 4, 5, 6, 7], result)


@async_test
async def test_MultipleEnumerations_ProducesSameResults():
    source = create_source(1, 2).concat(create_source(3, 4))
    assert await to_pylist(source) == [1, 2, 3, 4]
    assert await to_pylist(source) == [1, 2, 3, 4]


@async_test
async def test_DisposeBeforeComplete_DoesNotThrow():
    enumerator = create_source(1, 2, 3).concat(create_source(4, 5, 6)).get_async_enumerator()
    try:
        assert await enumerator.__anext__() == 1
        assert await enumerator.__anext__() == 2
    finally:
        await enumerator.aclose()


@async_test
async def test_ConcatEmptySequences_ReturnsEmpty():
    await assert_equal([], AsyncFlpIt.empty().concat(AsyncFlpIt.empty()))


@async_test
async def test_Concat_TransitionsCorrectlyBetweenSources():
    result = create_source(1, 2).concat(create_source(3, 4)).concat(create_source(5, 6))
    items = []
    async for item in result:
        items.append(item)
    assert items == [1, 2, 3, 4, 5, 6]


@async_test
async def test_ParallelEnumeration_ConcatClones():
    source = create_source(1, 2).concat(create_source(3, 4))
    enum1 = source.get_async_enumerator()
    enum2 = source.get_async_enumerator()
    try:
        list1 = [item async for item in enum1]
        list2 = [item async for item in enum2]
    finally:
        await enum1.aclose()
        await enum2.aclose()
    assert list1 == [1, 2, 3, 4]
    assert list2 == [1, 2, 3, 4]
