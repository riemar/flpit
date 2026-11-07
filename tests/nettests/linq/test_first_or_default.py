"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq FirstOrDefaultTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/FirstOrDefaultTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

The .NET tests distinguish IList and non-IList sources and use generic type
instantiations. In Python, those distinctions are represented by flp.lst and
flp.it respectively; Python's runtime does not require separate copies for
each generic type argument.

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).

API difference that affects this port:
  * .NET FirstOrDefault() / FirstOrDefault(predicate) fall back to default(T).
    Python has no way to derive a correct default for a type, so flp's
    first_or_default(default, predicate=None) takes a MANDATORY `default` as its
    first argument (the argument order is (default, predicate), the reverse of
    .NET's (predicate, defaultValue)).
  * The .NET overloads without a default are ported by passing .NET's default(T)
    explicitly: 0 for int, None for int? / string / reference types.
"""

from datetime import datetime

import pytest

from flpit import (
    flp,
    FlpIt,
    FlpList,
    SourceNoneError,
    PredicateNoneError,
)


def _is_even(x):
    return x % 2 == 0


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type(range(0, 0)).select(lambda x: x)

    assert q.first_or_default(0) == q.first_or_default(0)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: bool(x))

    assert q.first_or_default(None) == q.first_or_default(None)


@pytest.mark.parametrize(
    "default_of_t",
    [0, None, datetime.min, None],
    ids=["int", "string", "DateTime", "class"],
)
def test_EmptyIListT(default_of_t):
    source = flp.lst([])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert flp.it(_run_once(source)).first_or_default(default_of_t) == default_of_t


@pytest.mark.parametrize("default_value", [5, "Hello", datetime(1970, 1, 1)])
def test_EmptyIListDefault(default_value):
    source = flp.lst([])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert flp.it(_run_once(source)).first_or_default(default_value) == default_value


def test_IListTOneElement():
    source = flp.lst([5])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert source.first_or_default(0) == 5


def test_IListOneElementDefault():
    source = flp.lst([5])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert source.first_or_default(3) == 5


def test_IListTManyElementsFirstIsDefault():
    source = flp.lst([None, -10, 2, 4, 3, 0, 2])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert source.first_or_default(None) is None


def test_IListTManyElementsFirstIsNotDefault():
    source = flp.lst([19, None, -10, 2, 4, 3, 0, 2])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    assert source.first_or_default(None) == 19


@pytest.mark.parametrize(
    "default_of_t",
    [0, None, datetime.min, None],
    ids=["int", "string", "DateTime", "class"],
)
def test_EmptyNotIListT(default_of_t):
    def empty_source():
        return
        yield

    source = flp.it(empty_source())
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False

    assert flp.it(_run_once(source)).first_or_default(default_of_t) == default_of_t


@pytest.mark.parametrize("default_value", [5, "Hello", datetime(1970, 1, 1)])
def test_EmptyNotIListDefault(default_value):
    def empty_source():
        return
        yield

    source = flp.it(empty_source())
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False

    assert flp.it(_run_once(source)).first_or_default(default_value) == default_value


def test_OneElementNotIListT():
    source = flp.it(range(-5, -4))
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False

    assert source.first_or_default(0) == -5


def test_ManyElementsNotIListT():
    source = flp.it(range(3, 13))
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False

    assert source.first_or_default(0) == 3


def test_EmptySource(flp_type):
    source = flp_type([])

    assert source.first_or_default(None, lambda x: True) is None
    assert source.first_or_default(None, lambda x: False) is None


def test_OneElementTruePredicate(flp_type):
    source = flp_type([4])

    assert source.first_or_default(0, _is_even) == 4


def test_OneElementTruePredicateDefault(flp_type):
    source = flp_type([4])

    # .NET: FirstOrDefault(predicate, 5) -> Python order is (default, predicate).
    assert source.first_or_default(5, _is_even) == 4


def test_ManyElementsPredicateFalseForAll(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21])

    assert source.first_or_default(0, _is_even) == 0


def test_ManyElementsPredicateFalseForAllDefault(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21])

    assert source.first_or_default(5, _is_even) == 5


def test_PredicateTrueOnlyForLast(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21, 50])

    assert source.first_or_default(0, _is_even) == 50


def test_PredicateTrueOnlyForLastDefault(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21, 50])

    assert source.first_or_default(5, _is_even) == 50


def test_PredicateTrueForSome(flp_type):
    source = flp_type([3, 7, 10, 7, 9, 2, 11, 17, 13, 8])

    assert source.first_or_default(0, _is_even) == 10


def test_PredicateTrueForSomeDefault(flp_type):
    source = flp_type([3, 7, 10, 7, 9, 2, 11, 17, 13, 8])

    assert source.first_or_default(5, _is_even) == 10


def test_PredicateTrueForSomeRunOnce(flp_type):
    source = [3, 7, 10, 7, 9, 2, 11, 17, 13, 8]

    # .NET RunOnce() -> one-shot generator.
    query = flp_type(_run_once(source))

    assert query.first_or_default(0, _is_even) == 10


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError.
    with pytest.raises(SourceNoneError):
        flp_type(None).first_or_default(0)

    with pytest.raises(SourceNoneError):
        flp_type(None).first_or_default(5)


def test_NullSourcePredicateUsed(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).first_or_default(0, lambda i: i != 2)

    with pytest.raises(SourceNoneError):
        flp_type(None).first_or_default(5, lambda i: i != 2)


def test_NullPredicate(flp_type):
    with pytest.raises(PredicateNoneError):
        flp_type(range(3)).first_or_default(0, None)

    with pytest.raises(PredicateNoneError):
        flp_type(range(3)).first_or_default(5, None)