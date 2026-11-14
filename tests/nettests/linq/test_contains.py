"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Adapted from dotnet/runtime System.Linq ContainsTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ContainsTests.cs
"""

from collections.abc import Collection
import math
from decimal import Decimal

import pytest

from flpit import FlpIt, FlpList, flp


@pytest.mark.parametrize(
    "source, value, expected",
    [
        ([], 6, False),
        ([8, 10, 3, 0, -8], 6, False),
        ([8, 10, 3, 0, -8], 8, True),
        ([8, 10, 3, 0, -8], -8, True),
        ([8, 0, 10, 3, 0, -8, 0], 0, True),
        (range(0, 0), 0, False),
        (range(4, 9), 3, False),
        (range(3, 8), 3, True),
        (range(3, 8), 7, True),
        (range(10, 13), 10, True),
    ],
)
def test_Contains(flp_type, source, value, expected):
    assert flp_type(source).contains(value) is expected


@pytest.mark.parametrize("flp_type", [FlpIt, FlpList])
def test_Contains_NullValues(flp_type):
    assert flp_type([None]).contains(None) is True
    assert flp_type([None, "value"]).contains("value") is True
    assert flp_type(["value", None]).contains(None) is True
    assert flp_type(["value"]).contains(None) is False


@pytest.mark.parametrize("flp_type", [FlpIt, FlpList])
def test_Contains_DefaultStringEqualityIsCaseSensitive(flp_type):
    source = flp_type(["Bob", "Robert", "Tim"])
    assert source.contains("Tim") is True
    assert source.contains("tim") is False


@pytest.mark.parametrize("flp_type", [FlpIt, FlpList])
def test_Contains_UsesDotNetValueTypeEquality(flp_type):
    assert flp_type([1]).contains(True) is False
    assert flp_type([1.0]).contains(1) is False
    assert flp_type([Decimal("1")]).contains(1) is False


@pytest.mark.parametrize("flp_type", [FlpIt, FlpList])
def test_Contains_NaNMatchesNaNLikeDotNetDoubleEquals(flp_type):
    stored_nan = float("nan")
    search_nan = float("nan")
    assert stored_nan is not search_nan
    assert math.isnan(stored_nan) and math.isnan(search_nan)
    assert flp_type([stored_nan]).contains(search_nan) is True


def test_ContainsRunOnce(run_once):
    source = flp.it(run_once([8, 10, 3, 0, -8]))
    assert source.contains(3) is True


def test_Contains_ShortCircuitsAfterFirstMatch():
    def source():
        yield 1
        raise AssertionError("Contains must stop after the first match")

    assert flp.it(source()).contains(1) is True


def test_Contains_CustomCollectionUsesItsContainsImplementation():
    class CaseInsensitiveCollection(Collection[str]):
        def __contains__(self, value: object) -> bool:
            return isinstance(value, str) and value.casefold() == "abc"

        def __iter__(self):
            return iter(["ABC"])

        def __len__(self) -> int:
            return 1

    assert flp.it(CaseInsensitiveCollection()).contains("abc") is True


@pytest.mark.parametrize("flp_type", [FlpIt, FlpList])
def test_Contains_RepeatCallsOnReplayableSource(flp_type):
    source = flp_type([1, 2, 3])
    assert source.contains(2) is True
    assert source.contains(2) is True
    assert source.contains(4) is False


def test_Contains_HasNoComparerOverload():
    source = flp.it([1, 2, 3])
    with pytest.raises(TypeError):
        source.contains(2, None)


def test_FlpListContainsAndMembershipOperatorUseDefaultEquality():
    source = FlpList([float("nan")])
    assert source.contains(float("nan")) is True
    assert (float("nan") in source) is True
