"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq AggregateTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/AggregateTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).

The overloads follow the .NET shapes, dispatched by positional arity:
    aggregate(func)
    aggregate(seed, func)
    aggregate(seed, func, result_selector)
"""

import pytest

from conftest import create_sources
from flpit import (
    flp,
    EmptySequenceError,
    FuncNoneError,
    ResultSelectorNoneError,
    SourceNoneError,
)


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)

    assert q.aggregate(lambda x, y: x + y) == q.aggregate(lambda x, y: x + y)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: bool(x))

    assert q.aggregate(lambda x, y: x + y) == q.aggregate(lambda x, y: x + y)


def test_EmptySource(flp_type):
    source = []

    for source in create_sources(flp_type)(source):
        with pytest.raises(EmptySequenceError):
            source.aggregate(lambda x, y: x + y)

        with pytest.raises(EmptySequenceError):
            flp.it(_run_once(source)).aggregate(lambda x, y: x + y)


def test_SingleElement(flp_type):
    source = [5]
    expected = 5

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(lambda x, y: x + y)


def test_SingleElementRunOnce(flp_type):
    source = [5]
    expected = 5

    for source in create_sources(flp_type)(source):
        assert expected == flp.it(_run_once(source)).aggregate(lambda x, y: x + y)


def test_TwoElements(flp_type):
    source = [5, 6]
    expected = 11

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(lambda x, y: x + y)


def test_MultipleElements(flp_type):
    source = [5, 6, 0, -4]
    expected = 7

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(lambda x, y: x + y)


def test_MultipleElementsRunOnce(flp_type):
    source = [5, 6, 0, -4]
    expected = 7

    for source in create_sources(flp_type)(source):
        assert expected == flp.it(_run_once(source)).aggregate(lambda x, y: x + y)


def test_EmptySourceAndSeed(flp_type):
    source = []
    seed = 2
    expected = 2

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y)


def test_SingleElementAndSeed(flp_type):
    source = [5]
    seed = 2
    expected = 10

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y)


def test_TwoElementsAndSeed(flp_type):
    source = [5, 6]
    seed = 2
    expected = 60

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y)


def test_MultipleElementsAndSeed(flp_type):
    source = [5, 6, 2, -4]
    seed = 2
    expected = -480

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y)


def test_MultipleElementsAndSeedRunOnce(flp_type):
    source = [5, 6, 2, -4]
    seed = 2
    expected = -480

    for source in create_sources(flp_type)(source):
        assert expected == flp.it(_run_once(source)).aggregate(seed, lambda x, y: x * y)


def test_NoElementsSeedResultSeletor(flp_type):
    source = []
    seed = 2
    expected = 7

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y, lambda x: x + 5.0)


def test_SingleElementSeedResultSelector(flp_type):
    source = [5]
    seed = 2
    expected = 15

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y, lambda x: x + 5.0)


def test_TwoElementsSeedResultSelector(flp_type):
    source = [5, 6]
    seed = 2
    expected = 65

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y, lambda x: x + 5.0)


def test_MultipleElementsSeedResultSelector(flp_type):
    source = [5, 6, 2, -4]
    seed = 2
    expected = -475

    for source in create_sources(flp_type)(source):
        assert expected == source.aggregate(seed, lambda x, y: x * y, lambda x: x + 5.0)


def test_MultipleElementsSeedResultSelectorRunOnce(flp_type):
    source = [5, 6, 2, -4]
    seed = 2
    expected = -475

    for source in create_sources(flp_type)(source):
        assert expected == flp.it(_run_once(source)).aggregate(seed, lambda x, y: x * y, lambda x: x + 5.0)


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before aggregate() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).aggregate(lambda x, y: x + y)

    with pytest.raises(SourceNoneError):
        flp_type(None).aggregate(0, lambda x, y: x + y)

    with pytest.raises(SourceNoneError):
        flp_type(None).aggregate(0, lambda x, y: x + y, lambda i: i)


def test_NullFunc(flp_type):
    func = None

    with pytest.raises(FuncNoneError):
        flp_type(range(0, 3)).aggregate(func)

    with pytest.raises(FuncNoneError):
        flp_type(range(0, 3)).aggregate(0, func)

    with pytest.raises(FuncNoneError):
        flp_type(range(0, 3)).aggregate(0, func, lambda i: i)


def test_NullResultSelector(flp_type):
    result_selector = None

    with pytest.raises(ResultSelectorNoneError):
        flp_type(range(0, 3)).aggregate(0, lambda x, y: x + y, result_selector)
