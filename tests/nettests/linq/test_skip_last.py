"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SkipLastTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SkipLastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`).

.NET overloads covered by SkipLastTests:
    SkipLast(source, count)              -> source.skip_last(count)
    (.NET has no comparer overload for SkipLast, so there is nothing to skip here.)

.NET helper / language mapping:
    SkipTakeData.EnumerableData          -> ENUMERABLE_DATA (tests/nettests/linq/skip_take_data.py), as
                                            (source_count, count); the source is ``range(0, source_count)``.
    SkipTakeData.EvaluationBehaviorData  -> EVALUATION_BEHAVIOR_DATA
    CreateSources(source)                -> conftest ``create_sources(flp_type)``: the data as a collection
                                            and as a plain, non-collection iterable.
    DelegateIterator<int>                -> DelegateIterator (skip_take_data.py)
    RunOnce()                            -> conftest ``run_once`` fixture.
    List<int> + RemoveAt                 -> mutable_list(): a ``FlpList`` or a ``FlpIt`` over a live list.
    Assert.Equal(expected, actual)       -> list(actual) == expected
    ToArray() / ToList()                 -> to_list(): there is no array type.
    FirstOrDefault() / LastOrDefault()   -> first_or_default(0) / last_or_default(0); 0 is default(int).
    expected[^1]                         -> expected[-1]
    ElementAtOrDefault(index)            -> element_at(index) raising ArgumentOutOfRangeError: flp has no
                                            element_at_or_default() yet, so the two out-of-range probes
                                            (-1 and Count()) assert the exception at the same indices.
    AssertExtensions.Throws<ArgumentNullException>("source", ...) -> pytest.raises(SourceNoneError):
                                            the FlpIt/FlpList constructor rejects None before skip_last()
                                            can be called.
    int.MinValue / int.MaxValue          -> INT_MIN; ``index ^= int.MinValue`` and the
                                            ``index & ...`` checks keep their .NET bit semantics, since
                                            Python integers behave like infinite two's complement.
"""
from types import SimpleNamespace

import pytest

from conftest import create_sources
from flpit import ArgumentOutOfRangeError, SourceNoneError, flp
from tests.nettests.linq.skip_take_data import (
    ENUMERABLE_DATA,
    ENUMERABLE_DATA_IDS,
    EVALUATION_BEHAVIOR_DATA,
    INT_MIN,
    DelegateIterator,
    mutable_list,
)


def test_SkipLastThrowsOnNull(flp_type):
    # .NET: ArgumentNullException("source"); flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).skip_last(10)


@pytest.mark.parametrize("source_count, count", ENUMERABLE_DATA, ids=ENUMERABLE_DATA_IDS)
def test_SkipLast(flp_type, source_count, count):
    source = range(0, source_count)
    expected = list(flp.it(source).reverse().skip(count).reverse())

    for source in create_sources(flp_type)(source):
        actual = source.skip_last(count)

        assert expected == list(actual)

        assert len(expected) == actual.count()
        assert expected == list(actual.to_list())  # .NET: ToArray() and ToList()
        assert (expected[0] if expected else 0) == actual.first_or_default(0)
        assert (expected[-1] if expected else 0) == actual.last_or_default(0)

        if len(expected) > 0:
            assert expected[0] == actual.element_at(0)
            assert expected[-1] == actual.element_at(len(expected) - 1)
            assert expected[len(expected) // 2] == actual.element_at(len(expected) // 2)

        # .NET: ElementAtOrDefault(-1) == 0 and ElementAtOrDefault(Count()) == 0
        with pytest.raises(ArgumentOutOfRangeError):
            actual.element_at(-1)
        with pytest.raises(ArgumentOutOfRangeError):
            actual.element_at(actual.count())


@pytest.mark.parametrize("count", EVALUATION_BEHAVIOR_DATA)
def test_EvaluationBehavior(count):
    # We want to make sure no more than `count` items are ever evaluated ahead of the current position.
    # As an example, if Enumerable.Range(1, 6).SkipLast(2) is called, then we should read in the first 3 items,
    # yield 1, read in 4, yield 2, and so on.
    state = SimpleNamespace(index=0)
    limit = max(0, count * 2)

    def move_next():
        # index++ != limit: stop once we go past the limit.
        moved = state.index != limit
        state.index += 1
        return moved

    def dispose():
        state.index ^= INT_MIN

    # Yield from 1 up to the limit, inclusive.
    source = DelegateIterator(move_next=move_next, current=lambda: state.index, dispose=dispose)

    iterator = iter(flp.it(source).skip_last(count))
    assert state.index == 0  # Nothing should be done before MoveNext is called.

    for i in range(1, count + 1):
        assert next(iterator) == i
        assert state.index == count + i

    with pytest.raises(StopIteration):
        next(iterator)
    assert state.index & INT_MIN == INT_MIN


@pytest.mark.parametrize("source_count, count", ENUMERABLE_DATA, ids=ENUMERABLE_DATA_IDS)
def test_RunOnce(flp_type, run_once, source_count, count):
    source = flp_type(range(0, source_count))

    expected = source.skip_last(count)
    assert list(expected) == list(run_once(source.skip_last(count)))


def test_List_ChangesAfterSkipLast_ChangesReflectedInResults(flp_type):
    source, remove_at = mutable_list(flp_type, [1, 2, 3, 4, 5])

    e = source.skip_last(2)

    remove_at(4)
    remove_at(3)

    assert [1] == list(e)


def test_List_Skip_ChangesAfterSkipLast_ChangesReflectedInResults(flp_type):
    source, remove_at = mutable_list(flp_type, [1, 2, 3, 4, 5])

    e = source.skip(1).skip_last(2)

    remove_at(4)

    assert [2] == list(e)
