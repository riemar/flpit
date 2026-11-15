"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq TakeLastTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/TakeLastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`).

.NET overloads covered by TakeLastTests:
    TakeLast(source, count)              -> source.take_last(count)
    (.NET has no comparer overload for TakeLast, so there is nothing to skip here.)

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
                                            the FlpIt/FlpList constructor rejects None before take_last()
                                            can be called.
    int.MinValue / int.MaxValue          -> INT_MIN / INT_MAX; ``index ^= int.MinValue`` and the
                                            ``index & ...`` checks keep their .NET bit semantics, since
                                            Python integers behave like infinite two's complement.

Faithful quirk: the first .NET test is (copy-paste) named `SkipLastThrowsOnNull` although it exercises
TakeLast. The name is kept so the port stays one-to-one with the original.
"""
from types import SimpleNamespace

import pytest

from conftest import create_sources
from flpit import ArgumentOutOfRangeError, SourceNoneError, flp
from tests.nettests.linq.skip_take_data import (
    ENUMERABLE_DATA,
    ENUMERABLE_DATA_IDS,
    EVALUATION_BEHAVIOR_DATA,
    INT_MAX,
    INT_MIN,
    DelegateIterator,
    mutable_list,
)


def test_SkipLastThrowsOnNull(flp_type):
    # .NET: ArgumentNullException("source"); flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).take_last(10)


@pytest.mark.parametrize("source_count, count", ENUMERABLE_DATA, ids=ENUMERABLE_DATA_IDS)
def test_TakeLast(flp_type, source_count, count):
    source = range(0, source_count)
    expected = list(flp.it(source).reverse().take(count).reverse())

    for source in create_sources(flp_type)(source):
        actual = source.take_last(count)

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
    state = SimpleNamespace(index=0)
    limit = count * 2

    def move_next():
        # index++ != limit: stop once we go past the limit.
        moved = state.index != limit
        state.index += 1
        return moved

    def dispose():
        state.index ^= INT_MIN

    # Yield from 1 up to the limit, inclusive.
    source = DelegateIterator(move_next=move_next, current=lambda: state.index, dispose=dispose)

    iterator = iter(flp.it(source).take_last(count))
    assert state.index == 0  # Nothing should be done before MoveNext is called.

    for i in range(1, count + 1):
        assert next(iterator) == count + i

        # After the first MoveNext call to the enumerator, everything should be evaluated and the enumerator
        # should be disposed.
        assert state.index & INT_MIN == INT_MIN
        assert state.index & INT_MAX == limit + 1

    with pytest.raises(StopIteration):
        next(iterator)

    # Unlike SkipLast, TakeLast can tell straightaway that it can return a sequence with no elements if count <= 0.
    # The enumerable it returns is a specialized empty iterator that has no connections to the source. Hence,
    # after MoveNext returns false under those circumstances, it won't invoke Dispose on our enumerator.
    expected = 0 if count <= 0 else INT_MIN
    assert state.index & INT_MIN == expected


@pytest.mark.parametrize("source_count, count", ENUMERABLE_DATA, ids=ENUMERABLE_DATA_IDS)
def test_RunOnce(flp_type, run_once, source_count, count):
    source = flp_type(range(0, source_count))

    expected = source.take_last(count)
    assert list(expected) == list(run_once(source.take_last(count)))


def test_List_ChangesAfterTakeLast_ChangesReflectedInResults(flp_type):
    source, remove_at = mutable_list(flp_type, [1, 2, 3, 4, 5])

    e = source.take_last(3)

    remove_at(0)
    remove_at(0)

    assert [3, 4, 5] == list(e)


def test_List_Skip_ChangesAfterTakeLast_ChangesReflectedInResults(flp_type):
    source, remove_at = mutable_list(flp_type, [1, 2, 3, 4, 5])

    e = source.skip(1).take_last(3)

    remove_at(0)

    assert [3, 4, 5] == list(e)
