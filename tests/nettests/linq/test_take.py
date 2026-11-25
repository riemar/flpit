"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq TakeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/TakeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Every upstream test keeps its name. Mapping:

- ``Take(int)`` is ``take(count)``. Nearly every upstream test repeats its assertions for
  ``Take(Range)`` (``Take(0..3)``, ``Take(^5..3)``, ``Take(0..^2)``, ``Take(^5..^2)``). FlpIt has no
  Range/Index overload, so those halves are the skipped ``test_<Name>_TakeRange`` companions, and the
  tests that use nothing but ranges are skips of their own.
- ``CreateSources`` is the conftest ``create_sources`` (list and a pure iterable); ``RunOnce()`` the
  conftest ``run_once``; ``NumberRangeGuaranteedNotCollectionType`` / ``ForceNotCollection`` generators.
- ``default(int)`` for ``FirstOrDefault()`` / ``LastOrDefault()`` is the explicit default ``0``.
- ``ToArray()`` collapses into ``to_list()`` (Python has no array type).
- ``IEnumerator.Dispose`` is closing the source generator (its ``finally`` runs).
"""
import itertools
from collections.abc import Iterator

import pytest
from conftest import create_sources

from flpit import (
    ArgumentOutOfRangeError,
    FlpList,
    InvalidOperationError,
    SourceNoneError,
    flp,
)

INT_MAX = 2_147_483_647


def _unsupported(api):
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {api}")


_TAKE_RANGE = "take(Range) / Index from end (C# Take(0..3), Take(^5..^2))"


def assert_equal(expected, actual):
    assert list(actual) == list(expected)


def assert_empty(actual):
    assert list(actual) == []


def NumberRangeGuaranteedNotCollectionType(start, count):
    return (i for i in range(start, start + count))


def ForceNotCollection(source):
    return (x for x in source)


class FastInfiniteEnumerator:
    def __iter__(self):
        return itertools.count()


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([x for x in [9999, 0, 888, -1, 66, -777, 1, 2, -12345] if x > -2147483648])

    assert_equal(q.take(9), q.take(9))


def test_SameResultsRepeatCallsIntQueryIList(flp_type):
    q = flp_type([x for x in [9999, 0, 888, -1, 66, -777, 1, 2, -12345] if x > -2147483648]).to_list()

    assert_equal(q.take(9), q.take(9))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type([x for x in ["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""] if x])

    assert_equal(q.take(7), q.take(7))


def test_SameResultsRepeatCallsStringQueryIList(flp_type):
    q = flp_type([x for x in ["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""] if x]).to_list()

    assert_equal(q.take(7), q.take(7))


def test_SourceEmptyCountPositive(flp_type):
    for source in create_sources(flp_type)([]):
        assert_empty(source.take(5))


def test_SourceNonEmptyCountNegative(flp_type):
    for source in create_sources(flp_type)([2, 5, 9, 1]):
        assert_empty(source.take(-5))


def test_SourceNonEmptyCountZero(flp_type):
    for source in create_sources(flp_type)([2, 5, 9, 1]):
        assert_empty(source.take(0))


def test_SourceNonEmptyCountOne(flp_type):
    expected = [2]
    for source in create_sources(flp_type)([2, 5, 9, 1]):
        assert_equal(expected, source.take(1))


def test_SourceNonEmptyTakeAllExactly(flp_type):
    for source in create_sources(flp_type)([2, 5, 9, 1]):
        assert_equal(source, source.take(4))


def test_SourceNonEmptyTakeAllButOne(flp_type):
    expected = [2, 5, 9]
    for source in create_sources(flp_type)([2, 5, 9, 1]):
        assert_equal(expected, source.take(3))


def test_RunOnce(flp_type, run_once):
    source = [2, 5, 9, 1]
    expected = [2, 5, 9]

    assert_equal(expected, flp_type(run_once(source)).take(3))


def test_SourceNonEmptyTakeExcessive(flp_type):
    for source in create_sources(flp_type)([2, 5, None, 9, 1]):
        assert_equal(source, source.take(5))


def test_ThrowsOnNullSource(flp_type):
    # A None source is caught where it is wrapped (see test_skip.py).
    with pytest.raises(SourceNoneError):
        flp_type(None).take(5)


def test_ForcedToEnumeratorDoesNotEnumerate(flp_type):
    iterator1 = flp_type(NumberRangeGuaranteedNotCollectionType(0, 3)).take(2)
    # Don't insist on this behaviour, but check it's correct if it happens
    en1 = iterator1 if isinstance(iterator1, Iterator) else None
    assert not (en1 is not None and next(en1, None) is not None)


def test_Count(flp_type):
    assert 2 == flp_type(NumberRangeGuaranteedNotCollectionType(0, 3)).take(2).count()
    assert 2 == flp_type([1, 2, 3]).take(2).count()
    assert 0 == flp_type(NumberRangeGuaranteedNotCollectionType(0, 3)).take(0).count()


def test_ForcedToEnumeratorDoesntEnumerateIList(flp_type):
    iterator1 = flp_type(NumberRangeGuaranteedNotCollectionType(0, 3)).to_list().take(2)
    # Don't insist on this behaviour, but check it's correct if it happens
    en1 = iterator1 if isinstance(iterator1, Iterator) else None
    assert not (en1 is not None and next(en1, None) is not None)


def test_FollowWithTake(flp_type):
    expected = [5, 6]
    for source in create_sources(flp_type)([5, 6, 7, 8]):
        assert_equal(expected, source.take(5).take(3).take(2).take(40))


def test_FollowWithSkip(flp_type):
    expected = [3, 4, 5]
    for source in create_sources(flp_type)([1, 2, 3, 4, 5, 6]):
        assert_equal(expected, source.take(5).skip(2).skip(-4))


def test_ElementAt(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5, 6]):
        taken0 = source.take(3)
        assert 1 == taken0.element_at(0)
        assert 3 == taken0.element_at(2)
        with pytest.raises(ArgumentOutOfRangeError):
            taken0.element_at(-1)
        with pytest.raises(ArgumentOutOfRangeError):
            taken0.element_at(3)


def test_ElementAtOrDefault(flp_type):
    _unsupported("FlpIt.element_at_or_default")


def test_First(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert 1 == source.take(1).first()
        assert 1 == source.take(4).first()
        assert 1 == source.take(40).first()
        with pytest.raises(InvalidOperationError):
            source.take(0).first()
        with pytest.raises(InvalidOperationError):
            source.skip(5).take(10).first()


def test_FirstOrDefault(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert 1 == source.take(1).first_or_default(0)
        assert 1 == source.take(4).first_or_default(0)
        assert 1 == source.take(40).first_or_default(0)
        assert 0 == source.take(0).first_or_default(0)
        assert 0 == source.skip(5).take(10).first_or_default(0)


def test_Last(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert 1 == source.take(1).last()
        assert 2 == source.take(2).last()
        assert 3 == source.take(3).last()
        assert 4 == source.take(4).last()
        assert 5 == source.take(5).last()
        assert 5 == source.take(6).last()
        assert 5 == source.take(40).last()
        with pytest.raises(InvalidOperationError):
            source.take(0).last()
        with pytest.raises(InvalidOperationError):
            flp_type([]).take(40).last()


def test_LastOrDefault(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert 1 == source.take(1).last_or_default(0)
        assert 2 == source.take(2).last_or_default(0)
        assert 3 == source.take(3).last_or_default(0)
        assert 4 == source.take(4).last_or_default(0)
        assert 5 == source.take(5).last_or_default(0)
        assert 5 == source.take(6).last_or_default(0)
        assert 5 == source.take(40).last_or_default(0)
        assert 0 == source.take(0).last_or_default(0)
        assert 0 == flp_type([]).take(40).last_or_default(0)


def test_ToArray(flp_type):
    pytest.skip("Not portable to Python: ToArray (Python has no array type; to_list is ported as ToList)")


def test_ToList(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert [1, 2, 3, 4, 5] == list(source.take(5).to_list())
        assert [1, 2, 3, 4, 5] == list(source.take(6).to_list())
        assert [1, 2, 3, 4, 5] == list(source.take(40).to_list())
        assert [1, 2, 3, 4] == list(source.take(4).to_list())
        assert 1 == source.take(1).to_list().single()
        assert_empty(source.take(0).to_list())
        assert_empty(source.take(-10).to_list())


def test_TakeCanOnlyBeOneList(flp_type):
    for source in create_sources(flp_type)([2, 4, 6, 8, 10]):
        assert_equal([2], source.take(1))
        assert_equal([4], source.skip(1).take(1))
        assert_equal([6], source.take(3).skip(2))
        assert_equal([2], source.take(3).take(1))


def test_RepeatEnumerating(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        taken1 = source.take(3)
        assert_equal(taken1, taken1)


@pytest.mark.parametrize("largeNumber", [
    1000,
    1000000,
    # FlpIt walks the elements instead of doing .NET's partition index arithmetic: same result, but
    # int.MaxValue elements take about a minute, so that row runs with -m stress.
    pytest.param(INT_MAX, marks=pytest.mark.stress),
])
def test_LazySkipAllTakenForLargeNumbers(largeNumber):
    assert_empty(flp.it(FastInfiniteEnumerator()).take(largeNumber).skip(largeNumber))
    assert_empty(flp.it(FastInfiniteEnumerator()).take(largeNumber).skip(largeNumber).skip(42))
    assert_empty(flp.it(FastInfiniteEnumerator()).take(largeNumber).skip(largeNumber // 2).skip(largeNumber // 2 + 1))


def test_LazyOverflowRegression():
    range_ = flp.it(NumberRangeGuaranteedNotCollectionType(1, 100))
    skipped = range_.skip(42)  # Min index is 42.
    taken1 = skipped.take(INT_MAX)  # May try to calculate max index as 42 + int.MaxValue, leading to integer overflow.
    # One-shot source: upstream enumerates taken1 four times over a re-enumerable iterator, so each
    # assertion gets its own fresh chain here.
    assert_equal(range(43, 101), taken1)
    assert 100 - 42 == flp.it(NumberRangeGuaranteedNotCollectionType(1, 100)).skip(42).take(INT_MAX).count()
    # ToArray collapses into ToList.
    assert_equal(range(43, 101), flp.it(NumberRangeGuaranteedNotCollectionType(1, 100)).skip(42).take(INT_MAX).to_list())


@pytest.mark.parametrize(("skip", "take", "expected"), [
    (0, 0, 0),
    (1, 1, 1),
    (0, INT_MAX, 100),
    (INT_MAX, 0, 0),
    (0xffff, 1, 0),
    (1, 0xffff, 99),
    (INT_MAX, INT_MAX, 0),
    (1, INT_MAX, 99),  # Regression test: The max index is precisely int.MaxValue.
    (0, 100, 100),
    (10, 100, 90),
])
def test_CountOfLazySkipTakeChain(skip, take, expected):
    total_count = 100

    def partition1():
        return flp.it(NumberRangeGuaranteedNotCollectionType(1, total_count)).skip(skip).take(take)

    assert expected == partition1().count()
    assert expected == partition1().select(lambda i: i).count()
    assert expected == len(partition1().select(lambda i: i).to_list())


@pytest.mark.parametrize(("sourceCount", "count"), [(0, -1), (0, 0), (1, 0), (2, 1), (2, 2), (2, 3)])
def test_DisposeSource(sourceCount, count):
    is_iterator_disposed = [False]

    def source():
        try:
            for _ in range(sourceCount):
                yield 0
        finally:
            is_iterator_disposed[0] = True

    iterator0 = iter(flp.it(source()).take(count))
    iterator_count0 = min(sourceCount, max(0, count))
    for _ in range(iterator_count0):
        assert next(iterator0, None) is not None

    assert next(iterator0, None) is None

    # Unlike Skip, Take can tell straightaway that it can return a sequence with no elements if count <= 0.
    # The enumerable it returns is a specialized empty iterator that has no connections to the source. Hence,
    # after MoveNext returns false under those circumstances, it won't invoke Dispose on our enumerator.
    is_iterator_not_empty0 = count > 0
    assert is_iterator_not_empty0 == is_iterator_disposed[0]


def test_DisposeSource_StartIndexFromEnd_ShouldDisposeOnFirstElement():
    _unsupported(_TAKE_RANGE)


def test_DisposeSource_EndIndexFromEnd_ShouldDisposeOnCompletedEnumeration():
    _unsupported(_TAKE_RANGE)


def test_MutableSource():
    # A List<int> source: the query is deferred, so it sees the mutations. FlpIt over a Python list
    # and FlpList mutated in place are the two list-backed forms.
    source1 = [0, 1, 2, 3, 4]
    query1 = flp.it(source1).take(3)
    source1.pop(0)
    source1[2:2] = [-1, -2]
    assert_equal([1, 2, -1], query1)

    source2 = FlpList([0, 1, 2, 3, 4])
    query2 = source2.take(3)
    source2.remove_at(0)
    source2.insert_range(2, [-1, -2])
    assert_equal([1, 2, -1], query2)


def test_MutableSourceNotList():
    source1 = [0, 1, 2, 3, 4]
    query1 = flp.it(ForceNotCollection(source1)).select(lambda i: i).take(3)
    source1.pop(0)
    source1[2:2] = [-1, -2]
    assert_equal([1, 2, -1], query1)


@pytest.mark.parametrize("upstream", [
    "OutOfBoundNoException",
    "OutOfBoundNoExceptionNotList",
    "OutOfBoundNoExceptionListPartition",
    "OutOfBoundNoExceptionEnumerablePartition",
    "NonEmptySource_ConsistencyWithCountable",
    "NonEmptySource_ConsistencyWithCountable_NotList",
    "NonEmptySource_ConsistencyWithCountable_ListPartition",
    "NonEmptySource_ConsistencyWithCountable_EnumerablePartition",
    "NonEmptySource_DoNotThrowException",
    "NonEmptySource_DoNotThrowException_NotList",
    "NonEmptySource_DoNotThrowException_ListPartition",
    "NonEmptySource_DoNotThrowException_EnumerablePartition",
    "EmptySource_DoNotThrowException",
    "EmptySource_DoNotThrowException_NotList",
    "EmptySource_DoNotThrowException_ListPartition",
    "EmptySource_DoNotThrowException_EnumerablePartition",
])
def test_RangeOnly(upstream):
    # Upstream tests that exercise nothing but Take(Range).
    _unsupported(_TAKE_RANGE)


def test_SkipTakeOnIListIsIList():
    _unsupported("skip().take() on a list returning a read-only IList view (IsReadOnly, indexer, CopyTo, IndexOf)")


@pytest.mark.parametrize("upstream", [
    "SameResultsRepeatCallsIntQuery", "SameResultsRepeatCallsIntQueryIList", "SameResultsRepeatCallsStringQuery",
    "SameResultsRepeatCallsStringQueryIList", "SourceEmptyCountPositive", "SourceNonEmptyCountNegative",
    "SourceNonEmptyCountZero", "SourceNonEmptyCountOne", "SourceNonEmptyTakeAllExactly", "SourceNonEmptyTakeAllButOne",
    "RunOnce", "SourceNonEmptyTakeExcessive", "ThrowsOnNullSource", "ForcedToEnumeratorDoesNotEnumerate", "Count",
    "ForcedToEnumeratorDoesntEnumerateIList", "FollowWithTake", "FollowWithSkip", "ElementAt", "First",
    "FirstOrDefault", "Last", "LastOrDefault", "ToList", "TakeCanOnlyBeOneList", "RepeatEnumerating",
    "LazySkipAllTakenForLargeNumbers", "LazyOverflowRegression", "CountOfLazySkipTakeChain", "DisposeSource",
    "MutableSource", "MutableSourceNotList",
])
def test_TakeRange(upstream):
    # The Take(Range) half of each of these upstream tests (their Take(int) half is ported above).
    _unsupported(_TAKE_RANGE)
