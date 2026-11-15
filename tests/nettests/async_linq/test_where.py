"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable WhereTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/WhereTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * The (value, index) and (value, index, ct) overloads are not implemented (FlpIt.where has no
      index overload either); their assertions are left out, the sync / async-callback ones are kept.
"""
import pytest

from flpit import AsyncFlpIt, PredicateNoneError, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    INT_CASES, assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, track,
)


async def _is_even(i, ct):
    return i % 2 == 0


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().where(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().where(lambda i: True) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().where(_is_even) is AsyncFlpIt.empty()


@pytest.mark.parametrize("ints", INT_CASES)
@async_test
async def test_VariousValues_MatchesEnumerable(ints):
    for source in create_sources(*ints):
        await assert_equal([i for i in ints if i % 2 == 0], source.where(lambda i: i % 2 == 0))
        await assert_equal([i for i in ints if i % 2 == 0], source.where(_is_even))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(1, 3, 5, 6, 7, 8)
    await cancel_while_enumerating(source.where(lambda i: i % 2 == 0))
    await cancel_while_enumerating(source.where(_is_even))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for factory in (lambda s: s.where(lambda i: i % 2 == 0), lambda s: s.where(_is_even)):
        source = track(create_source(1, 2, 3, 4))
        await consume(factory(source))
        assert source.move_next_count == 5
        assert source.current_count == 4
        assert source.dispose_count == 1
