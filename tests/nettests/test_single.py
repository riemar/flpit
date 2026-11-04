"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SingleTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SingleTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.
"""
from decimal import Decimal

import pytest

from flpit import (
    flp,
    EmptySequenceError,
    NoMatchError,
    MultipleElementsError,
    MultipleMatchesError,
    SourceNoneError,
    PredicateNoneError,
)


def test_SameResultsRepeatCallsIntQuery(flp_type):
    # Keep the original .NET test name; its 999.9m literal is a Decimal.
    q = flp_type([Decimal("999.9")])

    assert q.single() == q.single()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^"]).where(lambda value: value is not None and value != "")

    assert q.single() == q.single()


def test_SameResultsRepeatCallsIntQueryWithZero(flp_type):
    q = flp_type([0])

    assert q.single() == q.single()


def test_Empty(flp_type):
    source = flp_type([])

    with pytest.raises(EmptySequenceError):
        source.single()


def test_SingleElement(flp_type):
    source = flp_type([4])
    expected = 4

    assert source.single() == expected


def test_ManyElement(flp_type):
    source = flp_type([4, 4, 4, 4, 4])

    with pytest.raises(MultipleElementsError):
        source.single()


def test_EmptySourceWithPredicate(flp_type):
    source = flp_type([])

    with pytest.raises(NoMatchError):
        source.single(lambda i: i % 2 == 0)


def test_SingleElementPredicateTrue(flp_type):
    source = flp_type([4])
    expected = 4

    assert source.single(lambda i: i % 2 == 0) == expected


def test_SingleElementPredicateFalse(flp_type):
    source = flp_type([3])

    with pytest.raises(NoMatchError):
        source.single(lambda i: i % 2 == 0)


def test_ManyElementsPredicateFalseForAll(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19])

    with pytest.raises(NoMatchError):
        source.single(lambda i: i % 2 == 0)


def test_ManyElementsPredicateTrueForLast(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19, 20])
    expected = 20

    assert source.single(lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateTrueForFirstAndLast(flp_type):
    source = flp_type([2, 3, 1, 7, 9, 13, 19, 10])

    with pytest.raises(MultipleMatchesError):
        source.single(lambda i: i % 2 == 0)


@pytest.mark.parametrize(("target", "range_"), [(1, 100), (42, 100)])
def test_FindSingleMatch(flp_type, target, range_):
    source = flp_type(range(range_))

    assert source.single(lambda i: i == target) == target


@pytest.mark.parametrize(("target", "range_"), [(1, 100), (42, 100)])
def test_RunOnce(target, range_):
    # A generator expression is a one-shot iterator: unlike range itself,
    # it is exhausted after its single traversal.
    source = flp.it(i for i in range(range_))

    assert source.single(lambda i: i == target) == target


def test_ThrowsOnNullSource(flp_type):
    # FlpIt/FlpList validate the source during construction, before single()
    # can be called; this is the Python equivalent of .NET's null-source case.
    with pytest.raises(SourceNoneError):
        flp_type(None).single()

    with pytest.raises(SourceNoneError):
        flp_type(None).single(lambda i: i % 2 == 0)


def test_ThrowsOnNullPredicate(flp_type):
    source = flp_type([])

    # EXPECTED TO FAIL with the current FlpIt.single implementation:
    # single(None) treats None as a supplied predicate but does not validate
    # it before enumeration. Since this source is empty, the predicate is
    # never called and single() raises NoMatchError instead of PredicateNoneError.
    with pytest.raises(PredicateNoneError):
        source.single(None)
