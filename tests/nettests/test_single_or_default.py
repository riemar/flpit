"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SingleOrDefaultTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SingleOrDefaultTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

"""
import pytest

from flpit import (
    flp,
    FlpIt,
    FlpList,
    MultipleElementsError,
    MultipleMatchesError,
    SourceNoneError,
    PredicateNoneError,
)


def test_SameResultsRepeatCallsIntQuery(flp_type):
    # .NET original tests if the
    # var q = from x in new[] { 0.12335f }
    #         select x;
    q = flp_type([0.12335])

    assert q.single_or_default(0.0) == q.single_or_default(0.0)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type([""])
    is_null_or_empty = lambda value: value is None or value == ""

    assert q.single_or_default(None, is_null_or_empty) == q.single_or_default(
        None, is_null_or_empty
    )


def test_Empty(flp_type):
    source = flp_type([])

    assert source.single_or_default(None) is None
    assert source.single_or_default(5) == 5


def test_SingleElement(flp_type):
    source = flp_type([4])

    assert source.single_or_default(None) == 4
    assert source.single_or_default(5) == 4


def test_ManyElementIList(flp_type):
    source = flp_type([4, 4, 4, 4, 4])

    with pytest.raises(MultipleElementsError):
        source.single_or_default(None)

    with pytest.raises(MultipleElementsError):
        source.single_or_default(4)


def test_EmptySourceWithPredicate(flp_type):
    source = flp_type([])
    expected = 0  # .NET default(int); supplied explicitly in Python.

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_EmptySourceWithPredicateDefault(flp_type):
    source = flp_type([])
    expected = 5

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_SingleElementPredicateTrue(flp_type):
    source = flp_type([4])
    expected = 4

    assert source.single_or_default(0, lambda i: i % 2 == 0) == expected


def test_SingleElementPredicateTrueDefault(flp_type):
    source = flp_type([4])
    expected = 4

    assert source.single_or_default(5, lambda i: i % 2 == 0) == expected


def test_SingleElementPredicateFalse(flp_type):
    source = flp_type([3])
    expected = 0  # .NET default(int); supplied explicitly in Python.

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_SingleElementPredicateFalseDefault(flp_type):
    source = flp_type([3])
    expected = 5

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateFalseForAll(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19])
    expected = 0  # .NET default(int); supplied explicitly in Python.

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateFalseForAllDefault(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19])
    expected = 5

    assert source.single_or_default(expected, lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateTrueForLast(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19, 20])
    expected = 20

    assert source.single_or_default(0, lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateTrueForLastDefault(flp_type):
    source = flp_type([3, 1, 7, 9, 13, 19, 20])
    expected = 20

    assert source.single_or_default(5, lambda i: i % 2 == 0) == expected


def test_ManyElementsPredicateTrueForFirstAndFifth(flp_type):
    source = flp_type([2, 3, 1, 7, 10, 13, 19, 9])

    with pytest.raises(MultipleMatchesError):
        source.single_or_default(0, lambda i: i % 2 == 0)


def test_ManyElementsPredicateTrueForFirstAndFifthDefault(flp_type):
    source = flp_type([2, 3, 1, 7, 10, 13, 19, 9])

    with pytest.raises(MultipleMatchesError):
        source.single_or_default(5, lambda i: i % 2 == 0)


@pytest.mark.parametrize(("target", "range_"), [(1, 100), (42, 100)])
def test_FindSingleMatch(flp_type, target, range_):
    source = flp_type(range(range_))

    assert source.single_or_default(-1, lambda i: i == target) == target


@pytest.mark.parametrize(("target", "range_"), [(1, 100), (42, 100)])
def test_RunOnce(target, range_):
    # A one-shot iterator mirrors the .NET RunOnce() source: SingleOrDefault
    source = flp.it(x for x in range(range_))

    assert source.single_or_default(-1, lambda i: i == target) == target


def test_ThrowsOnNullSource(flp_type):
    # FlpIt/FlpList validate the source in their constructors, unlike the
    # .NET extension method which can be invoked with a null source argument.
    with pytest.raises(SourceNoneError):
        flp_type(None).single_or_default(None)

    with pytest.raises(SourceNoneError):
        flp_type(None).single_or_default(0, lambda i: i % 2 == 0)


def test_ThrowsOnNullSourceDefault(flp_type):
    # As above, construction fails before single_or_default can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).single_or_default(5)

    with pytest.raises(SourceNoneError):
        flp_type(None).single_or_default(5, lambda i: i % 2 == 0)


def test_ThrowsOnNullPredicate(flp_type):
    source = flp_type([])

    # EXPECTED TO FAIL with the current FlpIt.single implementation:
    # single() treats None as a supplied predicate but does not validate it
    # before enumeration. On an empty source it raises NoMatchError, which
    # single_or_default catches and converts to the default. .NET validates
    # the null predicate immediately, even when the source is empty.
    with pytest.raises(PredicateNoneError):
        source.single_or_default(0, None)


def test_ThrowsOnNullPredicateDefault(flp_type):
    source = flp_type([])

    # EXPECTED TO FAIL for the same reason as test_ThrowsOnNullPredicate:
    # the current implementation returns the supplied default instead of
    # raising PredicateNoneError for None predicate on an empty source.
    with pytest.raises(PredicateNoneError):
        source.single_or_default(5, None)
