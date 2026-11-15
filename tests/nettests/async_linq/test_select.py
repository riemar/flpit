"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable SelectTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/SelectTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * The (value, index) and (value, index, ct) overloads are not implemented (FlpIt.select has no
      index overload either); their assertions are left out.
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    INT_CASES, assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources,
    not_portable, track,
)


async def _to_str(i, ct):
    return str(i)


async def _identity(i, ct):
    return i


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().select(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().select(lambda s: s) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().select(_identity) is AsyncFlpIt.empty()


@pytest.mark.parametrize("ints", INT_CASES)
@async_test
async def test_VariousValues_MatchesEnumerable(ints):
    for source in create_sources(*ints):
        await assert_equal([str(i) for i in ints], source.select(lambda i: str(i)))
        await assert_equal([str(i) for i in ints], source.select(_to_str))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    await cancel_while_enumerating(source.select(lambda i: i))
    await cancel_while_enumerating(source.select(_identity))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for factory in (lambda s: s.select(lambda i: i), lambda s: s.select(_identity)):
        source = track(create_source(1, 2, 3, 4))
        await consume(factory(source))
        assert source.move_next_count == 5
        assert source.current_count == 4
        assert source.dispose_count == 1


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
