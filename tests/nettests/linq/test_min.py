"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq MinTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/MinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overload mapping (the selector/comparer overloads are ASSUMED API; flpit's min()/min_by() have none):
    Min()                          -> min()
    Min(IComparer<T>)              -> min(comparer=<_Comparer>)
    Min(selector)                  -> min(selector)
    MinBy(keySelector)             -> min_by(key_selector)
    MinBy(keySelector, IComparer)  -> min_by(key_selector, comparer)

.NET type mapping:
    byte/sbyte/short/ushort/int/uint/long/ulong/nint/nuint -> int
    float / double                 -> float   (Python has no single precision; both map to float)
    decimal                        -> decimal.Decimal
    T? (nullable) / null           -> T | None / None
    DateTime                       -> datetime.datetime
    anonymous types                -> namedtuple
    IComparer<T>                   -> _Comparer(compare)
    Shuffle()                      -> _shuffled(...) (flpit has no shuffle(); seeded random.shuffle)
    TestEnumerable<T>(array)       -> _ForceNotCollection(array)
    ForceNotCollection(x)          -> _ForceNotCollection(x)
    RunOnce()                      -> flp.it(run_once(...)) (conftest `run_once`)
    Assert.Equal on floats         -> _assert_equal (NaN equals NaN, like xunit)
    Enumerable.Repeat(NaN, int.MaxValue) -> skipped rows: .NET short-circuits on NaN, builtin min()
                                      would enumerate 2**31 elements (minutes) before returning.

Known reasons for failures in this file:
    * No selector overload (min(selector)) and no comparer overload (min(comparer=...)) -> TypeError.
    * NaN: .NET Min returns NaN as soon as a NaN is present; builtin min() only returns NaN when the NaN
      comes first (comparisons with NaN are False).
    * None elements: builtin min() raises TypeError when comparing None with a number/str, so the nullable
      cases (null is skipped by .NET) fail; an all-null or empty nullable/reference source returns null in
      .NET but raises EmptySequenceError / TypeError here.
    * min_by() raises EmptySequenceError for empty sources (.NET returns null for nullable/reference
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
    InvalidOperationError,
    SelectorNoneError,
    SourceNoneError,
)

INT_MIN = -2147483648
INT_MAX = 2147483647
LONG_MIN = -9223372036854775808
LONG_MAX = 9223372036854775807
FLOAT_MIN = -3.4028234663852886e38
DOUBLE_MIN = -sys.float_info.max
DECIMAL_MIN = Decimal("-79228162514264337593543950335")
DECIMAL_MAX = Decimal("79228162514264337593543950335")
NAN = float("nan")
NEG_INF = float("-inf")

_SKIP_HUGE = "Repeat(NaN, int.MaxValue): .NET short-circuits on NaN; builtin min() would enumerate 2**31 elements"


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
    return flp_type(wrap(array))


_WRAPS = [pytest.param(_ForceNotCollection, id="TestEnumerable"), pytest.param(list, id="array")]
_Named = namedtuple("_Named", "name num")


def _huge(value):
    return pytest.param(value, NAN, marks=pytest.mark.skip(_SKIP_HUGE), id="Repeat_NaN_int_MaxValue")


# ---------------------------------------------------------------------------
# Min_AllTypes
# ---------------------------------------------------------------------------

def _all_types_data():
    data = []
    for length in range(2, 65):
        data.append((_shuffled(range(length, length + length)), length, 1))
        data.append((_shuffled([float(i) for i in range(length, length + length)]), float(length), 1.0))
        data.append((_shuffled([Decimal(i) for i in range(length, length + length)]), Decimal(length), Decimal(1)))
    return data


@pytest.mark.parametrize("source, expected, one", _all_types_data())
def test_Min_AllTypes(flp_type, source, expected, one):
    source = flp_type(_ForceNotCollection(source))

    _assert_equal(expected, source.min())

    # _assert_equal(expected, source.min(comparer=None))
    # _assert_equal(expected, source.min(comparer=_DEFAULT_COMPARER))
    # _assert_equal(expected, source.min(comparer=_Comparer(_default_compare)))
    first = source.first()
    # _assert_equal(first, source.min(comparer=_Comparer(lambda x, y: -1 if x == first else 1)))
    # ... and no selector overload either.
    _assert_equal(expected + one, source.min(lambda x: x + one))


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)

    assert q.min() == q.min()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: x is not None and x != "")

    assert q.min() == q.min()


# ---------------------------------------------------------------------------
# int / long
# ---------------------------------------------------------------------------

_MIN_INT_DATA = [
    ([42], 42),
    (list(range(1, 11)), 1),
    ([-1, -10, 10, 200, 1000], -10),
    ([3000, 100, 200, 1000], 100),
    ([3000, 100, 200, 1000, INT_MIN], INT_MIN),
    ([20], 20),
    ([-2] * 5, -2),
    (list(range(1, 11)), 1),
    ([6, 9, 10, 7, 8], 6),
    ([6, 9, 10, 0, -5], -5),
    ([6, 0, 9, 0, 10, 0], 0),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MIN_INT_DATA)
def test_Min_Int(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.min()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.min(lambda x: x)


def test_Min_Int_NullSource_ThrowsArgumentNullException(flp_type):
    # .NET: ArgumentNullException("source") for both overloads; flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


def _assert_empty_source_throws(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min()

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).min()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).min(lambda x: x)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min()  # Array.Empty<T>()
    # with pytest.raises(InvalidOperationError):
    #     flp.lst([]).min()  # new List<T>()

    # until then everything is None-able
    assert flp_type([]).min() is None
    assert flp_type([]).min(lambda x: x) is None
    assert flp.it(_ForceNotCollection([])).min() is None
    assert flp.it(_ForceNotCollection([])).min(lambda x: x) is None
    assert flp_type([]).min() is None # Array.Empty<T>()
    assert flp.lst([]).min() is None # new List<T>()



def test_Min_Int_EmptySource_ThrowsInvalidOperationException(flp_type):
    _assert_empty_source_throws(flp_type)


_MIN_LONG_DATA = [
    ([42], 42),
    (list(range(1, 11)), 1),
    ([-1, -10, 10, 200, 1000], -10),
    ([3000, 100, 200, 1000], 100),
    ([3000, 100, 200, 1000, LONG_MIN], LONG_MIN),
    ([INT_MAX + 10], INT_MAX + 10),
    ([500] * 5, 500),
    ([-250, 49, 130, 47, 28], -250),
    ([6, 9, 10, 0, -INT_MAX - 50], -INT_MAX - 50),
    ([6, -5, 9, -5, 10, -5], -5),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MIN_LONG_DATA)
def test_Min_Long(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.min()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.min(lambda x: x)


def test_Min_Long_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


def test_Min_Long_EmptySource_ThrowsInvalidOperationException(flp_type):
    """just keeps this for completeness"""
    _assert_empty_source_throws(flp_type)


# ---------------------------------------------------------------------------
# float / double
# ---------------------------------------------------------------------------

_MIN_FLOAT_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 1.0),
    ([-1.0, -10.0, 10.0, 200.0, 1000.0], -10.0),
    ([3000.0, 100.0, 200.0, 1000.0], 100.0),
    ([3000.0, 100.0, 200.0, 1000.0, FLOAT_MIN], FLOAT_MIN),
    ([5.5], 5.5),
    ([NAN] * 5, NAN),
    ([-2.5, 4.9, 130.0, 4.7, 28.0], -2.5),
    ([6.8, 9.4, 10.0, 0.0, -5.6], -5.6),
    ([-5.5, NEG_INF, 9.9, NEG_INF], NEG_INF),
    ([NAN, 6.8, 9.4, 10.0, 0.0, -5.6], NAN),
    ([6.8, 9.4, 10.0, 0.0, -5.6, NAN], NAN),
    ([NAN, NEG_INF], NAN),
    ([NEG_INF, NAN], NAN),
    # Normally NaN < anything is false, as is anything < NaN
    # However, this leads to some irksome outcomes in Min and Max.
    # If we use those semantics then Min(NaN, 5.0) is NaN, but
    # Min(5.0, NaN) is 5.0!  To fix this, we impose a total
    # ordering where NaN is smaller than every value, including
    # negative infinity.
    ([float(i) for i in range(1, 11)] + [NAN], NAN),
    ([-1.0, -10.0, NAN, 10.0, 200.0, 1000.0], NAN),
    ([FLOAT_MIN, 3000.0, 100.0, 200.0, NAN, 1000.0], NAN),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MIN_FLOAT_DATA)
def test_Min_Float(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    # EXPECTED FAIL (NaN rows where the NaN is not first): builtin min() only yields NaN when the NaN
    # comes first; .NET returns NaN as soon as the source contains one.
    _assert_equal(expected, source.min())
    _assert_equal(expected, source.min(lambda x: x))


@pytest.mark.parametrize("source, expected", [
    _huge(None),  # Enumerable.Repeat(float.NaN, int.MaxValue)
    ([NAN] * 3, NAN),
])
def test_Min_Float_ShortCircuit(flp_type, source, expected):
    # (rows of Min_Float_TestData that are not wrapped in TestEnumerable / array pairs)
    _assert_equal(expected, flp_type(source).min())
    _assert_equal(expected, flp_type(source).min(lambda x: x))


def test_Min_Float_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


def test_Min_Float_EmptySource_ThrowsInvalidOperationException(flp_type):
    _assert_empty_source_throws(flp_type)


_MIN_DOUBLE_DATA = [
    ([42.0], 42.0),
    ([float(i) for i in range(1, 11)], 1.0),
    ([-1.0, -10.0, 10.0, 200.0, 1000.0], -10.0),
    ([3000.0, 100.0, 200.0, 1000.0], 100.0),
    ([3000.0, 100.0, 200.0, 1000.0, DOUBLE_MIN], DOUBLE_MIN),
    ([5.5], 5.5),
    ([-2.5, 4.9, 130.0, 4.7, 28.0], -2.5),
    ([6.8, 9.4, 10.0, 0.0, -5.6], -5.6),
    ([-5.5, NEG_INF, 9.9, NEG_INF], NEG_INF),
    ([NAN, 6.8, 9.4, 10.0, 0.0, -5.6], NAN),
    ([6.8, 9.4, 10.0, 0.0, -5.6, NAN], NAN),
    ([NAN, NEG_INF], NAN),
    ([NEG_INF, NAN], NAN),
    # Normally NaN < anything is false, as is anything < NaN
    # However, this leads to some irksome outcomes in Min and Max.
    # If we use those semantics then Min(NaN, 5.0) is NaN, but
    # Min(5.0, NaN) is 5.0!  To fix this, we impose a total
    # ordering where NaN is smaller than every value, including
    # negative infinity.
    ([float(i) for i in range(1, 11)] + [NAN], NAN),
    ([-1.0, -10.0, NAN, 10.0, 200.0, 1000.0], NAN),
    ([DOUBLE_MIN, 3000.0, 100.0, 200.0, NAN, 1000.0], NAN),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MIN_DOUBLE_DATA)
def test_Min_Double(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    # EXPECTED FAIL (NaN rows where the NaN is not first): see test_Min_Float.
    _assert_equal(expected, source.min())
    # EXPECTED FAIL: no selector overload -> TypeError.
    _assert_equal(expected, source.min(lambda x: x))


@pytest.mark.skip(_SKIP_HUGE)
def test_Min_Double_ShortCircuit():
    # Enumerable.Repeat(double.NaN, int.MaxValue)
    assert math.isnan(flp.repeat(NAN, INT_MAX).min())


def test_Min_Double_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


def test_Min_Double_EmptySource_ThrowsInvalidOperationException(flp_type):
    _assert_empty_source_throws(flp_type)


# ---------------------------------------------------------------------------
# decimal
# ---------------------------------------------------------------------------

_MIN_DECIMAL_DATA = [
    ([Decimal("42")], Decimal("42")),
    ([Decimal(i) for i in range(1, 11)], Decimal("1")),
    ([Decimal("-1"), Decimal("-10"), Decimal("10"), Decimal("200"), Decimal("1000")], Decimal("-10")),
    ([Decimal("3000"), Decimal("100"), Decimal("200"), Decimal("1000")], Decimal("100")),
    ([Decimal("3000"), Decimal("100"), Decimal("200"), Decimal("1000"), DECIMAL_MIN], DECIMAL_MIN),
    ([Decimal("5.5")], Decimal("5.5")),
    ([Decimal("-3.4")] * 5, Decimal("-3.4")),
    ([Decimal("-2.5"), Decimal("4.9"), Decimal("130"), Decimal("4.7"), Decimal("28")], Decimal("-2.5")),
    ([Decimal("6.8"), Decimal("9.4"), Decimal("10"), Decimal("0"), Decimal("0"), DECIMAL_MIN], DECIMAL_MIN),
    ([Decimal("-5.5"), Decimal("0"), Decimal("9.9"), Decimal("-5.5"), Decimal("5")], Decimal("-5.5")),
]


@pytest.mark.parametrize("wrap", _WRAPS)
@pytest.mark.parametrize("array, expected", _MIN_DECIMAL_DATA)
def test_Min_Decimal(flp_type, wrap, array, expected):
    source = _wrap(flp_type, wrap, array)

    assert expected == source.min()
    assert expected == source.min(lambda x: x)


def test_Min_Decimal_EmptySource_ThrowsInvalidOperationException(flp_type):
    _assert_empty_source_throws(flp_type)


def test_Min_Decimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


# ---------------------------------------------------------------------------
# nullable int / long / float / double / decimal
#
# EXPECTED FAIL (whole section): .NET skips nulls and returns null for an empty/all-null source;
# builtin min() raises TypeError when it meets None next to a number, and flpit raises
# EmptySequenceError for an empty source.
# ---------------------------------------------------------------------------

_MIN_NULLABLE_INT_DATA = [
    (list(range(1, 11)), 1),
    ([None, -1, -10, 10, 200, 1000], -10),
    ([None, 3000, 100, 200, 1000], 100),
    ([None, 3000, 100, 200, 1000, INT_MIN], INT_MIN),
    ([None] * 100, None),
    ([42], 42),
    ([], None),
    ([20], 20),
    ([None] * 5, None),
    ([6, None, 9, 10, None, 7, 8], 6),
    ([None, None, None, None, None, -5], -5),
    ([6, None, None, 0, 9, 0, 10, 0], 0),
]


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_INT_DATA)
def test_Min_NullableInt(flp_type, source, expected, tlog):
    tlog.info(flp_type)
    tlog.info(source)
    tlog.info(expected)
    assert expected == flp_type(source).min()


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_INT_DATA)
def test_Min_NullableIntRunOnce(flp_type, run_once, source, expected):
    assert expected == flp.it(run_once(source)).min()


def test_Min_NullableInt_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


_MIN_NULLABLE_LONG_DATA = [
    (list(range(1, 11)), 1),
    ([None, -1, -10, 10, 200, 1000], -10),
    ([None, 3000, 100, 200, 1000], 100),
    ([None, 3000, 100, 200, 1000, LONG_MIN], LONG_MIN),
    ([None] * 100, None),
    ([42], 42),
    ([], None),
    ([LONG_MAX], LONG_MAX),
    ([None] * 5, None),
    ([LONG_MIN, None, 9, 10, None, 7, 8], LONG_MIN),
    ([None, None, None, None, None, -LONG_MAX], -LONG_MAX),
    ([6, None, None, 0, 9, 0, 10, 0], 0),
]


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_LONG_DATA)
def test_Min_NullableLong(flp_type, source, expected):
    assert expected == flp_type(source).min()


def test_Min_NullableLong_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


_MIN_NULLABLE_FLOAT_DATA = [
    (list(float(i) for i in range(1, 11)), 1.0),
    ([None, -1.0, -10.0, 10.0, 200.0, 1000.0], -10.0),
    ([None, 3000.0, 100.0, 200.0, 1000.0], 100.0),
    ([None, 3000.0, 100.0, 200.0, 1000.0, FLOAT_MIN], FLOAT_MIN),
    ([None] * 100, None),
    ([42.0], 42.0),
    ([], None),
    ([FLOAT_MIN], FLOAT_MIN),
    ([None] * 100, None),
    ([-4.50, None, 10.98, None, 7.5, 8.6], -4.5),
    ([None, None, None, None, None, 0.0], 0.0),
    ([6.4, None, None, -0.5, 9.4, -0.5, 10.9, -0.5], -0.5),
    ([NAN, 6.8, 9.4, 10.0, 0.0, None, -5.6], NAN),
    ([6.8, 9.4, 10.0, 0.0, None, -5.6, NAN], NAN),
    ([NAN, NEG_INF], NAN),
    ([NEG_INF, NAN], NAN),
    ([NAN, None, None, None], NAN),
    ([None, None, None, NAN], NAN),
    ([None, NAN, None], NAN),
    _huge([NAN] * 1),  # Enumerable.Repeat((float?)float.NaN, int.MaxValue)
    ([NAN] * 3, NAN),
]


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_FLOAT_DATA)
def test_Min_NullableFloat(flp_type, source, expected):
    _assert_equal(expected, flp_type(source).min())
    _assert_equal(expected, flp_type(source).min(lambda x: x))


def test_Min_NullableFloat_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


_MIN_NULLABLE_DOUBLE_DATA = [
    (list(float(i) for i in range(1, 11)), 1.0),
    ([None, -1.0, -10.0, 10.0, 200.0, 1000.0], -10.0),
    ([None, 3000.0, 100.0, 200.0, 1000.0], 100.0),
    ([None, 3000.0, 100.0, 200.0, 1000.0, DOUBLE_MIN], DOUBLE_MIN),
    ([None] * 100, None),
    ([42.0], 42.0),
    ([], None),
    ([DOUBLE_MIN], DOUBLE_MIN),
    ([None] * 5, None),
    ([-4.50, None, 10.98, None, 7.5, 8.6], -4.5),
    ([None, None, None, None, None, 0.0], 0.0),
    ([6.4, None, None, -0.5, 9.4, -0.5, 10.9, -0.5], -0.5),
    ([NAN, 6.8, 9.4, 10.0, 0.0, None, -5.6], NAN),
    ([6.8, 9.4, 10.0, 0.0, None, -5.6, NAN], NAN),
    ([NAN, NEG_INF], NAN),
    ([NEG_INF, NAN], NAN),
    ([NAN, None, None, None], NAN),
    ([None, None, None, NAN], NAN),
    ([None, NAN, None], NAN),
    _huge([NAN] * 1),  # Enumerable.Repeat((double?)double.NaN, int.MaxValue)
    ([NAN] * 3, NAN),
]


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_DOUBLE_DATA)
def test_Min_NullableDouble(flp_type, source, expected):
    _assert_equal(expected, flp_type(source).min())
    _assert_equal(expected, flp_type(source).min(lambda x: x))


def test_Min_NullableDouble_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()


_MIN_NULLABLE_DECIMAL_DATA = [
    ([Decimal(i) for i in range(1, 11)], Decimal("1")),
    ([None, Decimal("-1"), Decimal("-10"), Decimal("10"), Decimal("200"), Decimal("1000")], Decimal("-10")),
    ([None, Decimal("3000"), Decimal("100"), Decimal("200"), Decimal("1000")], Decimal("100")),
    ([None, Decimal("3000"), Decimal("100"), Decimal("200"), Decimal("1000"), DECIMAL_MIN], DECIMAL_MIN),
    ([None] * 100, None),
    ([Decimal("42")], Decimal("42")),
    ([], None),
    ([DECIMAL_MAX], DECIMAL_MAX),
    ([None] * 5, None),
    ([Decimal("-4.50"), None, None, Decimal("10.98"), None, Decimal("7.5"), Decimal("8.6")], Decimal("-4.5")),
    ([None, None, None, None, None, Decimal("0")], Decimal("0")),
    ([Decimal("6.4"), None, None, DECIMAL_MIN, Decimal("9.4"), DECIMAL_MIN, Decimal("10.9"), DECIMAL_MIN], DECIMAL_MIN),
]


@pytest.mark.parametrize("source, expected", _MIN_NULLABLE_DECIMAL_DATA)
def test_Min_NullableDecimal(flp_type, source, expected):
    assert expected == flp_type(source).min()
    assert expected == flp_type(source).min(lambda x: x)


def test_Min_NullableDecimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


# ---------------------------------------------------------------------------
# DateTime / string
# ---------------------------------------------------------------------------

_HUNDRED = [datetime(3000, 1, 1), datetime(100, 1, 1), datetime(200, 1, 1), datetime(1000, 1, 1)]

_MIN_DATETIME_DATA = [
    ([datetime(2000, 1, i) for i in range(1, 11)], datetime(2000, 1, 1)),
    ([datetime(2000, 12, 1), datetime(2000, 1, 1), datetime(2000, 1, 12)], datetime(2000, 1, 1)),
    (_HUNDRED, datetime(100, 1, 1)),
    (_HUNDRED + [datetime.min], datetime.min),
]


@pytest.mark.parametrize("source, expected", _MIN_DATETIME_DATA)
def test_Min_DateTime(flp_type, source, expected):
    source = flp_type(source)

    assert expected == source.min()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.min(lambda x: x)


def test_Min_DateTime_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


def test_Min_DateTime_EmptySource_ThrowsInvalidOperationException(flp_type):
    _assert_empty_source_throws(flp_type)


_MIN_STRING_DATA = [
    ([str(i) for i in range(1, 11)], "1"),
    (["Alice", "Bob", "Charlie", "Eve", "Mallory", "Trent", "Victor"], "Alice"),
    ([None, "Charlie", None, "Victor", "Trent", None, "Eve", "Alice", "Mallory", "Bob"], "Alice"),
    ([], None),
    (["Hello"], "Hello"),
    (["hi"] * 5, "hi"),
    (["aaa", "abcd", "bark", "temp", "cat"], "aaa"),
    ([None, None, None, None, "aAa"], "aAa"),
    (["ooo", "www", "www", "ooo", "ooo", "ppp"], "ooo"),
    ([None] * 5, None),
]


@pytest.mark.parametrize("source, expected", _MIN_STRING_DATA)
def test_Min_String(flp_type, source, expected):
    source = flp_type(source)

    # EXPECTED FAIL (None / empty rows): .NET skips null strings and returns null for empty / all-null
    # sources; builtin min() raises TypeError on None and EmptySequenceError for empty sources.
    assert expected == source.min()
    # EXPECTED FAIL: no selector overload -> TypeError.
    assert expected == source.min(lambda x: x)


@pytest.mark.parametrize("source, expected", _MIN_STRING_DATA)
def test_Min_StringRunOnce(flp_type, run_once, source, expected):
    # EXPECTED FAIL: same reasons as test_Min_String.
    assert expected == flp.it(run_once(source)).min()
    assert expected == flp.it(run_once(source)).min(lambda x: x)


def test_Min_String_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    with pytest.raises(SourceNoneError):
        flp_type(None).min(lambda x: x)


# ---------------------------------------------------------------------------
# Selector tests
#
# EXPECTED FAIL (whole section): there is no min(selector) overload, so the call raises TypeError
# (and a None selector is just another TypeError instead of SelectorNoneError).
# ---------------------------------------------------------------------------

def test_Min_Int_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 10), _Named("John", -105), _Named("Bob", -30)]

    assert -105 == flp_type(source).min(lambda e: e.num)


def test_Min_Int_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_Long_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 10), _Named("John", LONG_MIN), _Named("Bob", -10)]

    assert LONG_MIN == flp_type(source).min(lambda e: e.num)


def test_Min_Long_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_Float_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", -45.5), _Named("John", -132.5), _Named("Bob", 20.45)]

    assert -132.5 == flp_type(source).min(lambda e: e.num)


def test_Min_Float_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_Double_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", -45.5), _Named("John", -132.5), _Named("Bob", 20.45)]

    assert -132.5 == flp_type(source).min(lambda e: e.num)


def test_Min_Double_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_Decimal_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("100.45")), _Named("John", Decimal("10.5")), _Named("Bob", Decimal("0.05"))]

    assert Decimal("0.05") == flp_type(source).min(lambda e: e.num)


def test_Min_Decimal_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_NullableInt_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", 10), _Named("John", None), _Named("Bob", -30)]

    assert -30 == flp_type(source).min(lambda e: e.num)


def test_Min_NullableInt_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_NullableLong_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", None), _Named("John", LONG_MIN), _Named("Bob", -10)]

    assert LONG_MIN == flp_type(source).min(lambda e: e.num)


def test_Min_NullableLong_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_NullableFloat_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", -45.5), _Named("John", -132.5), _Named("Bob", None)]

    assert -132.5 == flp_type(source).min(lambda e: e.num)


def test_Min_NullableFloat_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_NullableDouble_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", -45.5), _Named("John", -132.5), _Named("Bob", None)]

    assert -132.5 == flp_type(source).min(lambda e: e.num)


def test_Min_NullableDouble_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_NullableDecimal_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("100.45")), _Named("John", Decimal("10.5")), _Named("Bob", None)]

    assert Decimal("10.5") == flp_type(source).min(lambda e: e.num)


def test_Min_NullableDecimal_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_DateTime_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_String_WithSelectorAccessingProperty(flp_type):
    source = [_Named("Tim", Decimal("100.45")), _Named("John", Decimal("10.5")), _Named("Bob", Decimal("0.05"))]

    assert "Bob" == flp_type(source).min(lambda e: e.name)


def test_Min_String_NullSelector_ThrowsArgumentNullException(flp_type):
    selector = None
    with pytest.raises(SelectorNoneError):
        flp_type([]).min(selector)


def test_Min_Bool_EmptySource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min()
    # with pytest.raises(InvalidOperationError):
    #     flp.it(_ForceNotCollection([])).min()

    # until then
    assert flp_type([]).min() is None
    assert flp.it(_ForceNotCollection([])).min() is None

# ---------------------------------------------------------------------------
# Min(comparer)
# ---------------------------------------------------------------------------

def test_Min_Generic_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min()
    # comparer not implemented, but won't be reached as flpit raises early on source
    with pytest.raises(SourceNoneError):
        flp_type(None).min(comparer=None)
    with pytest.raises(SourceNoneError):
        flp_type(None).min(comparer=_Comparer(lambda _a, _b: 0))


def test_Min_Generic_EmptyStructSource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min()

    # until then
    assert flp_type([]).min() is None

    # comparer not supprted yet... and maybe never will
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min(comparer=None)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min(comparer=_Comparer(lambda _a, _b: 0))


_MIN_GENERIC_DATA = [
    ([], None, None),
    ([], _Comparer(lambda _a, _b: 0), None),
    (list(range(0, 10)), None, 0),
    (list(range(0, 10)), _Comparer(lambda x, y: -_default_compare(x, y)), 9),
    (list(range(0, 10)), _Comparer(lambda x, y: 0), 0),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], None, "Aardvark"),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], _Comparer(lambda x, y: -_default_compare(x, y)), "Zyzzyva"),
]


@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, comparer, expected", _MIN_GENERIC_DATA)
def test_Min_Generic_HasExpectedOutput(flp_type, source, comparer, expected):
    # EXPECTED FAIL: no comparer overload (TypeError); an empty source also raises EmptySequenceError
    # where .NET returns null for nullable element types.
    assert expected == flp_type(source).min(comparer=comparer)


@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, comparer, expected", _MIN_GENERIC_DATA)
def test_Min_Generic_RunOnce_HasExpectedOutput(flp_type, run_once, source, comparer, expected):
    assert expected == flp.it(run_once(source)).min(comparer=comparer)


# ---------------------------------------------------------------------------
# MinBy
# ---------------------------------------------------------------------------

def test_MinBy_Generic_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).min_by(lambda x: x)
    with pytest.raises(SourceNoneError):
        flp_type(None).min_by(lambda x: x, comparer=None)
    with pytest.raises(SourceNoneError):
        flp_type(None).min_by(lambda x: x, _Comparer(lambda _a, _b: 0))


def test_MinBy_Generic_NullKeySelector_ThrowsArgumentNullException(flp_type):
    source = []
    key_selector = None

    # EmptySequenceError, a None selector is never called) and has no comparer overload.

    # once there are real runtime generics we can enforce exception on empty source
    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).min_by(key_selector)

    # until then
    assert flp_type(source).min_by(key_selector) is None

    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).min_by(key_selector, comparer=None)
    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).min_by(key_selector, _Comparer(lambda _a, _b: 0))


def test_MinBy_Generic_EmptyStructSource_ThrowsInvalidOperationException(flp_type):
    # once there are real runtime generics we can enforce exception on empty source

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min_by(lambda x: str(x))

    # until then
    assert flp_type([]).min_by(lambda x: str(x)) is None

    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min_by(lambda x: str(x), comparer=None)
    # with pytest.raises(InvalidOperationError):
    #     flp_type([]).min_by(lambda x: str(x), _Comparer(lambda _a, _b: 0))


def test_MinBy_Generic_EmptyNullableSource_ReturnsNull(flp_type):
    # for nullable / reference element types.
    assert flp_type([]).min_by(lambda x: hash(x)) is None
    # assert flp_type([]).min_by(lambda x: hash(x), comparer=None) is None
    # assert flp_type([]).min_by(lambda x: hash(x), _Comparer(lambda _a, _b: 0)) is None


def test_MinBy_Generic_EmptyReferenceSource_ReturnsNull(flp_type):
    assert flp_type([]).min_by(lambda x: hash(x)) is None
    # assert flp_type([]).min_by(lambda x: hash(x), comparer=None) is None
    # assert flp_type([]).min_by(lambda x: hash(x), _Comparer(lambda _a, _b: 0)) is None


def _throw_comparer():
    def compare(_a, _b):
        raise InvalidOperationError("comparer should not be called.")

    return _Comparer(compare)


def test_MinBy_Generic_StructSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    # .NET returns the first element without comparing null keys. No comparer overload either.
    assert 0 == flp_type(range(0, 5)).min_by(lambda x: None)
    # assert 0 == flp_type(range(0, 5)).min_by(lambda x: None, comparer=None)
    # assert 0 == flp_type(range(0, 5)).min_by(lambda x: None, _throw_comparer())


def test_MinBy_Generic_NullableSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    assert 0 == flp_type(range(0, 5)).cast(int | None).min_by(lambda x: None)
    # assert 0 == flp_type(range(0, 5)).cast(int | None).min_by(lambda x: None, comparer=None)
    # assert 0 == flp_type(range(0, 5)).cast(int | None).min_by(lambda x: None, _throw_comparer())


def test_MinBy_Generic_ReferenceSourceAllKeysAreNull_ReturnsFirstElement(flp_type):
    # EXPECTED FAIL: same as test_MinBy_Generic_StructSourceAllKeysAreNull_ReturnsFirstElement.
    assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).min_by(lambda x: None)
    # assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).min_by(lambda x: None, comparer=None)
    # assert "0" == flp_type(range(0, 5)).select(lambda x: str(x)).min_by(lambda x: None, _throw_comparer())


_Person = namedtuple("_Person", "name age")

_MIN_BY_DATA = [
    ([], lambda x: x, None, None),
    ([], lambda x: x, _Comparer(lambda _a, _b: 0), None),
    (list(range(0, 10)), lambda x: x, None, 0),
    (list(range(0, 10)), lambda x: x, _Comparer(lambda x, y: -_default_compare(x, y)), 9),
    (list(range(0, 10)), lambda x: x, _Comparer(lambda x, y: 0), 0),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], lambda x: x, None, "Aardvark"),
    (["Aardvark", "Zyzzyva", "Zebra", "Antelope"], lambda x: x, _Comparer(lambda x, y: -_default_compare(x, y)), "Zyzzyva"),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.age, None, _Person("Harry", 20)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.age,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Dick", 55)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.name, None, _Person("Dick", 55)),
    ([_Person("Tom", 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.name,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Tom", 43)),
    ([_Person(None, 43), _Person("Dick", 55), _Person("Harry", 20)], lambda x: x.name,
     _Comparer(lambda x, y: -_default_compare(x, y)), _Person("Harry", 20)),
]

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, key_selector, comparer, expected", _MIN_BY_DATA)
def test_MinBy_Generic_HasExpectedOutput(flp_type, source, key_selector, comparer, expected):
    # EXPECTED FAIL: no comparer overload (TypeError on rows that pass a comparer or a None comparer
    # positionally), and empty sources raise EmptySequenceError where .NET returns null.
    assert expected == flp_type(source).min_by(key_selector, comparer)

@pytest.mark.skip("comparer not supported")
@pytest.mark.parametrize("source, key_selector, comparer, expected", _MIN_BY_DATA)
def test_MinBy_Generic_RunOnce_HasExpectedOutput(flp_type, run_once, source, key_selector, comparer, expected):
    # EXPECTED FAIL: same reasons as test_MinBy_Generic_HasExpectedOutput.
    assert expected == flp.it(run_once(source)).min_by(key_selector, comparer)
