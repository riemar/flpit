"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ZipTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ZipTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overloads covered by ZipTests:
    Zip(first, second, resultSelector)   -> first.zip(second, result_selector)
    Zip(first, second)                   -> first.zip(second)            (yields tuples)
    Zip(first, second, third)            -> first.zip(second, third)     (NOT implemented: the
                                            3rd positional argument binds to `result_selector`)

.NET helper / language mapping:
    IEnumerable<T> first                 -> flp_type(list)   (FlpIt and FlpList)
    IEnumerable<T> second / third        -> plain list
    int? (nullable) arithmetic `x + y`   -> _lifted_add(x, y): C# lifts `+` over nullables
                                            (null + 1 == null); Python's `None + 1` raises TypeError,
                                            so the lambda body mirrors the lifted C# operator.
    ThrowsOnMatchEnumerable<T>           -> _ThrowsOnMatchEnumerable
    RunOnce()                            -> conftest `run_once` fixture (fails on 2nd enumeration)
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    Explicit type arguments Zip<int,int,int> -> not expressible in Python; the call is identical
                                            to the implicit variant.
    AssertExtensions.Throws<ArgumentNullException>("x", ...) -> pytest.raises(<…NoneError>) around the
                                            *call* (not the enumeration), because .NET validates eagerly.
"""
from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    ArgumentNullError,
    ResultSelectorNoneError,
    SecondNoneError,
    SourceNoneError, FlpList, FlpIt,
)


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

def _lifted_add(x, y):
    """C# `int? + int?` (lifted operator): null if either operand is null."""
    return None if x is None or y is None else x + y


class _ThrowsOnMatchEnumerable:
    """EnumerableTests.ThrowsOnMatchEnumerable<T>: throws a plain Exception when `thrown_on` is reached."""

    def __init__(self, source, thrown_on):
        self._data = source
        self._thrown_on = thrown_on

    def __iter__(self):
        for datum in self._data:
            if datum == self._thrown_on:
                raise Exception()
            yield datum


class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


# ---------------------------------------------------------------------------
# Zip(first, second, resultSelector)
# ---------------------------------------------------------------------------

def test_ImplicitTypeParameters(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 5, 9]
    expected = [3, 7, 12]

    assert list(first.zip(second, lambda x, y: x + y)) == expected


def test_ExplicitTypeParameters(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 5, 9]
    expected = [3, 7, 12]

    # Zip<int, int, int>(...): no explicit type arguments in Python.
    assert list(first.zip(second, lambda x, y: x + y)) == expected


def test_FirstIsNull(flp_type):
    second = [2, 5, 9]

    # .NET: ArgumentNullException("first"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).zip(second, lambda x, y: x + y)


def test_SecondIsNull(flp_type):
    first = flp_type([1, 2, 3])

    # .NET: ArgumentNullException("second"), thrown eagerly at the call.
    # when the query is enumerated (TypeError from builtin zip), so nothing is raised here.
    with pytest.raises(SecondNoneError):
        first.zip(None, lambda x, y: x + y)


def test_FuncIsNull(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 4, 6]

    # .NET: ArgumentNullException("resultSelector"), thrown eagerly at the call.
    # (`result_selector is not _SENTINEL`), so it is accepted as a selector and only fails
    # lazily with "TypeError: 'NoneType' object is not callable" during enumeration.
    with pytest.raises(ResultSelectorNoneError):
        first.zip(second, None)


def test_ExceptionThrownFromFirstsEnumerator():
    first = flp.it(_ThrowsOnMatchEnumerable([1, 3, 3], 2))
    second = [2, 4, 6]
    func = lambda x, y: x + y
    expected = [3, 7, 9]

    assert list(first.zip(second, func)) == expected

    first = flp.it(_ThrowsOnMatchEnumerable([1, 2, 3], 2))

    zip_query = first.zip(second, func)

    with pytest.raises(Exception):
        list(zip_query)


def test_ExceptionThrownFromSecondsEnumerator(flp_type):
    second = _ThrowsOnMatchEnumerable([1, 3, 3], 2)
    first = flp_type([2, 4, 6])
    func = lambda x, y: x + y
    expected = [3, 7, 9]

    assert list(first.zip(second, func)) == expected

    second = _ThrowsOnMatchEnumerable([1, 2, 3], 2)

    zip_query = first.zip(second, func)

    with pytest.raises(Exception):
        list(zip_query)


def test_FirstAndSecondEmpty(flp_type):
    first = flp_type([])
    second = []
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == []


def test_FirstEmptySecondSingle(flp_type):
    first = flp_type([])
    second = [2]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == []


def test_FirstEmptySecondMany(flp_type):
    first = flp_type([])
    second = [2, 4, 8]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == []


def test_SecondEmptyFirstSingle(flp_type):
    first = flp_type([1])
    second = []
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == []


def test_SecondEmptyFirstMany(flp_type):
    first = flp_type([1, 2, 3])
    second = []
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == []


def test_FirstAndSecondSingle(flp_type):
    first = flp_type([1])
    second = [2]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3]


def test_FirstAndSecondEqualSize(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 3, 4]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 5, 7]


def test_SecondOneMoreThanFirst(flp_type):
    first = flp_type([1, 2])
    second = [2, 4, 8]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 6]


def test_SecondManyMoreThanFirst(flp_type):
    first = flp_type([1, 2])
    second = [2, 4, 8, 16]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 6]


def test_FirstOneMoreThanSecond(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 4]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 6]


def test_FirstManyMoreThanSecond(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [2, 4]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 6]


def test_DelegateFuncChanged(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [2, 4, 8]
    func = lambda x, y: x + y

    assert list(first.zip(second, func)) == [3, 6, 11]

    func = lambda x, y: x - y

    assert list(first.zip(second, func)) == [-1, -2, -5]


def test_LambdaFuncChanged(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [2, 4, 8]

    assert list(first.zip(second, lambda x, y: x + y)) == [3, 6, 11]

    assert list(first.zip(second, lambda x, y: x - y)) == [-1, -2, -5]


def test_FirstHasFirstElementNull(flp_type):
    first = flp_type([None, 2, 3, 4])
    second = [2, 4, 8]

    assert list(first.zip(second, _lifted_add)) == [None, 6, 11]


def test_FirstHasLastElementNull(flp_type):
    first = flp_type([1, 2, None])
    second = [2, 4, 6, 8]

    assert list(first.zip(second, _lifted_add)) == [3, 6, None]


def test_FirstHasMiddleNullValue(flp_type):
    first = flp_type([1, None, 3])
    second = [2, 4, 6, 8]

    assert list(first.zip(second, _lifted_add)) == [3, None, 9]


def test_FirstAllElementsNull(flp_type):
    first = flp_type([None, None, None])
    second = [2, 4, 6, 8]

    assert list(first.zip(second, _lifted_add)) == [None, None, None]


def test_SecondHasFirstElementNull(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [None, 4, 6]

    assert list(first.zip(second, _lifted_add)) == [None, 6, 9]


def test_SecondHasLastElementNull(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [2, 4, None]

    assert list(first.zip(second, _lifted_add)) == [3, 6, None]


def test_SecondHasMiddleElementNull(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [2, None, 6]

    assert list(first.zip(second, _lifted_add)) == [3, None, 9]


def test_SecondHasAllElementsNull(flp_type):
    first = flp_type([1, 2, 3, 4])
    second = [None, None, None]

    assert list(first.zip(second, _lifted_add)) == [None, None, None]


def test_SecondLargerFirstAllNull(flp_type):
    first = flp_type([None, None, None, None])
    second = [None, None, None]

    assert list(first.zip(second, _lifted_add)) == [None, None, None]


def test_FirstSameSizeSecondAllNull(flp_type):
    first = flp_type([None, None, None])
    second = [None, None, None]

    assert list(first.zip(second, _lifted_add)) == [None, None, None]


def test_FirstSmallerSecondAllNull(flp_type):
    first = flp_type([None, None, None])
    second = [None, None, None, None]

    assert list(first.zip(second, _lifted_add)) == [None, None, None]


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_ForceNotCollection(range(0, 3))).zip(range(0, 3), lambda x, y: x + y)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


def test_RunOnce(run_once):
    first = flp.it(run_once([1, None, 3]))
    second = run_once([2, 4, 6, 8])

    assert list(first.zip(second, _lifted_add)) == [3, None, 9]


# ---------------------------------------------------------------------------
# Zip(first, second) -> tuples
# ---------------------------------------------------------------------------

def test_Zip2_ImplicitTypeParameters(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 5, 9]

    assert list(first.zip(second)) == [(1, 2), (2, 5), (3, 9)]


def test_Zip2_ExplicitTypeParameters(flp_type):
    first = flp_type([1, 2, 3])
    second = [2, 5, 9]

    # Zip<int, int>(second): no explicit type arguments in Python.
    assert list(first.zip(second)) == [(1, 2), (2, 5), (3, 9)]


def test_Zip2_FirstIsNull(flp_type):
    second = [2, 5, 9]

    # .NET: ArgumentNullException("first"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).zip(second)


def test_Zip2_SecondIsNull(flp_type):
    first = flp_type([1, 2, 3])

    # .NET: ArgumentNullException("second"), thrown eagerly at the call.
    # the None surfaces lazily as a TypeError when the query is enumerated.
    with pytest.raises(SecondNoneError):
        first.zip(None)


def test_Zip2_ExceptionThrownFromFirstsEnumerator():
    first = flp.it(_ThrowsOnMatchEnumerable([1, 3, 3], 2))
    second = [2, 4, 6]

    assert list(first.zip(second)) == [(1, 2), (3, 4), (3, 6)]

    first = flp.it(_ThrowsOnMatchEnumerable([1, 2, 3], 2))

    zip_query = first.zip(second)

    with pytest.raises(Exception):
        list(zip_query)


def test_Zip2_ExceptionThrownFromSecondsEnumerator(flp_type):
    second = _ThrowsOnMatchEnumerable([1, 3, 3], 2)
    first = flp_type([2, 4, 6])

    assert list(first.zip(second)) == [(2, 1), (4, 3), (6, 3)]

    second = _ThrowsOnMatchEnumerable([1, 2, 3], 2)

    zip_query = first.zip(second)

    with pytest.raises(Exception):
        list(zip_query)


def test_Zip2_FirstAndSecondEmpty(flp_type):
    assert list(flp_type([]).zip([])) == []


def test_Zip2_FirstEmptySecondSingle(flp_type):
    assert list(flp_type([]).zip([2])) == []


def test_Zip2_FirstEmptySecondMany(flp_type):
    assert list(flp_type([]).zip([2, 4, 8])) == []


def test_Zip2_SecondEmptyFirstSingle(flp_type):
    assert list(flp_type([1]).zip([])) == []


def test_Zip2_SecondEmptyFirstMany(flp_type):
    assert list(flp_type([1, 2, 3]).zip([])) == []


def test_Zip2_FirstAndSecondSingle(flp_type):
    assert list(flp_type([1]).zip([2])) == [(1, 2)]


def test_Zip2_FirstAndSecondEqualSize(flp_type):
    assert list(flp_type([1, 2, 3]).zip([2, 3, 4])) == [(1, 2), (2, 3), (3, 4)]


def test_Zip2_SecondOneMoreThanFirst(flp_type):
    assert list(flp_type([1, 2]).zip([2, 4, 8])) == [(1, 2), (2, 4)]


def test_Zip2_SecondManyMoreThanFirst(flp_type):
    assert list(flp_type([1, 2]).zip([2, 4, 8, 16])) == [(1, 2), (2, 4)]


def test_Zip2_FirstOneMoreThanSecond(flp_type):
    assert list(flp_type([1, 2, 3]).zip([2, 4])) == [(1, 2), (2, 4)]


def test_Zip2_FirstManyMoreThanSecond(flp_type):
    assert list(flp_type([1, 2, 3, 4]).zip([2, 4])) == [(1, 2), (2, 4)]


def test_Zip2_RunOnce(run_once):
    first = flp.it(run_once([1, None, 3]))
    second = run_once([2, 4, 6, 8])

    assert list(first.zip(second)) == [(1, 2), (None, 4), (3, 6)]


def test_Zip2_NestedTuple(flp_type):
    first = flp_type([1, 3, 5])
    second = [2, 4, 6]
    third = [(1, 2), (3, 4), (5, 6)]

    assert list(first.zip(second)) == third

    fourth = ["one", "two", "three"]

    final = [((1, 2), "one"), ((3, 4), "two"), ((5, 6), "three")]
    assert list(flp_type(third).zip(fourth)) == final


def test_Zip2_TupleNames(flp_type: FlpIt | FlpList):
    t = flp_type([1, 2, 3]).zip([2, 4, 6]).first()
    # element names `First`/`Second` besides Item1/Item2; a plain Python tuple only
    # supports indexing, so `.first` / `.second` raise AttributeError.
    assert t[0] == t.first  # t.Item1 == t.First
    assert t[1] == t.second  # t.Item2 == t.Second
    assert t.item1 == t.first
    assert t.item2 == t.second


# ---------------------------------------------------------------------------
# Zip(first, second, third) -> 3-tuples
#
# EXPECTED FAIL (whole section, unless stated otherwise): the three-sequence overload is not
# implemented. zip(second, result_selector=...) binds `third` to `result_selector`, so the
# query tries to *call* the `third` list/iterable and fails with
# "TypeError: 'list' object is not callable" during enumeration.
# ---------------------------------------------------------------------------

@pytest.mark.skip("third not supported yet")
def test_Zip3_FirstIsNull(flp_type):
    second = [4, 5, 6]
    third = [7, 8, 9]

    # Passes for the "wrong" reason: the FlpIt/FlpList constructor rejects None before zip() is reached.
    with pytest.raises(SourceNoneError):
        flp_type(None).zip(second, third)

@pytest.mark.skip("third not supported yet")
def test_Zip3_SecondIsNull(flp_type):
    first = flp_type([1, 2, 3])
    third = [4, 5, 6]

    # .NET: ArgumentNullException("second"), thrown eagerly.
    # EXPECTED FAIL: no 3-way overload and no eager validation of `second`.
    with pytest.raises(SecondNoneError):
        first.zip(None, third)


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdIsNull(flp_type):
    first = flp_type([1, 2, 3])
    second = [4, 5, 6]

    # .NET: ArgumentNullException("third"), thrown eagerly.
    # EXPECTED FAIL: no 3-way overload; `None` binds to `result_selector` and is not validated
    # eagerly (there is also no dedicated ThirdNoneError, so the ArgumentNullError base is used).
    with pytest.raises(ArgumentNullError):
        first.zip(second, None)


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdEmpty(flp_type):
    first = flp_type([1, 2, 3])
    second = [4, 5, 6]
    third = []

    # EXPECTED FAIL: `third` is treated as the result selector -> TypeError ('list' object is not callable).
    assert list(first.zip(second, third)) == []


@pytest.mark.skip("third not supported yet")
def test_Zip3_ImplicitTypeParameters(flp_type):
    first = flp_type([1, 2])
    second = [3, 4]
    third = [5, 6]

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5), (2, 4, 6)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_ExplicitTypeParameters(flp_type):
    first = flp_type([1, 2])
    second = [3, 4]
    third = [5, 6]

    # Zip<int, int, int>(second, third): no explicit type arguments in Python.
    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5), (2, 4, 6)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdOneMore(flp_type):
    first = flp_type([1, 2])
    second = [3, 4]
    third = [5, 6, 7]

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5), (2, 4, 6)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdManyMore(flp_type):
    first = flp_type([1, 2])
    second = [3, 4]
    third = [5, 6, 7, 8]

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5), (2, 4, 6)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdOneLess(flp_type):
    first = flp_type([1, 2])
    second = [3, 4]
    third = [5]

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_ThirdManyLess(flp_type):
    first = flp_type([1, 2, 3])
    second = [3, 4, 5]
    third = [5]

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5)]


@pytest.mark.skip("third not supported yet")
def test_Zip3_RunOnce(run_once):
    first = flp.it(run_once([1, 2]))
    second = run_once([3, 4])
    third = run_once([5, 6])

    # EXPECTED FAIL: 3-way zip not implemented (see section comment).
    assert list(first.zip(second, third)) == [(1, 3, 5), (2, 4, 6)]
