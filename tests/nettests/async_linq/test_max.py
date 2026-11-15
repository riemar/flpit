"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable MaxAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/MaxAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Numeric mapping (see _numeric.py): int/long -> int, float/double -> float, decimal -> Decimal,
      TimeSpan -> datetime.timedelta; T? adds None. NaN ordering follows .NET (FlpIt.max is the oracle).
    * flpit has no runtime generics, so every sequence is None-able (as for FlpIt.max): an empty sequence
      gives None; the non-nullable InvalidOperationException half is an explicitly skipped test.
    * MaxAsync(IComparer) is not implemented (FlpIt.max has no comparer either); the comparer assertions
      are split into an explicitly skipped test.
    * FormatException -> ValueError.
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from flpit.task import OperationCanceledError
from nettests.async_linq._numeric import NON_NULLABLE, NULLABLE, TIMESPAN
from nettests.async_linq.async_helpers import (
    append_exception, async_test, canceled_token, create_source, create_sources, track, unsupported,
)

_NAN = float("nan")


def _same(a, b):
    return a == b or (a != a and b != b)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.skip("Python only has nullables")
def test_EmptyInputs_NonNullable_Throws():
    pass


@async_test
async def test_EmptyInputs_Nullable_ReturnsNull():
    for _ in NULLABLE:
        assert await AsyncFlpIt.empty().max() is None


@pytest.mark.parametrize("values", [[], [0], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [-1000, 1000], [-1, -2, -3]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    expected = flp.it(values)
    for source in create_sources(*values):
        projections = NON_NULLABLE + NULLABLE + [TIMESPAN] if values else NULLABLE
        for _, projection in projections:
            assert await source.select(projection).max() == expected.select(projection).max()

        # With NaNs
        for special in ([_NAN, _NAN], [1.0, _NAN], [_NAN, 1.0]):
            oracle = flp.it(special).concat(expected.select(float)).concat(special).max()
            actual = await flp.ait(special).concat(source.select(float)).concat(flp.ait(special)).max()
            assert _same(oracle, actual)

        # With nulls
        oracle = flp.it([None, None]).concat(expected.select(float)).concat([None, None]).max()
        actual = await flp.ait([None, None]).concat(source.select(float)).concat(flp.ait([None, None])).max()
        assert oracle == actual


def test_VariousValues_MatchesEnumerable_Comparer():
    unsupported("max(comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    for _, projection in NON_NULLABLE + NULLABLE + [TIMESPAN]:
        with pytest.raises(OperationCanceledError):
            await create_source(2, 4).select(projection).max(token=canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for _, projection in NON_NULLABLE + NULLABLE + [TIMESPAN]:
        source = track(create_source(2, 4, 8, 16))
        await source.select(projection).max()
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)

        source = track(append_exception(create_source(2, 4, 8, 16), ValueError()))
        with pytest.raises(ValueError):
            await source.select(projection).max()
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
