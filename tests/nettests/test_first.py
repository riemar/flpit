"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq FirstTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/FirstTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

The .NET tests distinguish IList and non-IList sources and use generic type
instantiations. In Python, those distinctions are represented by flp.lst and
flp.it respectively; Python's runtime does not require separate copies for
each generic type argument.

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
"""

import pytest

from flpit import (
    flp,
    FlpIt,
    FlpList,
    EmptySequenceError,
    NoMatchError,
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
    # .NET: where x > int.MinValue
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)

    assert q.first() == q.first()


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: bool(x))

    assert q.first() == q.first()


def test_EmptyIListT():
    source = flp.lst([])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True

    with pytest.raises(EmptySequenceError):
        flp.it(_run_once(source)).first()


def test_IListTOneElement():
    source = flp.lst([5])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.first() == 5


def test_IListTManyElementsFirstIsDefault():
    source = flp.lst([None, -10, 2, 4, 3, 0, 2])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.first() is None


def test_IListTManyElementsFirstIsNotDefault():
    source = flp.lst([19, None, -10, 2, 4, 3, 0, 2])
    assert isinstance(source, FlpIt) == False
    assert isinstance(source, FlpList) == True
    assert source.first() == 19


def test_EmptyNotIListT():
    def empty_source():
        return
        yield

    source = flp.it(empty_source())
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False

    with pytest.raises(EmptySequenceError):
        flp.it(_run_once(source)).first()


def test_OneElementNotIListT():
    source = flp.it(range(-5, -4))
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False
    assert source.first() == -5


def test_ManyElementsNotIListT():
    source = flp.it(range(3, 13))
    assert isinstance(source, FlpIt) == True
    assert isinstance(source, FlpList) == False
    assert source.first() == 3


def test_EmptySource(flp_type):
    source = flp_type([])

    with pytest.raises(NoMatchError):
        source.first(lambda x: True)

    with pytest.raises(NoMatchError):
        source.first(lambda x: False)


def test_OneElementTruePredicate(flp_type):
    source = flp_type([4])

    assert source.first(_is_even) == 4


def test_ManyElementsPredicateFalseForAll(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21])

    with pytest.raises(NoMatchError):
        source.first(_is_even)


def test_PredicateTrueOnlyForLast(flp_type):
    source = flp_type([9, 5, 1, 3, 17, 21, 50])

    assert source.first(_is_even) == 50


def test_PredicateTrueForSome(flp_type):
    source = flp_type([3, 7, 10, 7, 9, 2, 11, 17, 13, 8])

    assert source.first(_is_even) == 10


def test_PredicateTrueForSomeRunOnce(flp_type):
    source = [3, 7, 10, 7, 9, 2, 11, 17, 13, 8]

    # .NET RunOnce() -> one-shot generator. first() must stop at the first match
    # and must not enumerate the source a second time.
    query = flp_type(_run_once(source))

    assert query.first(_is_even) == 10


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError.
    with pytest.raises(SourceNoneError):
        flp_type(None).first()


def test_NullSourcePredicateUsed(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).first(lambda i: i != 2)


def test_NullPredicate(flp_type):
    with pytest.raises(PredicateNoneError):
        flp_type(range(3)).first(None)