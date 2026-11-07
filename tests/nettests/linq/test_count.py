"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq CountTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/CountTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest
from flpit import flp

# ==============================================================================
# Helper Methods (Ported from C# EnumerableTests Base Class)
# ==============================================================================

def IsEven(x: int) -> bool:
    return x % 2 == 0

def RepeatedNumberGuaranteedNotCollectionType(number, count):
    for _ in range(count):
        yield number

def CreateSources(flp_type, iterable):
    """
    Simulates the C# CreateSources variant arrays.
    Converts the raw data stream into multiple underlying structural types.
    """
    # Materialize safely to prevent multi-consuming issues during list setup
    raw_list = list(iterable)

    # Return different underlying python representations wrapped by your fixture
    return [
        flp_type(raw_list),                     # Array/List alternative
        flp_type(tuple(raw_list)),              # ReadOnly/Immutable alternative
        flp_type((x for x in list(raw_list)))   # Pure One-Shot Generator alternative
    ]


# ==============================================================================
# Data Providers (Returning RAW Python structures to avoid pre-evaluation crashes)
# ==============================================================================

def Int_TestData_Raw():
    yield ([], None, 0)
    yield ([], IsEven, 0)
    yield ([4], IsEven, 1)
    yield ([5], IsEven, 0)
    yield ([2, 5, 7, 9, 29, 10], IsEven, 2)
    yield ([2, 20, 22, 100, 50, 10], IsEven, 6)

    # Generator data streams
    yield (RepeatedNumberGuaranteedNotCollectionType(0, 0), None, 0)
    yield (RepeatedNumberGuaranteedNotCollectionType(5, 1), None, 1)
    yield (RepeatedNumberGuaranteedNotCollectionType(5, 10), None, 10)


def EnumerateCollectionTypesAndCounts_Raw(count, enumerable):
    # Pass structural definitions downstream to handle inner matrix iterations
    return (count, list(enumerable))


def CountsAndTallies_Raw():
    count = 5
    r = range(1, count + 1)

    yield EnumerateCollectionTypesAndCounts_Raw(count, r)
    yield EnumerateCollectionTypesAndCounts_Raw(count, [float(x) for x in r])
    yield EnumerateCollectionTypesAndCounts_Raw(count, [float(x) for x in r]) # Double mirror
    yield EnumerateCollectionTypesAndCounts_Raw(count, [float(x) for x in r]) # Decimal mirror


def NonEnumeratedCount_SupportedEnumerables_Raw():
    yield (4, [1, 2, 3, 4])
    yield (4, list([1, 2, 3, 4]))
    yield (4, list([1, 2, 3, 4])) # Stack simulation
    yield (0, [])
    yield (100, range(1, 101))
    yield (80, [1] * 80)
    yield (20, list(reversed(range(1, 21))))
    yield (20, sorted(range(1, 21), key=lambda x: -x))
    yield (20, list(range(1, 11)) + list(range(11, 21)))

    # Optimized platform tracking mirrors
    yield (50, [x + 1 for x in range(1, 51)])
    yield (4, [x + 1 for x in [1, 2, 3, 4]])
    yield (50, [x - 1 for x in [x + 1 for x in range(1, 51)]])


def NonEnumeratedCount_UnsupportedEnumerables_Raw():
    # Structural elements failing O(1) tracking rules natively
    yield (x for x in range(1, 101) if x % 2 == 0)
    yield ((x % 2 == 0, x) for x in range(1, 101)) # GroupBy placeholder stream
    yield (x + 1 for x in [1,2,3,4])
    # ist incomplete and doesn't make sense as we don't have stack


# ==============================================================================
# Main Test Suites (Strictly prefixed with test_, utilizing flp_type inside)
# ==============================================================================

def test_SameResultsRepeatCallsIntQuery(flp_type):
    # query generation equivalent to Linq expression
    raw = [9999, 0, 888, -1, 66, -777, 1, 2, -12345]
    q = flp_type([x for x in raw if x > -2147483648])

    assert q.count() == q.count()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    raw = ["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]
    q = flp_type([x for x in raw if x != ""])

    assert q.count() == q.count()


@pytest.mark.parametrize("source, predicate, expected", list(Int_TestData_Raw()))
def test_it_Int(source, predicate, expected):
    it = flp.it(source)
    if predicate is None:
        assert expected == it.count()
    else:
        assert (expected == it.count(predicate))

@pytest.mark.parametrize("source, predicate, expected", list(Int_TestData_Raw()))
def test_it_Int(source, predicate, expected):
    it = flp.lst(source)
    if predicate is None:
        assert expected == it.count()
    else:
        assert (expected == it.count(predicate))



# @pytest.mark.parametrize("source, predicate, expected", list(Int_TestData_Raw()))
# def test_IntRunOnce(flp_type, source, predicate, expected):
#     for src in CreateSources(flp_type, source):
#         if predicate is None:
#             assert expected == src.run_once().count()
#         else:
#             assert expected == src.run_once().count(predicate)


def test_NullableIntArray_IncludesNullObjects(flp_type):
    data = flp_type([-10, 4, 9, None, 11])
    assert data.count() == 5


@pytest.mark.parametrize("count, enumerable", list(CountsAndTallies_Raw()))
def test_CountMatchesTally(flp_type, count, enumerable):
    for src in CreateSources(flp_type, enumerable):
        assert count == src.count()


@pytest.mark.parametrize("count, enumerable", list(CountsAndTallies_Raw()))
def test_RunOnce(flp_type, count, enumerable):
    it = flp_type(x for x in enumerable) # we just one-shot generatoring it
    assert count == it.count()


def test_NullSource_ThrowsArgumentNullException(flp_type):
    # Pass None straight into the test target instance construction
    with pytest.raises((AttributeError, TypeError, ValueError)):
        flp_type(None).count()

    with pytest.raises((AttributeError, TypeError, ValueError)):
        flp_type(None).count(lambda i: i != 0)


def test_NullPredicate_ThrowsArgumentNullException(flp_type):
    with pytest.raises((AttributeError, TypeError, ValueError)):
        flp_type(range(0, 3)).count(None)


def test_NonEnumeratedCount_NullSource_ThrowsArgumentNullException(flp_type):
    with pytest.raises((AttributeError, TypeError, ValueError)):
        flp_type(None).try_get_non_enumerated_count()


@pytest.mark.skip("Python doesn't have unsupported types")
@pytest.mark.parametrize("expected_count, source", list(NonEnumeratedCount_SupportedEnumerables_Raw()))
def test_NonEnumeratedCount_SupportedEnumerables_ShouldReturnExpectedCount(flp_type, expected_count, source):
    instance = flp_type(source)
    success, actual_count = instance.try_get_non_enumerated_count()

    assert success is True
    assert expected_count == actual_count


@pytest.mark.skip("Python doesn't have unsupported types")
@pytest.mark.parametrize("source", list(NonEnumeratedCount_UnsupportedEnumerables_Raw()))
def test_NonEnumeratedCount_UnsupportedEnumerables_ShouldReturnFalse(flp_type, source):
    instance = flp_type(source)
    success, actual_count = instance.try_get_non_enumerated_count()

    assert success is False
    assert actual_count == 0

@pytest.mark.skip(".NET testing their own helper")
def test_NonEnumeratedCount_ShouldNotEnumerateSource(flp_type):
    is_enumerated = False

    def Source():
        nonlocal is_enumerated
        is_enumerated = True
        yield 42

    instance = flp_type(Source())
    success, count = instance.try_get_non_enumerated_count()

    assert success is False
    assert count == 0
    assert is_enumerated is False
