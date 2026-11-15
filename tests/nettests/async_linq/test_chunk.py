"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ChunkTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ChunkTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

TSource[] chunks map to FlpList chunks (as for FlpIt.chunk).
"""
import random

import pytest

from flpit import ArgumentOutOfRangeError, AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    async_test, cancel_while_enumerating, consume, create_source, create_sources, fill_random_ints, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    AsyncFlpIt.empty().chunk(1)
    with pytest.raises(ArgumentOutOfRangeError, match="size"):
        AsyncFlpIt.empty().chunk(0)
    with pytest.raises(ArgumentOutOfRangeError, match="size"):
        AsyncFlpIt.empty().chunk(-1)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().chunk(1) is AsyncFlpIt.empty()


@async_test
async def test_VariousValues_MatchesEnumerable():
    rand = random.Random(42)
    for collection_size in (0, 1, 10, 50):
        for chunk_size in (1, 2, 3, 5, 60):
            ints = fill_random_ints(rand, collection_size)
            for source in create_sources(*ints):
                expected = [list(chunk) for chunk in flp.it(ints).chunk(chunk_size)]
                e2 = source.chunk(chunk_size).get_async_enumerator()
                try:
                    for chunk in expected:
                        assert list(await e2.__anext__()) == chunk
                    with pytest.raises(StopAsyncIteration):
                        await e2.__anext__()
                finally:
                    await e2.aclose()


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).chunk(2))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(1, 2, 3, 4, 5, 6, 7, 8, 9, 10))
    await consume(source.chunk(3))
    assert (source.move_next_count, source.current_count, source.dispose_count) == (11, 10, 1)
