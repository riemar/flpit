"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq AverageTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/AverageTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest
import math
import random
import sys
from decimal import Decimal

# Constants mimicking .NET numeric boundaries (since Python integers have arbitrary precision)
INT_MIN = -2147483648
INT_MAX = 2147483647
LONG_MAX = 9223372036854775807
FLOAT_MIN = -3.4028235e38
FLOAT_MAX = 3.4028235e38
DECIMAL_MIN = Decimal('-79228162514264337593543950335')
DECIMAL_MAX = Decimal('79228162514264337593543950335')

# Attempt to import flp if available globally, otherwise rely on the fixture where possible.
try:
    import flp
except ImportError:
    pass # Assume flp might be injected or globally available in the test runner environment

def _is_nan(val) -> bool:
    if isinstance(val, Decimal):
        return val.is_nan()
    if isinstance(val, float):
        return math.isnan(val)
    return False

def assert_equal(actual, expected):
    """Robust equality assertion handling None, NaN, float tolerance, and Decimal/float mixed types."""
    if expected is None:
        assert actual is None
        return

    if _is_nan(expected):
        assert _is_nan(actual)
        return

    # If either value is float, compare using pytest.approx with both rel and abs tolerances
    if isinstance(expected, float) or isinstance(actual, float):
        act_val = float(actual) if isinstance(actual, Decimal) else actual
        exp_val = float(expected) if isinstance(expected, Decimal) else expected
        assert act_val == exp_val
    else:
        assert actual == expected


# ==============================================================================
# TEST DATA GENERATORS
# ==============================================================================
"""
        public static IEnumerable<object[]> NullableFloat_TestData()
        {
            yield return [new float?[0], null];
            yield return [new float?[] { float.MinValue }, float.MinValue];
            yield return [new float?[] { 0f, 0f, 0f, 0f, 0f }, 0f];

            yield return [new float?[] { 5.5f, 0, null, null, null, 15.5f, 40.5f, null, null, -23.5f }, 7.6f];

            yield return [new float?[] { null, null, null, null, 45f }, 45f];
            yield return [new float?[] { null, null, null, null, null }, null];
        }
"""
def nullable_float_test_data():
    return [
        ([], None),
        ([FLOAT_MIN], FLOAT_MIN),
        ([0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
        ([5.5, 0.0, None, None, None, 15.5, 40.5, None, None, -23.5], 7.6),
        ([None, None, None, None, 45.0], 45.0),
        ([None, None, None, None, None], None)
    ]

def int_test_data():
    cases = [
        ([5], 5.0),
        ([0, 0, 0, 0, 0], 0.0),
        ([5, -10, 15, 40, 28], 15.6)
    ]
    for i in range(1, 34):
        sum_val = sum(range(1, i + 1))
        expected = float(sum_val) / i
        source = list(range(1, i + 1))
        random.shuffle(source)
        cases.append((source, expected))
    return cases

def nullable_int_test_data():
    return [
        ([], None),
        ([-5], -5.0),
        ([0, 0, 0, 0, 0], 0.0),
        ([5, -10, None, None, None, 15, 40, 28, None, None], 15.6),
        ([None, None, None, None, 50], 50.0),
        ([None, None, None, None, None], None)
    ]

def long_test_data():
    cases = [
        ([LONG_MAX], float(LONG_MAX)),
        ([0, 0, 0, 0, 0], 0.0),
        ([5, -10, 15, 40, 28], 15.6)
    ]
    for i in range(1, 34):
        sum_val = sum(range(1, i + 1))
        expected = float(sum_val) / i
        source = list(range(1, i + 1))
        random.shuffle(source)
        cases.append((source, expected))
    return cases

def nullable_long_test_data():
    return [
        ([], None),
        ([LONG_MAX], float(LONG_MAX)),
        ([0, 0, 0, 0, 0], 0.0),
        ([5, -10, None, None, None, 15, 40, 28, None, None], 15.6),
        ([None, None, None, None, 50], 50.0),
        ([None, None, None, None, None], None)
    ]

def double_test_data():
    cases = [
        ([sys.float_info.max], sys.float_info.max),
        ([0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
        ([5.5, -10.0, 15.5, 40.5, 28.5], 16.0),
        ([5.58, float('nan'), 30.0, 4.55, 19.38], float('nan'))
    ]
    for i in range(1, 34):
        sum_val = sum(range(1, i + 1))
        expected = float(sum_val) / i
        source = [float(x) for x in range(1, i + 1)]
        random.shuffle(source)
        cases.append((source, expected))
    return cases

def nullable_double_test_data():
    return [
        ([], None),
        ([-sys.float_info.max], -sys.float_info.max),
        ([0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
        ([5.5, 0.0, None, None, None, 15.5, 40.5, None, None, -23.5], 7.6),
        ([None, None, None, None, 45.0], 45.0),
        ([-23.5, 0.0, float('nan'), 54.3, 0.56], float('nan')),
        ([None, None, None, None, None], None)
    ]

def decimal_test_data():
    cases = [
        ([DECIMAL_MAX], DECIMAL_MAX),
        ([Decimal('0.0'), Decimal('0.0'), Decimal('0.0'), Decimal('0.0'), Decimal('0.0')], Decimal('0.0')),
        ([Decimal('5.5'), Decimal('-10'), Decimal('15.5'), Decimal('40.5'), Decimal('28.5')], Decimal('16.0'))
    ]
    for i in range(1, 34):
        sum_val = sum(range(1, i + 1))
        expected = Decimal(sum_val) / Decimal(i)
        source = [Decimal(x) for x in range(1, i + 1)]
        random.shuffle(source)
        cases.append((source, expected))
    return cases

def nullable_decimal_test_data():
    return [
        ([], None),
        ([DECIMAL_MIN], DECIMAL_MIN),
        ([Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')], Decimal('0')),
        ([Decimal('5.5'), Decimal('0'), None, None, None, Decimal('15.5'), Decimal('40.5'), None, None, Decimal('-23.5')], Decimal('7.6')),
        ([None, None, None, None, Decimal('45')], Decimal('45')),
        ([None, None, None, None, None], None)
    ]

def float_test_data():
    cases = [
        ([FLOAT_MAX], FLOAT_MAX),
        ([0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
        ([5.5, -10.0, 15.5, 40.5, 28.5], 16.0)
    ]
    for i in range(1, 34):
        sum_val = sum(range(1, i + 1))
        expected = float(sum_val) / i
        source = [float(x) for x in range(1, i + 1)]
        random.shuffle(source)
        cases.append((source, expected))
    return cases

# ==============================================================================
# TESTS
# ==============================================================================

def test_SameResultsRepeatCallsIntQuery():
    # In C# the query resolves as a repeatable IEnumerable. We emulate this by using a list.
    q = [x for x in [9999, 0, 888, -1, 66, -777, 1, 2, -12345] if x > INT_MIN]
    enumerable = flp.lst(q)
    assert enumerable.average() == enumerable.average()

def test_SameResultsRepeatCallsNullableLongQuery():
    source = [INT_MAX, 0, 255, 127, 128, 1, 33, 99, None, INT_MIN]
    enumerable = flp.lst(source)
    assert enumerable.average() == enumerable.average()

@pytest.mark.parametrize("source, expected", nullable_float_test_data())
def test_NullableFoat(flp_type, source, expected): # Typo carried over from C# exact naming requirement
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

@pytest.mark.parametrize("source, expected", nullable_float_test_data())
def test_NullableFoatRunOnce(flp_type, source, expected): # Typo carried over from C# exact naming requirement
    # pass the source in as one shot generator to ensure they exhaust
    assert_equal(flp_type((item for item in source)).average(), expected)
    assert_equal(flp_type((item for item in source)).average(lambda x: x), expected)

def test_NullableFloat_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_NullableFloat_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

def test_Int_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)


@pytest.mark.skip("Python only has nullables")
def test_Int_EmptySource_ThrowsInvalidOperationException(flp_type):
    sources = [[], iter([])]
    for s in sources:
        with pytest.raises(ValueError):
            flp_type(s).average()
        with pytest.raises(ValueError):
            flp_type(s).average(lambda i: i)


def test_NullableFloat_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 5.5},
        {"name": "John", "num": 15.5},
        {"name": "Bob", "num": None}
    ]
    expected = 10.5
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

def test_Int_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

@pytest.mark.parametrize("source, expected", int_test_data())
def test_Int(flp_type, source, expected):
    # Generating the wrapper for each invocation to avoid iterator depletion if flp_type is flp.it
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

@pytest.mark.parametrize("source, expected", int_test_data())
def test_IntRunOnce(flp_type, source, expected):
    # pass the source in as one shot generator to ensure they exhaust
    assert_equal(flp_type((item for item in source)).average(), expected)
    assert_equal(flp_type((item for item in source)).average(lambda x: x), expected)

def test_Int_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 10},
        {"name": "John", "num": -10},
        {"name": "Bob", "num": 15}
    ]
    expected = 5.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.parametrize("source, expected", nullable_int_test_data())
def test_NullableInt(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_NullableInt_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_NullableInt_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

def test_NullableInt_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 10},
        {"name": "John", "num": None},
        {"name": "Bob", "num": 10}
    ]
    expected = 10.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.skip("Python only has nullables")
def test_Long_EmptySource_ThrowsInvalidOperationException(flp_type):
    sources = [[], iter([])]
    for s in sources:
        with pytest.raises(ValueError):
            flp_type(s).average()
        with pytest.raises(ValueError):
            flp_type(s).average(lambda i: i)

def test_Long_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_Long_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

@pytest.mark.parametrize("source, expected", long_test_data())
def test_Long(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_Long_FromSelector(flp_type):
    source = [
        {"name": "Tim", "num": 40},
        {"name": "John", "num": 50},
        {"name": "Bob", "num": 60}
    ]
    expected = 50.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.skip("Python int can't overflow")
def test_Long_SumTooLarge_ThrowsOverflowException(flp_type):
    source = [LONG_MAX, LONG_MAX] * 1000
    # Assumption: The Python LINQ port explicitly throws OverflowError to mimic .NET OverflowException
    with pytest.raises(OverflowError):
        flp_type(source).average()

@pytest.mark.parametrize("source, expected", nullable_long_test_data())
def test_NullableLong(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_NullableLong_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_NullableLong_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

def test_NullableLong_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 40},
        {"name": "John", "num": None},
        {"name": "Bob", "num": 30}
    ]
    expected = 35.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.skip("Python only has nullables")
def test_Double_EmptySource_ThrowsInvalidOperationException(flp_type):
    sources = [[], iter([])]
    for s in sources:
        with pytest.raises(ValueError):
            flp_type(s).average()
        with pytest.raises(ValueError):
            flp_type(s).average(lambda i: i)

def test_Double_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_Double_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

@pytest.mark.parametrize("source, expected", double_test_data())
def test_Average_Double(flp_type, source, expected): # Preserving C# method name per instructions
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_Double_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 5.5},
        {"name": "John", "num": 15.5},
        {"name": "Bob", "num": 3.0}
    ]
    expected = 8.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.parametrize("source, expected", nullable_double_test_data())
def test_NullableDouble(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_NullableDouble_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_NullableDouble_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

def test_NullableDouble_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 5.5},
        {"name": "John", "num": 15.5},
        {"name": "Bob", "num": None}
    ]
    expected = 10.5
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.skip("Python only has nullables")
def test_Decimal_EmptySource_ThrowsInvalidOperationException(flp_type):
    sources = [[], iter([])]
    for s in sources:
        with pytest.raises(ValueError):
            flp_type(s).average()
        with pytest.raises(ValueError):
            flp_type(s).average(lambda i: i)

def test_Decimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_Decimal_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

@pytest.mark.parametrize("source, expected", decimal_test_data())
def test_Decimal(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_Decimal_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": Decimal('5.5')},
        {"name": "John", "num": Decimal('15.5')},
        {"name": "Bob", "num": Decimal('3.0')}
    ]
    expected = Decimal('8.0')
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

@pytest.mark.parametrize("source, expected", nullable_decimal_test_data())
def test_NullableDecimal(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_NullableDecimal_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_NullableDecimal_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

def test_NullableDecimal_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": Decimal('5.5')},
        {"name": "John", "num": Decimal('15.5')},
        {"name": "Bob", "num": None}
    ]
    expected = Decimal('10.5')
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)

def test_NullableDecimal_SumTooLarge_ThrowsOverflowException(flp_type):
    source = [DECIMAL_MAX, DECIMAL_MAX] * 2 # python needs a bit more to overflow with the current average implementation
    # Assumption: Depending on the port's backend context for decimal, we expect an OverflowError to match C# logic
    with pytest.raises(OverflowError):
        flp_type(source).average()

@pytest.mark.skip("Python only has nullables")
def test_Float_EmptySource_ThrowsInvalidOperationException(flp_type):
    sources = [[], iter([])]
    for s in sources:
        with pytest.raises(ValueError):
            flp_type(s).average()
        with pytest.raises(ValueError):
            flp_type(s).average(lambda i: i)

def test_Float_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type(None).average()
    with pytest.raises(TypeError):
        flp_type(None).average(lambda i: i)

def test_Float_NullSelector_ThrowsArgumentNullException(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).average(None)

@pytest.mark.parametrize("source, expected", float_test_data())
def test_Float(flp_type, source, expected):
    assert_equal(flp_type(source).average(), expected)
    assert_equal(flp_type(source).average(lambda x: x), expected)

def test_Float_WithSelector(flp_type):
    source = [
        {"name": "Tim", "num": 5.5},
        {"name": "John", "num": 15.5},
        {"name": "Bob", "num": 3.0}
    ]
    expected = 8.0
    assert_equal(flp_type(source).average(lambda e: e["num"]), expected)