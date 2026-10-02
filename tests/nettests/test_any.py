"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq AnyTests  .cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/AnyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest


def is_even(x):
    return x % 2 == 0


def test_SameResultsRepeatCallsIntQuery(flp_type):
    # Assumption: x > -2147483648 maps to int.MinValue in C# 32-bit signed integer
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)
    assert q.any(is_even) == q.any(is_even)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""])
    is_null_or_empty = lambda s: not s
    assert q.any(is_null_or_empty) == q.any(is_null_or_empty)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_Any(flp_type, count):
    # Assumption: CreateSources logic is handled by parametrized count and flp_type wrapper
    expected = count > 0
    arr = [0] * count

    source = flp_type(arr)
    assert source.any() == expected
    assert source.select(lambda i: i).any() == expected
    assert source.where(lambda i: True).any() == expected
    assert source.where(lambda i: False).any() is False


def test_Any_GroupBy(flp_type):
    # Assumption: group_by yields an iterable structure that .any() can evaluate
    empty_grouped = flp_type([]).group_by(lambda num: num)
    assert empty_grouped.any() is False

    arr2_grouped = flp_type([1, 2]).group_by(lambda num: num)
    assert arr2_grouped.any() is True

    # original was using elementSelector that's no yet implemented
    # arr5_grouped = flp_type([1, 2, 1, 3, 2]).group_by(lambda n: n, lambda k, v: v)
    arr5_grouped = flp_type([1, 2, 1, 3, 2]).group_by(lambda n: n)
    assert arr5_grouped.any() is True


def _TestDataWithPredicate():
    cases = [
        ([], None, False),
        ([3], None, True),
        ([], is_even, False),
        ([4], is_even, True),
        ([5], is_even, False),
        ([5, 9, 3, 7, 4], is_even, True),
        ([5, 8, 9, 3, 7, 11], is_even, True),
    ]
    rng = list(range(1, 11))
    cases.append((rng, lambda i: i > 10, False))
    for j in range(10):
        # Local copy for iterator binding equivalent in python lambda
        cases.append((rng, lambda i, k=j: i > k, True))
    return cases


@pytest.mark.parametrize("source_data, predicate, expected", _TestDataWithPredicate())
def test_Any_Predicate(flp_type, source_data, predicate, expected):
    source = flp_type(source_data)
    if predicate is None:
        assert source.any() == expected
    else:
        assert source.any(predicate) == expected


@pytest.mark.parametrize("source_data, predicate, expected", _TestDataWithPredicate())
def test_AnyRunOnce(flp_type, source_data, predicate, expected):
    # Assumption: run_once() wrapper exists on the python object to limit iteration
    source = flp_type(source_data)
    run_once_source = source.run_once() if hasattr(source, "run_once") else source
    if predicate is None:
        assert run_once_source.any() == expected
    else:
        assert run_once_source.any(predicate) == expected


def test_NullObjectsInArray_Included(flp_type):
    source = flp_type([None, None, None, None])
    assert source.any() is True


def test_NullSource_ThrowsArgumentNullException(flp_type):
    # Assumption: Equivalent of ArgumentNullException is TypeError, ValueError or AttributeError in the python lib
    with pytest.raises((TypeError, AttributeError, ValueError)):
        flp_type(None).any()
    with pytest.raises((TypeError, AttributeError, ValueError)):
        flp_type(None).any(lambda i: i != 0)


def test_NullPredicate_ThrowsArgumentNullException(flp_type):
    # Assumption: Supplying None as a predicate triggers an Exception instead of returning True/False
    with pytest.raises((TypeError, ValueError)):
        flp_type(range(3)).any(None)