"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable PrependTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/PrependTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).
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
        await assert_equal([42] + values, source.prepend(42))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).prepend(42))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await consume(source.prepend(42))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1


@async_test
async def test_MultiplePrepends_Coalesced():
    await assert_equal([1, 2, 3, 4, 5, 6], create_source(4, 5, 6).prepend(3).prepend(2).prepend(1))


@pytest.mark.parametrize("prepend_count", [1, 2, 5, 10])
@async_test
async def test_ChainedPrepends_ProducesCorrectSequence(prepend_count):
    source = AsyncFlpIt.empty()
    for i in range(prepend_count - 1, -1, -1):
        source = source.prepend(i)
    await assert_equal(list(range(prepend_count)), source)


@async_test
async def test_PrependThenAppend_Coalesced():
    await assert_equal([0, 1, 2, 3, 4], create_source(2, 3).prepend(1).append(4).prepend(0))


@async_test
async def test_LongPrependChain_WorksCorrectly():
    enumerable = AsyncFlpIt.empty()
    for i in range(999, -1, -1):
        enumerable = enumerable.prepend(i)
    total = 0
    async for item in enumerable:
        total += item
    assert total == sum(range(1000))


@async_test
async def test_MultipleEnumerations_ProducesSameResults():
    source = create_source(2, 3, 4).prepend(1).prepend(0)
    assert await to_pylist(source) == [0, 1, 2, 3, 4]
    assert await to_pylist(source) == [0, 1, 2, 3, 4]


@async_test
async def test_PrependOnEmptySource_WorksCorrectly():
    await assert_equal([42], AsyncFlpIt.empty().prepend(42))


@async_test
async def test_DisposeBeforeComplete_DoesNotThrow():
    enumerator = create_source(2, 3, 4).prepend(1).prepend(0).get_async_enumerator()
    try:
        assert await enumerator.__anext__() == 0
    finally:
        await enumerator.aclose()


@async_test
async def test_AppendAfterPrepend_BothWork():
    await assert_equal([1, 2, 3, 4], create_source(2, 3).prepend(1).append(4))


@async_test
async def test_ParallelEnumeration_PrependClones():
    source = create_source(3, 4, 5).prepend(2).prepend(1)
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
