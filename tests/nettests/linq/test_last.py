"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq LastTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/LastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

The .NET tests distinguish IList and non-IList sources and use generic type
instantiations. In Python, those distinctions are represented by flp.lst and
flp.it respectively; Python's runtime does not require separate copies for
each generic type argument.
"""

import pytest


from flpit import (
    flp,
    FlpIt,
    FlpList,
    EmptySequenceError,
    NoMatchError,
    MultipleElementsError,
    MultipleMatchesError,
    SourceNoneError,
    PredicateNoneError,
)

from tests.helpers import (
    Bomb,
    Falsy,
    NoIterList,
    broken_iterator,
)


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345])

    assert q.last() == q.last()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""])

    assert q.last() == q.last()


def test_EmptyIListT():
    source = flp.lst([])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    with pytest.raises(EmptySequenceError):
        source.last()


def test_IListTOneElement():
    source = flp.lst([5])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.last() == 5


def test_IListTManyElementsLastIsDefault():
    source = flp.lst([-10, 2, 4, 3, 0, 2, None])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.last() is None


def test_IListTManyElementsLastIsNotDefault():
    source = flp.lst([-10, 2, 4, 3, 0, 2, None, 19])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.last() == 19


def test_EmptyNotIListT():
    source = flp.it([])
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False
    with pytest.raises(EmptySequenceError):
        source.last()


def test_OneElementNotIListT():
    source = flp.it([-5])
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False
    assert source.last() == -5


def test_ManyElementsNotIListT():
    source = flp.it(range(3, 13))
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False
    assert source.last() == 12


def test_EmptySourcePredicate(flp_type):
    source = flp_type([])

    with pytest.raises(NoMatchError):
        source.last(lambda x: True)

    with pytest.raises(NoMatchError):
        source.last(lambda x: False)


def test_OneElementTruePredicate(flp_type):
    source = flp_type([4])

    assert source.last(lambda x: x % 2 == 0) == 4


def test_ManyElementsPredicateFalseForAll(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21])

    with pytest.raises(NoMatchError):
        source.last(lambda x: x % 2 == 0)


def test_PredicateTrueOnlyForLast(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21, 50])

    assert source.last(lambda x: x % 2 == 0) == 50


def test_PredicateTrueForSome(flp_type):
    source = flp_type([3, 7, 10, 7, 9, 2, 11, 18, 13, 9])

    assert source.last(lambda x: x % 2 == 0) == 18


def test_PredicateTrueForSomeRunOnce(flp_type):
    source = [3, 7, 10, 7, 9, 2, 11, 18, 13, 9]
    query = flp.it(iter(source))

    assert query.last(lambda x: x % 2 == 0) == 18


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is a TypeError.
    with pytest.raises(SourceNoneError):
        flp_type(None).last()


def test_NullSourcePredicateUsed(flp_type):
    # Python has no separate null-source + null-predicate overload contract;
    # both invalid call shapes are represented by TypeError.
    with pytest.raises(SourceNoneError):
        flp_type(None).last(lambda i: i != 2)


def test_NullPredicate(flp_type):
    with pytest.raises(PredicateNoneError):
        flp_type(range(3)).last(None)
