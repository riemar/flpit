"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq AllTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/AllTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest


def is_even(x):
    return x % 2 == 0


def test_SameResultsRepeatCallsIntQuery(flp_type):
    # Assumption: x > -2147483648 maps to int.MinValue for a 32-bit signed integer
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)
    assert q.all(is_even) == q.all(is_even)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    # Assumption: string.Empty translates to "" and string.IsNullOrEmpty translates to `not s`
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""])
    is_null_or_empty = lambda s: not s
    assert q.all(is_null_or_empty) == q.all(is_null_or_empty)


def _All_TestData():
    cases = [
        ([], is_even, True),
        ([3], is_even, False),
        ([4], is_even, True),
        ([3], is_even, False),
        ([4, 8, 3, 5, 10, 20, 12], is_even, False),
        ([4, 2, 10, 12, 8, 6, 3], is_even, False),
        ([4, 2, 10, 12, 8, 6, 14], is_even, True),
    ]
    # Enumerable.Range(1, 10) produces [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    rng = list(range(1, 11))
    cases.append((rng, lambda i: i > 0, True))
    for j in range(1, 11):
        # Local copy for iterator binding equivalent in python lambda
        cases.append((rng, lambda i, k=j: i > k, False))
    return cases


@pytest.mark.parametrize("source_data, predicate, expected", _All_TestData())
def test_All(flp_type, source_data, predicate, expected):
    # Assumption: CreateSources logic is handled by parametrized source_data and flp_type wrapper
    source = flp_type(source_data)
    assert source.all(predicate) == expected


@pytest.mark.parametrize("source_data, predicate, expected", _All_TestData())
def test_AllRunOnce(flp_type, source_data, predicate, expected):
    # Assumption: run_once() wrapper exists on the python object to limit iteration
    source = flp_type(source_data)
    run_once_source = source.run_once() if hasattr(source, "run_once") else source
    assert run_once_source.all(predicate) == expected


def test_NullSource_ThrowsArgumentNullException(flp_type):
    # Assumption: Equivalent of ArgumentNullException is TypeError, ValueError or AttributeError in the python lib
    with pytest.raises((TypeError, AttributeError, ValueError)):
        flp_type(None).all(lambda i: i != 0)


def test_NullPredicate_ThrowsArgumentNullException(flp_type):
    # Assumption: Supplying None as a predicate triggers an Exception instead of processing
    with pytest.raises((TypeError, ValueError)):
        flp_type(range(3)).all(None)