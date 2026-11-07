"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SumTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SumTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import math
import sys
from decimal import Decimal
from types import SimpleNamespace
import pytest


INT_MAX = 2_147_483_647
INT_MIN = -2_147_483_648
LONG_MAX = 9_223_372_036_854_775_807
LONG_MIN = -9_223_372_036_854_775_808
FLOAT_MAX = 3.402823466e38
DOUBLE_MAX = sys.float_info.max
DECIMAL_MAX = Decimal("79228162514264337593543950335")
VECTOR_INT_COUNT = 4  # Assumption for SIMD Vector<int>.Count in Python port
VECTOR_LONG_COUNT = 2  # Assumption for SIMD Vector<long>.Count in Python port


# Helper for parametrized vector overflow tests
def SumOverflowsVerticalVectorLanes():
    for element in range(2):
        for verticalOffset in range(1, 6):
            yield element, verticalOffset


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfInt_SourceIsNull_ArgumentNullExceptionThrown():
    source_int = None
    with pytest.raises((TypeError, ValueError)):
        source_int.sum()
    with pytest.raises((TypeError, ValueError)):
        source_int.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfNullableOfInt_SourceIsNull_ArgumentNullExceptionThrown():
    source_nullable_int = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_int.sum()
    with pytest.raises((TypeError, ValueError)):
        source_nullable_int.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfLong_SourceIsNull_ArgumentNullExceptionThrown():
    source_long = None
    with pytest.raises((TypeError, ValueError)):
        source_long.sum()
    with pytest.raises((TypeError, ValueError)):
        source_long.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfNullableOfLong_SourceIsNull_ArgumentNullExceptionThrown():
    source_nullable_long = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_long.sum()
    with pytest.raises((TypeError, ValueError)):
        source_nullable_long.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfFloat_SourceIsNull_ArgumentNullExceptionThrown():
    source_float = None
    with pytest.raises((TypeError, ValueError)):
        source_float.sum()
    with pytest.raises((TypeError, ValueError)):
        source_float.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfNullableOfFloat_SourceIsNull_ArgumentNullExceptionThrown():
    source_nullable_float = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_float.sum()
    with pytest.raises((TypeError, ValueError)):
        source_nullable_float.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfDouble_SourceIsNull_ArgumentNullExceptionThrown():
    source_double = None
    with pytest.raises((TypeError, ValueError)):
        source_double.sum()
    with pytest.raises((TypeError, ValueError)):
        source_double.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfNullableOfDouble_SourceIsNull_ArgumentNullExceptionThrown():
    source_nullable_double = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_double.sum()
    with pytest.raises((TypeError, ValueError)):
        source_nullable_double.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfDecimal_SourceIsNull_ArgumentNullExceptionThrown():
    source_decimal = None
    with pytest.raises((TypeError, ValueError)):
        source_decimal.sum()
    with pytest.raises((TypeError, ValueError)):
        source_decimal.sum(lambda x: x)


@pytest.mark.skip("Python can't invoke extension methods on None")
def test_SumOfNullableOfDecimal_SourceIsNull_ArgumentNullExceptionThrown():
    source_nullable_decimal = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_decimal.sum()
    with pytest.raises((TypeError, ValueError)):
        source_nullable_decimal.sum(lambda x: x)

# in the following group one would be sufficient as in Python they all test the sem
# I keep them for completeness's sake

def test_SumOfInt_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_int = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_int.sum(selector)


def test_SumOfNullableOfInt_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_nullable_int = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_int.sum(selector)


def test_SumOfLong_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_long = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_long.sum(selector)


def test_SumOfNullableOfLong_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_nullable_long = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_long.sum(selector)


def test_SumOfFloat_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_float = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_float.sum(selector)


def test_SumOfNullableOfFloat_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_nullable_float = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_float.sum(selector)


def test_SumOfDouble_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_double = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_double.sum(selector)


def test_SumOfNullableOfDouble_SelectorIsNull_ArgumentNullExceptionThrown(
        flp_type,
):
    source_nullable_double = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_double.sum(selector)


def test_SumOfDecimal_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source_decimal = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_decimal.sum(selector)


def test_SumOfNullableOfDecimal_SelectorIsNull_ArgumentNullExceptionThrown(
        flp_type,
):
    source_nullable_decimal = flp_type([])
    selector = None
    with pytest.raises((TypeError, ValueError)):
        source_nullable_decimal.sum(selector)


# Region: SourceIsEmptyCollection - ZeroReturned


def test_SumOfInt_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_int = flp_type([])
    assert source_int.sum() == 0
    assert source_int.sum(lambda x: x) == 0


def test_SumOfNullableOfInt_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_nullable_int = flp_type([])
    assert source_nullable_int.sum() == 0
    assert source_nullable_int.sum(lambda x: x) == 0


def test_SumOfLong_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_long = flp_type([])
    assert source_long.sum() == 0
    assert source_long.sum(lambda x: x) == 0


def test_SumOfNullableOfLong_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_nullable_long = flp_type([])
    assert source_nullable_long.sum() == 0
    assert source_nullable_long.sum(lambda x: x) == 0


def test_SumOfFloat_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_float = flp_type([])
    assert source_float.sum() == 0.0
    assert source_float.sum(lambda x: x) == 0.0


def test_SumOfNullableOfFloat_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_nullable_float = flp_type([])
    assert source_nullable_float.sum() == 0.0
    assert source_nullable_float.sum(lambda x: x) == 0.0


def test_SumOfDouble_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_double = flp_type([])
    assert source_double.sum() == 0.0
    assert source_double.sum(lambda x: x) == 0.0


def test_SumOfNullableOfDouble_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_nullable_double = flp_type([])
    assert source_nullable_double.sum() == 0.0
    assert source_nullable_double.sum(lambda x: x) == 0.0


def test_SumOfDecimal_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_decimal = flp_type([])
    assert source_decimal.sum() == Decimal(0)
    assert source_decimal.sum(lambda x: x) == Decimal(0)


def test_SumOfNullableOfDecimal_SourceIsEmptyCollection_ZeroReturned(flp_type):
    source_nullable_decimal = flp_type([])
    assert source_nullable_decimal.sum() == Decimal(0)
    assert source_nullable_decimal.sum(lambda x: x) == Decimal(0)


# the next group
# Region: SourceIsNotEmpty - ProperSumReturned


def test_SumOfInt_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_int = flp_type([1, -2, 3, -4])
    assert source_int.sum() == -2
    assert source_int.sum(lambda x: x) == -2


def test_SumOfNullableOfInt_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_nullable_int = flp_type([1, -2, None, 3, -4, None])
    assert source_nullable_int.sum() == -2
    assert source_nullable_int.sum(lambda x: x) == -2


def test_SumOfLong_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_long = flp_type([1, -2, 3, -4])
    assert source_long.sum() == -2
    assert source_long.sum(lambda x: x) == -2


def test_SumOfNullableOfLong_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_nullable_long = flp_type([1, -2, None, 3, -4, None])
    assert source_nullable_long.sum() == -2
    assert source_nullable_long.sum(lambda x: x) == -2


def test_SumOfFloat_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_float = flp_type([1.0, 0.5, -1.0, 0.5])
    assert source_float.sum() == 1.0
    assert source_float.sum(lambda x: x) == 1.0


def test_SumOfNullableOfFloat_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_nullable_float = flp_type([1.0, 0.5, None, -1.0, 0.5, None])
    assert source_nullable_float.sum() == 1.0
    assert source_nullable_float.sum(lambda x: x) == 1.0


def test_SumOfDouble_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_double = flp_type([1.0, 0.5, -1.0, 0.5])
    assert source_double.sum() == 1.0
    assert source_double.sum(lambda x: x) == 1.0


def test_SumOfNullableOfDouble_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_nullable_double = flp_type([1.0, 0.5, None, -1.0, 0.5, None])
    assert source_nullable_double.sum() == 1.0
    assert source_nullable_double.sum(lambda x: x) == 1.0


def test_SumOfDecimal_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_decimal = flp_type(
        [Decimal("1"), Decimal("0.5"), Decimal("-1"), Decimal("0.5")]
    )
    assert source_decimal.sum() == Decimal("1")
    assert source_decimal.sum(lambda x: x) == Decimal("1")


def test_SumOfNullableOfDecimal_SourceIsNotEmpty_ProperSumReturned(flp_type):
    source_nullable_decimal = flp_type(
        [
            Decimal("1"),
            Decimal("0.5"),
            None,
            Decimal("-1"),
            Decimal("0.5"),
            None,
        ]
    )
    assert source_nullable_decimal.sum() == Decimal("1")
    assert source_nullable_decimal.sum(lambda x: x) == Decimal("1")


# Region: SourceSumsToOverflow - OverflowExceptionThrown or Infinity returned

@pytest.mark.skip("Python int can't overflow")
def test_SumOfInt_SourceSumsToOverflow_OverflowExceptionThrown(flp_type):
    source_int = flp_type([INT_MAX, 1])
    with pytest.raises(OverflowError):
        source_int.sum()
    with pytest.raises(OverflowError):
        source_int.sum(lambda x: x)


@pytest.mark.skip("Python int can't overflow")
def test_SumOfInt_SourceSumsToOverflowVectorHorizontally_OverflowExceptionThrown(
        flp_type,
):
    source_int = [0] * (VECTOR_INT_COUNT * 4)
    for i in range(VECTOR_INT_COUNT):
        source_int[i] = INT_MAX - 3
    for i in range(VECTOR_INT_COUNT, len(source_int)):
        source_int[i] = 1

    wrapped = flp_type(source_int)
    with pytest.raises(OverflowError):
        wrapped.sum()


@pytest.mark.skip("Python int can't overflow")
@pytest.mark.parametrize("element, verticalOffset", SumOverflowsVerticalVectorLanes())
def test_SumOfInt_SourceSumsToOverflowVectorVertically_OverflowExceptionThrown(
        flp_type, element, verticalOffset
):
    source_int = [0] * (VECTOR_INT_COUNT * 6)
    source_int[element] = INT_MAX
    source_int[element + VECTOR_INT_COUNT * verticalOffset] = 1

    wrapped = flp_type(source_int)
    with pytest.raises(OverflowError):
        wrapped.sum()


@pytest.mark.skip("Python int can't overflow")
def test_SumOfNullableOfInt_SourceSumsToOverflow_OverflowExceptionThrown(flp_type):
    source_nullable_int = flp_type([INT_MAX, None, 1])
    with pytest.raises(OverflowError):
        source_nullable_int.sum()
    with pytest.raises(OverflowError):
        source_nullable_int.sum(lambda x: x)


@pytest.mark.skip("Python int can't overflow")
def test_SumOfLong_SourceSumsToOverflow_OverflowExceptionThrown(flp_type):
    source_long = flp_type([LONG_MAX, 1])
    with pytest.raises(OverflowError):
        source_long.sum()
    with pytest.raises(OverflowError):
        source_long.sum(lambda x: x)


@pytest.mark.skip("Python int can't overflow")
def test_SumOfLong_SourceSumsToOverflowVectorHorizontally_OverflowExceptionThrown(
        flp_type,
):
    source_long = [0] * (VECTOR_LONG_COUNT * 4)
    for i in range(VECTOR_LONG_COUNT):
        source_long[i] = LONG_MAX - 3
    for i in range(VECTOR_LONG_COUNT, len(source_long)):
        source_long[i] = 1

    wrapped = flp_type(source_long)
    with pytest.raises(OverflowError):
        wrapped.sum()


@pytest.mark.skip("Python int can't overflow")
@pytest.mark.parametrize("element, verticalOffset", SumOverflowsVerticalVectorLanes())
def test_SumOfLong_SourceSumsToOverflowVectorVertically_OverflowExceptionThrown(
        flp_type, element, verticalOffset
):
    source_long = [0] * (VECTOR_LONG_COUNT * 6)
    source_long[element] = LONG_MAX
    source_long[element + VECTOR_LONG_COUNT * verticalOffset] = 1

    wrapped = flp_type(source_long)
    with pytest.raises(OverflowError):
        wrapped.sum()


@pytest.mark.skip("Python int can't overflow")
def test_SumOfNullableOfLong_SourceSumsToOverflow_OverflowExceptionThrown(flp_type):
    source_nullable_long = flp_type([LONG_MAX, None, 1])
    with pytest.raises(OverflowError):
        source_nullable_long.sum()
    with pytest.raises(OverflowError):
        source_nullable_long.sum(lambda x: x)


@pytest.mark.skip("Python float only overflows at c# double boundary")
def test_SumOfFloat_SourceSumsToOverflow_InfinityReturned(flp_type):
    source_float = flp_type([FLOAT_MAX, FLOAT_MAX])
    assert math.isinf(source_float.sum()) and source_float.sum() > 0
    assert math.isinf(source_float.sum(lambda x: x)) and source_float.sum(
        lambda x: x
    ) > 0


@pytest.mark.skip("Python float only overflows at c# double boundary")
def test_SumOfNullableOfFloat_SourceSumsToOverflow_InfinityReturned(flp_type):
    source_nullable_float = flp_type([FLOAT_MAX, None, FLOAT_MAX])
    res = source_nullable_float.sum()
    assert math.isinf(res) and res > 0
    res_sel = source_nullable_float.sum(lambda x: x)
    assert math.isinf(res_sel) and res_sel > 0


def test_SumOfDouble_SourceSumsToOverflow_InfinityReturned(flp_type):
    source_double = flp_type([DOUBLE_MAX, DOUBLE_MAX])
    assert math.isinf(source_double.sum()) and source_double.sum() > 0
    assert math.isinf(source_double.sum(lambda x: x)) and source_double.sum(
        lambda x: x
    ) > 0


def test_SumOfNullableOfDouble_SourceSumsToOverflow_InfinityReturned(flp_type):
    source_nullable_double = flp_type([DOUBLE_MAX, None, DOUBLE_MAX])
    res = source_nullable_double.sum()
    assert math.isinf(res) and res > 0
    res_sel = source_nullable_double.sum(lambda x: x)
    assert math.isinf(res_sel) and res_sel > 0


def test_SumOfDecimal_SourceSumsToOverflow_OverflowExceptionThrown(flp_type):
    source_decimal = flp_type([DECIMAL_MAX, Decimal(1)] * 2)
    with pytest.raises(OverflowError):
        source_decimal.sum()
    with pytest.raises(OverflowError):
        source_decimal.sum(lambda x: x)


def test_SumOfNullableOfDecimal_SourceSumsToOverflow_OverflowExceptionThrown(
        flp_type,
):
    source_nullable_decimal = flp_type([DECIMAL_MAX, None, Decimal(1)] * 2)
    with pytest.raises(OverflowError):
        source_nullable_decimal.sum()
    with pytest.raises(OverflowError):
        source_nullable_decimal.sum(lambda x: x)


# Individual tests


def test_SameResultsRepeatCallsIntQuery(flp_type):
    raw_source = [9999, 0, 888, -1, 66, None, -777, 1, 2, -12345]
    # LINQ query: where x > int.MinValue
    q = flp_type([x for x in raw_source if x is None or x > INT_MIN])
    assert q.sum() == q.sum()


def test_SolitaryNullableSingle(flp_type):
    source = flp_type([20.51])
    assert source.first_or_default(0) == pytest.approx(source.sum())


def test_NaNFromSingles(flp_type):
    source = flp_type([20.45, 0.0, -10.55, float("nan")])
    assert math.isnan(source.sum())


def test_NullableSingleAllNull(flp_type):
    source = flp_type([None] * 4)
    assert source.sum() == 0.0


@pytest.mark.skip("Python float only overflows at c# double boundary")
def test_NullableSingleToNegativeInfinity(flp_type):
    source = flp_type([-FLOAT_MAX, -FLOAT_MAX])
    res = source.sum()
    assert math.isinf(res) and res < 0


def test_NullableSingleFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=9.5),
            SimpleNamespace(name="John", num=None),
            SimpleNamespace(name="Bob", num=8.5),
        ]
    )
    assert source.sum(lambda e: e.num) == pytest.approx(18.0)


def test_SolitaryInt32(flp_type):
    source = flp_type([20])
    assert source.first_or_default(0) == source.sum()


@pytest.mark.skip("Python int can't overflow")
def test_OverflowInt32Negative(flp_type):
    # -INT_MAX = -2147483647; adding -5 and -20 causes negative overflow below INT_MIN (-2147483648)
    source = flp_type([-INT_MAX, 0, -5, -20])
    with pytest.raises(OverflowError):
        source.sum()


def test_Int32FromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=10),
            SimpleNamespace(name="John", num=50),
            SimpleNamespace(name="Bob", num=-30),
        ]
    )
    assert source.sum(lambda e: e.num) == 30


def test_SolitaryNullableInt32(flp_type):
    source = flp_type([-9])
    assert source.first_or_default(0) == source.sum()


def test_NullableInt32AllNull(flp_type):
    source = flp_type([None] * 5)
    assert source.sum() == 0


@pytest.mark.skip("Python int can't overflow")
def test_NullableInt32NegativeOverflow(flp_type):
    source = flp_type([-INT_MAX, 0, -5, None, None, -20])
    with pytest.raises(OverflowError):
        source.sum()


def test_NullableInt32FromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=10),
            SimpleNamespace(name="John", num=None),
            SimpleNamespace(name="Bob", num=-30),
        ]
    )
    assert source.sum(lambda e: e.num) == -20


def test_RunOnce(flp_type):
    source = flp_type(
        (
            item for item in
            [
                SimpleNamespace(name="Tim", num=10),
                SimpleNamespace(name="John", num=None),
                SimpleNamespace(name="Bob", num=-30),
            ]
        ) # one shot generator
    )
    # original had run_once(), so we one-shot
    assert source.sum(lambda e: e.num) == -20


def test_SolitaryInt64(flp_type):
    source = flp_type([INT_MAX + 20])
    assert source.first_or_default(0) == source.sum()


@pytest.mark.skip("Python int can't overflow")
def test_NullableInt64NegativeOverflow(flp_type):
    source = flp_type([-LONG_MAX, 0, -5, 20, -16])
    with pytest.raises(OverflowError):
        source.sum()


def test_Int64FromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=10),
            SimpleNamespace(name="John", num=INT_MAX),
            SimpleNamespace(name="Bob", num=40),
        ]
    )
    assert source.sum(lambda e: e.num) == INT_MAX + 50


def test_SolitaryNullableInt64(flp_type):
    source = flp_type([-INT_MAX - 20])
    assert source.first_or_default(0) == source.sum()


def test_NullableInt64AllNull(flp_type):
    source = flp_type([None] * 5)
    assert source.sum() == 0

@pytest.mark.skip("Python int can't overflow")
def test_Int64NegativeOverflow(flp_type):
    source = flp_type([-LONG_MAX, 0, -5, -20, None, None])
    with pytest.raises(OverflowError):
        source.sum()


def test_NullableInt64FromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=10),
            SimpleNamespace(name="John", num=INT_MAX),
            SimpleNamespace(name="Bob", num=None),
        ]
    )
    assert source.sum(lambda e: e.num) == INT_MAX + 10


def test_SolitaryDouble(flp_type):
    source = flp_type([20.51])
    assert source.first_or_default(0) == pytest.approx(source.sum())


def test_DoubleWithNaN(flp_type):
    source = flp_type([20.45, 0, -10.55, float("nan")])
    assert math.isnan(source.sum())


def test_DoubleToNegativeInfinity(flp_type):
    source = flp_type([-DOUBLE_MAX, -DOUBLE_MAX])
    res = source.sum()
    assert math.isinf(res) and res < 0


def test_DoubleFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=9.5),
            SimpleNamespace(name="John", num=10.5),
            SimpleNamespace(name="Bob", num=3.5),
        ]
    )
    assert source.sum(lambda e: e.num) == pytest.approx(23.5)


def test_SolitaryNullableDouble(flp_type):
    source = flp_type([20.51])
    assert source.first_or_default(0) == pytest.approx(source.sum())


def test_NullableDoubleAllNull(flp_type):
    source = flp_type([None] * 4)
    assert source.sum() == 0.0


def test_NullableDoubleToNegativeInfinity(flp_type):
    source = flp_type([-DOUBLE_MAX, -DOUBLE_MAX])
    res = source.sum()
    assert math.isinf(res) and res < 0


def test_NullableDoubleFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=9.5),
            SimpleNamespace(name="John", num=None),
            SimpleNamespace(name="Bob", num=8.5),
        ]
    )
    assert source.sum(lambda e: e.num) == pytest.approx(18.0)


def test_SolitaryDecimal(flp_type):
    source = flp_type([Decimal("20.51")])
    assert source.first_or_default(0) == source.sum()


def test_DecimalNegativeOverflow(flp_type):
    source = flp_type([-DECIMAL_MAX, -DECIMAL_MAX] * 7 ) # with prec 29 we need 14 to overshoot
    with pytest.raises(OverflowError):
        source.sum()


def test_DecimalFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=Decimal("20.51")),
            SimpleNamespace(name="John", num=Decimal("10")),
            SimpleNamespace(name="Bob", num=Decimal("2.33")),
        ]
    )
    assert source.sum(lambda e: e.num) == Decimal("32.84")


def test_SolitaryNullableDecimal(flp_type):
    source = flp_type([Decimal("20.51")])
    assert source.first_or_default(0) == source.sum()


def test_NullableDecimalAllNull(flp_type):
    source = flp_type([None] * 3)
    assert source.sum() == Decimal(0)


def test_NullableDecimalNegativeOverflow(flp_type):
    source = flp_type([-DECIMAL_MAX, -DECIMAL_MAX] * 7)
    with pytest.raises(OverflowError):
        source.sum()


def test_NullableDecimalFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=Decimal("20.51")),
            SimpleNamespace(name="John", num=None),
            SimpleNamespace(name="Bob", num=Decimal("2.33")),
        ]
    )
    assert source.sum(lambda e: e.num) == Decimal("22.84")


def test_SolitarySingle(flp_type):
    source = flp_type([20.51])
    assert source.first_or_default(0) == pytest.approx(source.sum())


@pytest.mark.skip("Python float only overflows at c# double boundary")
def test_SingleToNegativeInfinity(flp_type):
    source = flp_type([-FLOAT_MAX, -FLOAT_MAX])
    res = source.sum()
    assert math.isinf(res) and res < 0


def test_SingleFromSelector(flp_type):
    source = flp_type(
        [
            SimpleNamespace(name="Tim", num=9.5),
            SimpleNamespace(name="John", num=10.5),
            SimpleNamespace(name="Bob", num=3.5),
        ]
    )
    assert source.sum(lambda e: e.num) == pytest.approx(23.5)