"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable AverageAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/AverageAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Numeric mapping (see _numeric.py): int/long -> int, float/double -> float, decimal -> Decimal; T? adds None.
    * flpit has no runtime generics, so every sequence is None-able (as for FlpIt.average): an empty
      sequence averages to None; the non-nullable InvalidOperationException half is an explicitly
      skipped test, as in tests/nettests/linq/test_average.py.
    * FormatException -> ValueError.
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from flpit.task import OperationCanceledError
from nettests.async_linq._numeric import NON_NULLABLE, NULLABLE
from nettests.async_linq.async_helpers import (
    INT_MAX, append_exception, async_test, canceled_token, create_source, create_sources, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.skip("Python only has nullables")
def test_EmptyInputs_NonNullable_Throws():
    pass


@async_test
async def test_EmptyInputs_Nullable_ReturnsNull():
    for _ in NULLABLE:
        assert await AsyncFlpIt.empty().average() is None


@pytest.mark.parametrize("values", [[0], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [-INT_MAX, INT_MAX], [-1, -2, -3]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        for _, projection in NON_NULLABLE + NULLABLE:
            assert await source.select(projection).average() == flp.it(values).select(projection).average()
        for _, projection in NULLABLE:
            assert (await source.select_many(lambda i: [projection(i), None]).average()
                    == flp.it(values).select(projection).average())


@async_test
async def test_Cancellation_Cancels():
    for _, projection in NON_NULLABLE + NULLABLE:
        with pytest.raises(OperationCanceledError):
            await create_source(2, 4).select(projection).average(token=canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for _, projection in NON_NULLABLE + NULLABLE:
        source = track(create_source(2, 4, 8, 16))
        await source.select(projection).average()
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)

        source = track(append_exception(create_source(2, 4, 8, 16), ValueError()))
        with pytest.raises(ValueError):
            await source.select(projection).average()
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
