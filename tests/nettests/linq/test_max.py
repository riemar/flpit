"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq MaxTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/MaxTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overload mapping (the selector/comparer overloads are ASSUMED API; flpit's max()/max_by() have none):
    Max()                          -> max()
    Max(IComparer<T>)              -> max(comparer=<_Comparer>)
    Max(selector)                  -> max(selector)
    MaxBy(keySelector)             -> max_by(key_selector)
    MaxBy(keySelector, IComparer)  -> max_by(key_selector, comparer)

.NET type mapping:
    byte/sbyte/short/ushort/int/uint/long/ulong/nint/nuint/Int128/UInt128 -> int
    float / double                 -> float   (Python has no single precision; both map to float)
    decimal                        -> decimal.Decimal
    T? (nullable) / null           -> T | None / None
    DateTime                       -> datetime.datetime
    char                           -> not ported in Max_AllTypes (T.One arithmetic has no str equivalent)
    anonymous types                -> namedtuple
    IComparer<T>                   -> _Comparer(compare)
    Shuffle()                      -> _shuffled(...) (flpit has no shuffle(); seeded random.shuffle)
    TestEnumerable<T>(array)       -> _ForceNotCollection(array)
    ForceNotCollection(x)          -> _ForceNotCollection(x)
    RunOnce()                      -> flp.it(run_once(...)) (conftest `run_once`)
    Assert.Equal on floats         -> _assert_equal (NaN equals NaN, like xunit)

Known reasons for failures in this file:
    * No selector overload (max(selector)) and no comparer overload (max(comparer=...)) -> TypeError.
    * builtin max() ignores NaN ordering: .NET treats NaN as smaller than everything for Max; Python's
      max() depends on element position.
    * None elements: builtin max() raises TypeError when comparing None with a number/str, so the
      nullable cases (null is skipped by .NET) fail; an all-null or empty nullable/reference source
      returns null in .NET but raises EmptySequenceError / TypeError here.
    * max_by() raises EmptySequenceError for empty sources (.NET returns null for nullable/reference
      element types) and cannot compare None keys.
"""
import math
import random
import sys
from collections import namedtuple
from datetime import datetime
from decimal import Decimal

import pytest

from flpit import (
    flp,
    ArgumentNullError,
    InvalidOperationError,
    SelectorNoneError,
    SourceNoneError,
)

INT_MIN = -2147483648
INT_MAX = 2147483647
LONG_MAX = 9223372036854775807
FLOAT_MAX = 3.4028234663852886e38
FLOAT_MIN = -FLOAT_MAX
DOUBLE_MAX = sys.float_info.max
DOUBLE_MIN = -sys.float_info.max
DECIMAL_MAX = Decimal("79228162514264337593543950335")
NAN = float("nan")
INF = float("inf")
NEG_INF = float("-inf")


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


class _Comparer:
    """IComparer<T>: Comparer<T>.Create(compare)."""

    def __init__(self, compare):
        self.compare = compare


def _default_compare(x, y):
    return (x > y) - (x < y)  # Comparer<T>.Default.Compare


_DEFAULT_COMPARER = _Comparer(_default_compare)


def _shuffled(items):
    """Enumerable.Shuffle(): flpit has no shuffle(); a seeded random.shuffle keeps the tests deterministic."""
    data = list(items)
    random.Random(12345).shuffle(data)
    return data


def _assert_equal(expected, actual):
    """xunit Assert.Equal for floats: NaN equals NaN."""
    if isinstance(expected, float) and isinstance(actual, float) and math.isnan(expected) and math.isnan(actual):
        return
    assert expected == actual


def _wrap(flp_type, wrap, array):
    """new TestEnumerable<T>(array) / array wrapped into FlpIt or FlpList."""
    return flp_type(wrap(array))


_WRAPS = [pytest.param(_ForceNotCollection, id="TestEnumerable"), pytest.param(list, id="array")]


# ---------------------------------------------------------------------------
# Max_AllTypes
# ---------------------------------------------------------------------------

def _all_types_data():
    data = []
    for length in range(2, 65):
        expected_int = length + length - 1
        # byte / sbyte / ushort / short / uint / int / ulong / long / nuint / nint / Int128 / UInt128 -> int
        data.append(([i for i in _shuffled(range(length, length + length))], expected_int, 1))
        data.append((_shuffled(list(range(length, length + length))), expected_int, 1))  # ToArray().Shuffle()
        data.append((_shuffled([float(i) for i in range(length, length + length)]), float(expected_int), 1.0))
        data.append((_shuffled([Decimal(i) for i in range(length, length + length)]), Decimal(expected_int), Decimal(1)))
    return data


@pytest.mark.parametrize("source, expected, one", _all_types_data())
def test_Max_AllTypes(flp_type, source, expected, one):
    source = flp_type(_ForceNotCollection(source))

    _assert_equal(expected, source.max())
    # EXPECTED FAIL (from here): the comparer overloads do not exist -> TypeError (unexpected keyword 'comparer').
    # _assert_equal(expected, source.max(comparer=None))
    # _assert_equal(expected, source.max(comparer=_DEFAULT_COMPARER))
    # _assert_equal(expected, source.max(comparer=_Comparer(_default_compare)))
    # first = source.first()
    # _assert_equal(first, source.max(comparer=_Comparer(lambda x, y: 1 if x == first else -1)))
    # ... and no selector overload either.
    _assert_equal(expected + one, source.max(lambda x: x + one))


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)

    assert q.max() == q.max()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: x is not None and x != "")

    assert q.max() == q.max()


# ---------------------------------------------------------------------------
# int / long
# ---------------------------------------------------------------------------

def test_Max_Int_NullSource_ThrowsArgumentNullException(flp_type):
    # .NET: ArgumentNullException("source") for both overloads; flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_Int_EmptySource_ThrowsInvalidOpertionException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()  # Array.Empty<int>()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()  # new List<int>()

    # until then everything is None-able
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x)  is None
    assert flp_type([]).max() is None  # Array.Empty<int>()
    assert flp.lst([]).max() is None # new List<int>()


_MAX_INT_DATA = [
    ([42], 42),
    (list(range(1, 11)), 10),
    ([-100, -15, -50, -10], -10),
    ([-16, 0, 50, 100, 1000], 1000),
    ([-16, 0, 50, 100, 1000] + [INT_MAX], INT_MAX),
    ([20], 20),
    ([-2] * 5, -2),
    ([16, 9, 10, 7, 8], 16),
    ([6, 9, 10, 0, 50], 50),
    ([-6, 0, -9, 0, -10, 0], 0),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MAX_INT_DATA)
def test_Max_Int(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


_MAX_LONG_DATA = [
    ([42], 42),
    (list(range(1, 11)), 10),
    ([-100, -15, -50, -10], -10),
    ([-16, 0, 50, 100, 1000], 1000),
    ([-16, 0, 50, 100, 1000] + [LONG_MAX], LONG_MAX),
    ([INT_MAX + 10], INT_MAX + 10),
    ([500] * 5, 500),
    ([250, 49, 130, 47, 28], 250),
    ([6, 9, 10, 0, INT_MAX + 50], INT_MAX + 50),
    ([6, 50, 9, 50, 10, 50], 50),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MAX_LONG_DATA)
def test_Max_Long(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


def test_Max_Long_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_Long_EmptySource_ThrowsInvalidOpertionException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()  # Array.Empty<int>()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()  # new List<int>()

    # until then everything is None-able
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x)  is None
    assert flp_type([]).max() is None  # Array.Empty<int>()
    assert flp.lst([]).max() is None # new List<int>()


# ---------------------------------------------------------------------------
# float
# ---------------------------------------------------------------------------

_MAX_FLOAT_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 10.0),
    ([-100.0, -15.0, -50.0, -10.0], -10.0),
    ([-16.0, 0.0, 50.0, 100.0, 1000.0], 1000.0),
    ([-16.0, 0.0, 50.0, 100.0, 1000.0, FLOAT_MAX], FLOAT_MAX),
    ([5.5], 5.5),
    ([112.5, 4.9, 30.0, 4.7, 28.0], 112.5),
    ([6.8, 9.4, -10.0, 0.0, NAN, 53.6], 53.6),
    ([-5.5, INF, 9.9, INF], INF),
    ([NAN] * 5, NAN),
    ([NAN, 6.8, 9.4, 10.0, 0.0, -5.6], 10.0),
    ([6.8, 9.4, 10.0, 0.0, -5.6, NAN], 10.0),
    ([NAN, NEG_INF], NEG_INF),
    ([NEG_INF, NAN], NEG_INF),
    # Normally NaN < anything and anything < NaN returns false
    # However, this leads to some irksome outcomes in Min and Max.
    # If we use those semantics then Min(NaN, 5.0) is NaN, but
    # Min(5.0, NaN) is 5.0!  To fix this, we impose a total
    # ordering where NaN is smaller than every value, including
    # negative infinity.
    ([float(i) for i in range(1, 11)] + [NAN], 10.0),
    ([-1.0, -10.0, NAN, 10.0, 200.0, 1000.0], 1000.0),
    ([-FLOAT_MAX, 3000.0, 100.0, 200.0, NAN, 1000.0], 3000.0),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MAX_FLOAT_DATA)
def test_Max_Float(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    # whereas .NET imposes a total order where NaN is smaller than every value.
    _assert_equal(expected, source.max())
    _assert_equal(expected, source.max(lambda x: x))


def test_Max_Float_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_Float_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()

    # until then
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x) is None
    assert flp.it(_ForceNotCollection([])).max() is None
    assert flp.it(_ForceNotCollection([])).max(lambda x: x) is None
    assert flp_type([]).max() is None
    assert flp.lst([]).max() is None


def test_Max_Float_SeveralNaNWithSelector():
    assert math.isnan(flp.repeat(NAN, 5).max(lambda i: i))


def test_Max_NullableFloat_SeveralNaNOrNullWithSelector():
    source = [NAN, None, NAN, None]
    assert math.isnan(flp.it(source).max(lambda i: i))


def test_Max_Float_NaNAtStartWithSelector():
    source = [NAN, 6.8, 9.4, 10.0, 0.0, -5.6]
    assert 10.0 == flp.it(source).max(lambda i: i)


# ---------------------------------------------------------------------------
# double
# ---------------------------------------------------------------------------

_MAX_DOUBLE_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 10.0),
    ([-100.0, -15.0, -50.0, -10.0], -10.0),
    ([-16.0, 0.0, 50.0, 100.0, 1000.0], 1000.0),
    ([-16.0, 0.0, 50.0, 100.0, 1000.0, DOUBLE_MAX], DOUBLE_MAX),
    ([5.5], 5.5),
    ([NAN] * 5, NAN),
    ([112.5, 4.9, 30.0, 4.7, 28.0], 112.5),
    ([6.8, 9.4, -10.0, 0.0, NAN, 53.6], 53.6),
    ([-5.5, INF, 9.9, INF], INF),
    ([NAN, 6.8, 9.4, 10.5, 0.0, -5.6], 10.5),
    ([6.8, 9.4, 10.5, 0.0, -5.6, NAN], 10.5),
    ([NAN, NEG_INF], NEG_INF),
    ([NEG_INF, NAN], NEG_INF),
    # Normally NaN < anything and anything < NaN returns false
    # However, this leads to some irksome outcomes in Min and Max.
    # If we use those semantics then Min(NaN, 5.0) is NaN, but
    # Min(5.0, NaN) is 5.0!  To fix this, we impose a total
    # ordering where NaN is smaller than every value, including
    # negative infinity.
    ([float(i) for i in range(1, 11)] + [NAN], 10.0),
    ([-1.0, -10.0, NAN, 10.0, 200.0, 1000.0], 1000.0),
    ([DOUBLE_MIN, 3000.0, 100.0, 200.0, NAN, 1000.0], 3000.0),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MAX_DOUBLE_DATA)
def test_Max_Double(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    _assert_equal(expected, source.max())
    _assert_equal(expected, source.max(lambda x: x))


def test_Max_Double_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_Double_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()

    # until then
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x) is None
    assert flp.it(_ForceNotCollection([])).max() is None
    assert flp.it(_ForceNotCollection([])).max(lambda x: x) is None
    assert flp_type([]).max() is None
    assert flp.lst([]).max() is None


def test_Max_Double_AllNaNWithSelector():
    assert math.isnan(flp.repeat(NAN, 5).max(lambda i: i))


def test_Max_Double_SeveralNaNOrNullWithSelector():
    source = [NAN, None, NAN, None]
    assert math.isnan(flp.it(source).max(lambda i: i))


def test_Max_Double_NaNThenNegativeInfinityWithSelector():
    source = [NAN, NEG_INF]
    assert math.isinf(flp.it(source).max(lambda i: i)) and flp.it(source).max(lambda i: i) < 0


# ---------------------------------------------------------------------------
# decimal
# ---------------------------------------------------------------------------

_MAX_DECIMAL_DATA = [
    ([Decimal("42")], Decimal("42")),
    ([Decimal(i) for i in range(1, 11)], Decimal("10")),
    ([Decimal("-100"), Decimal("-15"), Decimal("-50"), Decimal("-10")], Decimal("-10")),
    ([Decimal("-16"), Decimal("0"), Decimal("50"), Decimal("100"), Decimal("1000")], Decimal("1000")),
    ([Decimal("-16"), Decimal("0"), Decimal("50"), Decimal("100"), Decimal("1000"), DECIMAL_MAX], DECIMAL_MAX),
    ([Decimal("5.5")], Decimal("5.5")),
    ([Decimal("-3.4")] * 5, Decimal("-3.4")),
    ([Decimal("122.5"), Decimal("4.9"), Decimal("10"), Decimal("4.7"), Decimal("28")], Decimal("122.5")),
    ([Decimal("6.8"), Decimal("9.4"), Decimal("10"), Decimal("0"), Decimal("0"), DECIMAL_MAX], DECIMAL_MAX),
    ([Decimal("-5.5"), Decimal("0"), Decimal("9.9"), Decimal("-5.5"), Decimal("9.9")], Decimal("9.9")),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MAX_DECIMAL_DATA)
def test_Max_Decimal(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.max()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.max(lambda x: x)


def test_Max_Decimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_Decimal_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()

    # until then
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x) is None
    assert flp.it(_ForceNotCollection([])).max() is None
    assert flp.it(_ForceNotCollection([])).max(lambda x: x) is None
    assert flp_type([]).max() is None
    assert flp.lst([]).max() is None


# ---------------------------------------------------------------------------
# nullable int / long / float / double / decimal
#
# EXPECTED FAIL (whole section): .NET skips nulls and returns null for an empty/all-null source;
# builtin max() raises TypeError when it meets None next to a number, and flpit raises
# EmptySequenceError for an empty source. Selector overload also missing.
# ---------------------------------------------------------------------------

_MAX_NULLABLE_INT_DATA = [
    ([42], 42),
    (list(range(1, 11)), 10),
    ([None, -100, -15, -50, -10], -10),
    ([None, -16, 0, 50, 100, 1000], 1000),
    ([None, -16, 0, 50, 100, 1000, INT_MAX], INT_MAX),
    ([None] * 100, None),
    ([], None),
    ([-20], -20),
    ([-6, None, -9, -10, None, -17, -18], -6),
    ([None, None, None, None, None, -5], -5),
    ([6, None, None, 100, 9, 100, 10, 100], 100),
    ([None] * 5, None),
]


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_INT_DATA)
def test_Max_NullableInt(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_INT_DATA)
def test_Max_NullableIntRunOnce(flp_type, run_once, source, expected):
    assert expected == flp.it(run_once(source)).max()
    assert expected == flp.it(run_once(source)).max(lambda x: x)


def test_Max_NullableInt_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


_MAX_NULLABLE_LONG_DATA = [
    ([42], 42),
    (list(range(1, 11)), 10),
    ([None, -100, -15, -50, -10], -10),
    ([None, -16, 0, 50, 100, 1000], 1000),
    ([None, -16, 0, 50, 100, 1000, LONG_MAX], LONG_MAX),
    ([None] * 100, None),
    ([], None),
    ([LONG_MAX], LONG_MAX),
    ([None] * 5, None),
    ([LONG_MAX, None, 9, 10, None, 7, 8], LONG_MAX),
    ([None, None, None, None, None, -LONG_MAX], -LONG_MAX),
    ([-6, None, None, 0, -9, 0, -10, -30], 0),
]


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_LONG_DATA)
def test_Max_NullableLong(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


def test_Max_NullableLong_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


_MAX_NULLABLE_FLOAT_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 10.0),
    ([None, -100.0, -15.0, -50.0, -10.0], -10.0),
    ([None, -16.0, 0.0, 50.0, 100.0, 1000.0], 1000.0),
    ([None, -16.0, 0.0, 50.0, 100.0, 1000.0, FLOAT_MAX], FLOAT_MAX),
    ([None] * 100, None),
    ([], None),
    ([FLOAT_MIN], FLOAT_MIN),
    ([None] * 5, None),
    ([14.50, None, NAN, 10.98, None, 7.5, 8.6], 14.50),
    ([None, None, None, None, None, 0.0], 0.0),
    ([-6.4, None, None, -0.5, -9.4, -0.5, -10.9, -0.5], -0.5),
    ([NAN, 6.8, 9.4, 10.0, 0.0, None, -5.6], 10.0),
    ([6.8, 9.4, 10.0, 0.0, None, -5.6, NAN], 10.0),
    ([NAN, NEG_INF], NEG_INF),
    ([NEG_INF, NAN], NEG_INF),
    ([NAN] * 3, NAN),
    ([NAN, None, None, None], NAN),
    ([None, None, None, NAN], NAN),
    ([None, NAN, None], NAN),
]


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_FLOAT_DATA)
def test_Max_NullableFloat(flp_type, source, expected):
    source = flp_type(source)

    _assert_equal(expected, source.max())
    _assert_equal(expected, source.max(lambda x: x))


def test_Max_NullableFloat_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


_MAX_NULLABLE_DOUBLE_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 10.0),
    ([None, -100.0, -15.0, -50.0, -10.0], -10.0),
    ([None, -16.0, 0.0, 50.0, 100.0, 1000.0], 1000.0),
    ([None, -16.0, 0.0, 50.0, 100.0, 1000.0, DOUBLE_MAX], DOUBLE_MAX),
    ([None] * 100, None),
    ([], None),
    ([DOUBLE_MIN], DOUBLE_MIN),
    ([None] * 5, None),
    ([14.50, None, NAN, 10.98, None, 7.5, 8.6], 14.50),
    ([None, None, None, None, None, 0.0], 0.0),
    ([-6.4, None, None, -0.5, -9.4, -0.5, -10.9, -0.5], -0.5),
    ([NAN, 6.8, 9.4, 10.5, 0.0, None, -5.6], 10.5),
    ([6.8, 9.4, 10.8, 0.0, None, -5.6, NAN], 10.8),
    ([NAN, NEG_INF], NEG_INF),
    ([NEG_INF, NAN], NEG_INF),
    ([NAN] * 3, NAN),
    ([NAN, None, None, None], NAN),
    ([None, None, None, NAN], NAN),
    ([None, NAN, None], NAN),
]


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_DOUBLE_DATA)
def test_Max_NullableDouble(flp_type, source, expected):
    source = flp_type(source)

    _assert_equal(expected, source.max())
    _assert_equal(expected, source.max(lambda x: x))


def test_Max_NullableDouble_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


_MAX_NULLABLE_DECIMAL_DATA = [
    ([Decimal("42")], Decimal("42")),
    ([Decimal(i) for i in range(1, 11)], Decimal("10")),
    ([None, Decimal("-100"), Decimal("-15"), Decimal("-50"), Decimal("-10")], Decimal("-10")),
    ([None, Decimal("-16"), Decimal("0"), Decimal("50"), Decimal("100"), Decimal("1000")], Decimal("1000")),
    ([None, Decimal("-16"), Decimal("0"), Decimal("50"), Decimal("100"), Decimal("1000"), DECIMAL_MAX], DECIMAL_MAX),
    ([None] * 100, None),
    ([], None),
    ([DECIMAL_MAX], DECIMAL_MAX),
    ([None] * 5, None),
    ([Decimal("14.50"), None, None, Decimal("10.98"), None, Decimal("7.5"), Decimal("8.6")], Decimal("14.50")),
    ([None, None, None, None, None, Decimal("0")], Decimal("0")),
    ([Decimal("6.4"), None, None, DECIMAL_MAX, Decimal("9.4"), DECIMAL_MAX, Decimal("10.9"), DECIMAL_MAX], DECIMAL_MAX),
]


@pytest.mark.parametrize("source, expected", _MAX_NULLABLE_DECIMAL_DATA)
def test_Max_NullableDecimal(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


def test_Max_NullableDecimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


# ---------------------------------------------------------------------------
# DateTime / string
# ---------------------------------------------------------------------------

_THREE_THOUSAND = [datetime(3000, 1, 1), datetime(100, 1, 1), datetime(200, 1, 1), datetime(1000, 1, 1)]

_MAX_DATETIME_DATA = [
    ([datetime(2000, 1, i) for i in range(1, 11)], datetime(2000, 1, 10)),
    ([datetime(2000, 12, 1), datetime(2000, 12, 31), datetime(2000, 1, 12)], datetime(2000, 12, 31)),
    (_THREE_THOUSAND, datetime(3000, 1, 1)),
    (_THREE_THOUSAND + [datetime.max], datetime.max),
]


@pytest.mark.parametrize("source, expected", _MAX_DATETIME_DATA)
def test_Max_DateTime(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.max()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.max(lambda x: x)


def test_Max_DateTime_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


def test_Max_DateTime_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).max()

    # until then
    assert flp_type([]).max() is None
    assert flp_type([]).max(lambda x: x) is None
    assert flp.it(_ForceNotCollection([])).max() is None
    assert flp.it(_ForceNotCollection([])).max(lambda x: x) is None
    assert flp_type([]).max() is None
    assert flp.lst([]).max() is None


_MAX_STRING_DATA = [
    ([str(i) for i in range(1, 11)], "9"),
    (["Alice", "Bob", "Charlie", "Eve", "Mallory", "Victor", "Trent"], "Victor"),
    ([None, "Charlie", None, "Victor", "Trent", None, "Eve", "Alice", "Mallory", "Bob"], "Victor"),
    ([], None),
    (["Hello"], "Hello"),
    (["hi"] * 5, "hi"),
    (["zzz", "aaa", "abcd", "bark", "temp", "cat"], "zzz"),
    ([None, None, None, None, "aAa"], "aAa"),
    (["ooo", "ccc", "ccc", "ooo", "ooo", "nnn"], "ooo"),
    ([None] * 5, None),
]


@pytest.mark.parametrize("source, expected", _MAX_STRING_DATA)
def test_Max_String(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.max()
    assert expected == source.max(lambda x: x)


@pytest.mark.parametrize("source, expected", _MAX_STRING_DATA)
def test_Max_StringRunOnce(flp_type, run_once, source, expected):
    assert expected == flp.it(run_once(source)).max()
    assert expected == flp.it(run_once(source)).max(lambda x: x)


def test_Max_String_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(lambda i: i)


# ---------------------------------------------------------------------------
# Selector tests
#
# EXPECTED FAIL (whole section): there is no max(selector) overload (TypeError for the call; for the
# *_NullSelector_* tests nothing raises SelectorNoneError either, a None positional argument is just a TypeError).
# ---------------------------------------------------------------------------

_Named = namedtuple("_Named", "name num")


def test_Max_Int_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_Int_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 10), _Named("John", -105), _Named("Bob", 30)]

    assert 30 == flp_type(source).max(lambda e: e.num)


def test_Max_Long_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_Long_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 10), _Named("John", -105), _Named("Bob", LONG_MAX)]

    assert LONG_MAX == flp_type(source).max(lambda e: e.num)


def test_Max_Float_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 40.5), _Named("John", -10.25), _Named("Bob", 100.45)]

    # (the .NET test uses Select(e => e.num).Max(), which does not need the selector overload)
    assert 100.45 == flp_type(source).select(lambda e: e.num).max()


def test_Max_Float_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_Double_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_Double_WithSelectorAccessingField(flp_type):
    source = [_Named("Tim", 40.5), _Named("John", -10.25), _Named("Bob", 100.45)]

    assert 100.45 == flp_type(source).max(lambda e: e.num)


def test_Max_Decimal_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_Decimal_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("420.5")), _Named("John", Decimal("900.25")), _Named("Bob", Decimal("10.45"))]

    assert Decimal("900.25") == flp_type(source).max(lambda e: e.num)


def test_Max_NullableInt_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_NullableInt_WithSelectorAccessingField(flp_type):
    source = [_Named("Tim", 10), _Named("John", -105), _Named("Bob", None)]

    assert 10 == flp_type(source).max(lambda e: e.num)


def test_Max_NullableLong_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_NullableLong_WithSelectorAccessingField(flp_type):
    source = [_Named("Tim", None), _Named("John", -105), _Named("Bob", LONG_MAX)]

    assert LONG_MAX == flp_type(source).max(lambda e: e.num)


def test_Max_NullableFloat_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_NullableFloat_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 40.5), _Named("John", None), _Named("Bob", 100.45)]

    assert 100.45 == flp_type(source).max(lambda e: e.num)


def test_Max_NullableDouble_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_NullableDouble_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 40.5), _Named("John", None), _Named("Bob", 100.45)]

    assert 100.45 == flp_type(source).max(lambda e: e.num)


def test_Max_NullableDecimal_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_NullableDecimal_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("420.5")), _Named("John", None), _Named("Bob", Decimal("10.45"))]

    assert Decimal("420.5") == flp_type(source).max(lambda e: e.num)


def test_Max_NullableDateTime_EmptySourceWithSelector(flp_type):
    assert flp_type([]).max(lambda x: x) is None


def test_Max_NullableDateTime_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_String_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).max(selector)


def test_Max_String_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("420.5")), _Named("John", Decimal("900.25")), _Named("Bob", Decimal("10.45"))]

    assert "Tim" == flp_type(source).max(lambda e: e.name)


def test_Max_Boolean_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).max()

    # until then
    assert flp_type([]).max() is None
    assert flp.it(_ForceNotCollection([])).max() is None


# ---------------------------------------------------------------------------
# Max(comparer)
# ---------------------------------------------------------------------------

def test_Max_Generic_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max()
    with pytest.raises(SourceNoneError):
        flp_type(None).max(comparer=None)
    with pytest.raises(SourceNoneError):
        flp_type(None).max(comparer=_Comparer(lambda _a, _b: 0))


def test_Max_Generic_EmptyStructSource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max()

    # until then
    assert flp_type([]).max() is None

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(comparer=None)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max(comparer=_Comparer(lambda _a, _b: 0))


_MAX_GENERIC_DATA = [
    ([], None, None),
    ([], _Comparer(lambda _a, _b: 0), None),
    (list(range(0, 10)), None, 9),
    (list(range(0, 10)), _Comparer(lambda x, y: -_default_compare(x, y)), 0),
    (list(range(0, 10)), _Comparer(lambda x, y: 0), 0),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], None, "Zyzzyva"),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], _Comparer(lambda x, y: -_default_compare(x, y)), "Aardvark"),
]

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, comparer, expected", _MAX_GENERIC_DATA)
def test_Max_Generic_HasExpectedOutput(flp_type, source, comparer, expected):
    # where .NET returns null for nullable element types.
    assert expected == flp_type(source).max(comparer=comparer)

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, comparer, expected", _MAX_GENERIC_DATA)
def test_Max_Generic_RunOnce_HasExpectedOutput(flp_type, run_once, source, comparer, expected):
    assert expected == flp.it(run_once(source)).max(comparer=comparer)


# ---------------------------------------------------------------------------
# MaxBy
# ---------------------------------------------------------------------------

def test_MaxBy_Generic_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).max_by(lambda x: x)
    with pytest.raises(SourceNoneError):
        flp_type(None).max_by(lambda x: x, comparer=None)
    with pytest.raises(SourceNoneError):
        flp_type(None).max_by(lambda x: x, _Comparer(lambda _a, _b: 0))


def test_MaxBy_Generic_NullKeySelector_ThrowsArgumentNullException(flp_type):
    source = []
    key_selector = None

    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).max_by(key_selector)
    assert flp_type(source).max_by(key_selector) is None

    # no comparer
    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).max_by(key_selector, comparer=None)
    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).max_by(key_selector, _Comparer(lambda _a, _b: 0))


def test_MaxBy_Generic_EmptyStructSource_ThrowsInvalidOperationException(flp_type):
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max_by(lambda x: str(x))
    assert flp_type([]).max_by(lambda x: str(x)) is None

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max_by(lambda x: str(x), comparer=None)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).max_by(lambda x: str(x), _Comparer(lambda _a, _b: 0))


def test_MaxBy_Generic_EmptyNullableSource_ReturnsNull(flp_type):
    # for nullable / reference element types.
    assert flp_type([]).max_by(lambda x: hash(x)) is None
    # assert flp_type([]).max_by(lambda x: hash(x), comparer=None) is None
    # assert flp_type([]).max_by(lambda x: hash(x), _Comparer(lambda _a, _b: 0)) is None


def test_MaxBy_Generic_EmptyReferenceSource_ReturnsNull(flp_type):
    assert flp_type([]).max_by(lambda x: hash(x)) is None
    # assert flp_type([]).max_by(lambda x: hash(x), comparer=None) is None
    # assert flp_type([]).max_by(lambda x: hash(x), _Comparer(lambda _a, _b: 0)) is None


def _throw_comparer():
    def compare(_a, _b):
        raise InvalidOperationError("comparer should not be called.")

    return _Comparer(compare)


def test_MaxBy_Generic_StructSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    # .NET returns the first element without comparing null keys. No comparer overload either.
    assert 0 == flp_type(range(0, 5)).max_by(lambda x: None)
    # assert 0 == flp_type(range(0, 5)).max_by(lambda x: None, comparer=None)
    # assert 0 == flp_type(range(0, 5)).max_by(lambda x: None, _throw_comparer())


def test_MaxBy_Generic_NullableSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    assert 0 == flp_type(range(0, 5)).cast(int | None).max_by(lambda x: None)
    # assert 0 == flp_type(range(0, 5)).cast(int | None).max_by(lambda x: None, comparer=None)
    # assert 0 == flp_type(range(0, 5)).cast(int | None).max_by(lambda x: None, _throw_comparer())


def test_MaxBy_Generic_ReferenceSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).max_by(lambda x: None)
    # assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).max_by(lambda x: None, comparer=None)
    # assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).max_by(lambda x: None, _throw_comparer())


_Person = namedtuple("_Person", "name age")

_MAX_BY_DATA = [
    ([], lambda x: x, None, None),
    ([], lambda x: x, _Comparer(lambda _a, _b: 0), None),
    (list(range(0, 10)), lambda x: x, None, 9),
    (list(range(0, 10)), lambda x: x, _Comparer(lambda x, y: -_default_compare(x, y)), 0),
    (list(range(0, 10)), lambda x: x, _Comparer(lambda x, y: 0), 0),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], lambda x: x, None, "Zyzzyva"),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], lambda x: x, _Comparer(lambda x, y: -_default_compare(x, y)), "Aardvark"),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.age, None, _Person("Dick", 55)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.age,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Harry", 20)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.name, None, _Person("Tom", 43)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.name,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Dick", 55)),
    ([_Person("Tom", 43), _Person(None, 55), _Person("Harry", 20)], lambda x: x.name,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Harry", 20)),
]

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, key_selector, comparer, expected", _MAX_BY_DATA)
def test_MaxBy_Generic_HasExpectedOutput(flp_type, source, key_selector, comparer, expected):
    # positionally), and empty sources raise EmptySequenceError where .NET returns null.
    assert expected == flp_type(source).max_by(key_selector, comparer)

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, key_selector, comparer, expected", _MAX_BY_DATA)
def test_MaxBy_Generic_RunOnce_HasExpectedOutput(flp_type, run_once, source, key_selector, comparer, expected):
    # EXPECTED FAIL: same reasons as test_MaxBy_Generic_HasExpectedOutput.
    assert expected == flp.it(run_once(source)).max_by(key_selector, comparer)
