"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable AppendTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/AppendTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

``await using (var e = source.GetAsyncEnumerator())`` maps to get_async_enumerator() + aclose().
"""
import pytest

from flpit import SourceNoneError, AsyncFlpIt, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, to_pylist, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        await assert_equal(values + [42], source.append(42))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).append(42))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await consume(source.append(42))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1


@async_test
async def test_MultipleAppends_Coalesced():
    await assert_equal([1, 2, 3, 4, 5, 6], create_source(1, 2, 3).append(4).append(5).append(6))


@pytest.mark.parametrize("append_count", [1, 2, 5, 10])
@async_test
async def test_ChainedAppends_ProducesCorrectSequence(append_count):
    source = AsyncFlpIt.empty()
    for i in range(append_count):
        source = source.append(i)
    await assert_equal(list(range(append_count)), source)


@async_test
async def test_AppendThenPrepend_Coalesced():
    await assert_equal([1, 2, 3, 4, 5], create_source(2, 3).append(4).prepend(1).append(5))


@async_test
async def test_LongAppendChain_WorksCorrectly():
    enumerable = AsyncFlpIt.empty()
    for i in range(1000):
        enumerable = enumerable.append(i)
    total = 0
    async for item in enumerable:
        total += item
    assert total == sum(range(1000))


@async_test
async def test_VeryLongAppendChain_MatchesBenchmarkScenario():
    enumerable = AsyncFlpIt.empty()
    for i in range(10000):
        enumerable = enumerable.append(i)
    assert await enumerable.sum() == sum(range(10000))


@async_test
async def test_MultipleEnumerations_ProducesSameResults():
    source = create_source(1, 2, 3).append(4).append(5)
    assert await to_pylist(source) == [1, 2, 3, 4, 5]
    assert await to_pylist(source) == [1, 2, 3, 4, 5]


@async_test
async def test_AppendOnEmptySource_WorksCorrectly():
    await assert_equal([42], AsyncFlpIt.empty().append(42))


@async_test
async def test_DisposeBeforeComplete_DoesNotThrow():
    enumerator = create_source(1, 2, 3).append(4).append(5).get_async_enumerator()
    try:
        assert await enumerator.__anext__() == 1
    finally:
        await enumerator.aclose()


@async_test
async def test_PrependAfterAppend_BothWork():
    await assert_equal([1, 2, 3, 4], create_source(2, 3).append(4).prepend(1))


@async_test
async def test_ParallelEnumeration_AppendClones():
    source = create_source(1, 2, 3).append(4).append(5)
    enum1 = source.get_async_enumerator()
    enum2 = source.get_async_enumerator()
    try:
        list1 = [item async for item in enum1]
        list2 = [item async for item in enum2]
    finally:
        await enum1.aclose()
        await enum2.aclose()
    assert list1 == [1, 2, 3, 4, 5]
    assert list2 == [1, 2, 3, 4, 5]
