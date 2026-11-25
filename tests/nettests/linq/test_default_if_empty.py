"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq DefaultIfEmptyTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/DefaultIfEmptyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`).

.NET overloads covered by DefaultIfEmptyTests:
    DefaultIfEmpty(source, defaultValue) -> source.default_if_empty(default)
    DefaultIfEmpty(source)               -> not provided: Python has no default(T), so the default value is
                                            mandatory. Tests that mix both overloads are parametrized by
                                            `overload` ("default_value", "parameterless"); the parameterless
                                            case keeps its ported body and is skipped, so the working overload
                                            stays covered. Tests that only use the parameterless overload are
                                            skipped as a whole.
    (.NET has no comparer overload for DefaultIfEmpty, so there is nothing to skip here.)

.NET helper / language mapping:
    int[] / int?[] / string[]            -> list (wrapped with flp_type -> FlpIt and FlpList)
    Enumerable.Empty<int>()              -> flp_type(()) (an empty, re-enumerable source)
    NumberRangeGuaranteedNotCollectionType(a, n) -> flp.it(_ForceNotCollection(range(a, a + n)))
    Enumerable.Range(1, 3)               -> range(1, 4)
    RunOnce()                            -> conftest ``run_once`` fixture (fails on a 2nd enumeration).
    Assert.Equal(result, result)         -> list(result) == list(result): the query is enumerated twice.
    Assert.Equal(expected, actual)       -> list(actual) == expected
    ToArray() / ToList()                 -> to_list(): there is no array type.
    IEnumerator<int>.MoveNext()          -> _move_next(): next() returning True, StopIteration -> False.
    ArgumentOutOfRangeException          -> ArgumentOutOfRangeError
    AssertExtensions.Throws<ArgumentNullException>("source", ...) -> pytest.raises(SourceNoneError):
                                            the FlpIt/FlpList constructor rejects None before
                                            default_if_empty() can be called.
    ElementAtOrDefault(index)            -> not implemented yet (skipped); the port assumes
                                            element_at_or_default(index, default) with the mandatory default
                                            passed as .NET's default(T): 0 for int, None for string.
"""
from collections.abc import Iterator

import pytest

from flpit import ArgumentOutOfRangeError, SourceNoneError, flp

INT_MIN = -2147483648

_SKIP_PARAMETERLESS = pytest.mark.skip("parameterless overload not provided: Python has no default(T)")

_OVERLOADS = [
    "default_value",
    pytest.param("parameterless", marks=_SKIP_PARAMETERLESS),
]


class _ForceNotCollection:
    """Re-iterable source without __len__ / __getitem__ (.NET NumberRangeGuaranteedNotCollectionType)."""

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        for item in self._items:
            yield item


def _number_range_guaranteed_not_collection_type(start, count):
    return flp.it(_ForceNotCollection(range(start, start + count)))


def _move_next(enumerator):
    try:
        next(enumerator)
    except StopIteration:
        return False
    return True


def test_SameResultsRepeatCallsNonEmptyQuery(flp_type):
    q = (
        flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345])
        .where(lambda x: x > INT_MIN)
        .select(lambda x: x)
    )

    assert list(q.default_if_empty(5)) == list(q.default_if_empty(5))


def test_SameResultsRepeatCallsEmptyQuery():
    q = _number_range_guaranteed_not_collection_type(0, 0).select(lambda x: x)

    assert list(q.default_if_empty(88)) == list(q.default_if_empty(88))


# (source, default_value, expected); the source is wrapped with flp_type in the tests.
TEST_DATA = [
    pytest.param([], 0, [0], id="empty-0"),
    pytest.param([3], 0, [3], id="one-0"),
    pytest.param([3, -1, 0, 10, 15], 0, [3, -1, 0, 10, 15], id="many-0"),
    pytest.param([], -10, [-10], id="empty-minus10"),
    pytest.param([3], 9, [3], id="one-9"),
    pytest.param([3, -1, 0, 10, 15], 9, [3, -1, 0, 10, 15], id="many-9"),
    pytest.param((), 0, [0], id="Enumerable.Empty-0"),
]


@pytest.mark.parametrize("overload", _OVERLOADS)
@pytest.mark.parametrize("source, default_value, expected", TEST_DATA)
def test_DefaultIfEmpty(flp_type, overload, source, default_value, expected):
    source = flp_type(source)

    if overload == "parameterless":
        if default_value == 0:
            result = source.default_if_empty()
            assert list(result) == list(result)
            assert expected == list(result)
            assert len(expected) == result.count()
            assert expected == list(result.to_list())  # .NET: ToList() and ToArray()
        return

    result = source.default_if_empty(default_value)
    assert list(result) == list(result)
    assert expected == list(result)
    assert len(expected) == result.count()
    assert expected == list(result.to_list())  # .NET: ToList() and ToArray()


@pytest.mark.parametrize("overload", _OVERLOADS)
@pytest.mark.parametrize("source, default_value, expected", TEST_DATA)
def test_DefaultIfEmptyRunOnce(flp_type, run_once, overload, source, default_value, expected):
    if overload == "parameterless":
        if default_value == 0:
            assert expected == list(flp_type(run_once(source)).default_if_empty())
        return

    assert expected == list(flp_type(run_once(source)).default_if_empty(default_value))


@_SKIP_PARAMETERLESS
def test_NullableArray_Empty_WithoutDefaultValue(flp_type):
    source = flp_type([])
    assert [None] == list(source.default_if_empty())


def test_NullableArray_Empty_WithDefaultValue(flp_type):
    source = flp_type([])
    default_value = 9
    assert [default_value] == list(source.default_if_empty(default_value))


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NullSource_ThrowsArgumentNullException(flp_type, overload):
    source = None

    # .NET: ArgumentNullException("source"); flp: the constructor rejects None.
    if overload == "parameterless":
        with pytest.raises(SourceNoneError):
            flp_type(source).default_if_empty()
        return

    with pytest.raises(SourceNoneError):
        flp_type(source).default_if_empty(42)


@_SKIP_PARAMETERLESS
def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = _number_range_guaranteed_not_collection_type(0, 3).default_if_empty()
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    assert not (en is not None and _move_next(en))


def test_First_Last_ElementAt(flp_type):
    non_empty = flp_type(range(1, 4))
    assert 1 == non_empty.first()
    assert 3 == non_empty.last()
    assert 1 == non_empty.element_at(0)
    assert 2 == non_empty.element_at(1)
    assert 3 == non_empty.element_at(2)
    with pytest.raises(ArgumentOutOfRangeError):
        non_empty.element_at(-1)
    with pytest.raises(ArgumentOutOfRangeError):
        non_empty.element_at(4)

    empty = flp_type([])
    assert 42 == empty.default_if_empty(42).first()
    assert 42 == empty.default_if_empty(42).last()
    assert 42 == empty.default_if_empty(42).element_at(0)
    with pytest.raises(ArgumentOutOfRangeError):
        empty.default_if_empty(42).element_at(1)


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: element_at_or_default")
def test_ElementAtOrDefault_OutOfBounds_ReturnsTypeDefault(flp_type):
    # Regression test for https://github.com/dotnet/runtime/issues/119834
    # ElementAtOrDefault should return default(T) for out-of-bounds indices,
    # not the DefaultIfEmpty default value

    # Test with empty source
    empty = flp_type([])
    default_if_empty = empty.default_if_empty(999)

    # Index 0 should return the DefaultIfEmpty value (999)
    assert 999 == default_if_empty.element_at_or_default(0, 0)

    # Out-of-bounds indices should return default(int) which is 0, not 999
    assert 0 == default_if_empty.element_at_or_default(1, 0)
    assert 0 == default_if_empty.element_at_or_default(2, 0)
    assert 0 == default_if_empty.element_at_or_default(-1, 0)

    # Test with different type (string)
    empty_strings = flp_type([])
    default_if_empty_string = empty_strings.default_if_empty("default")

    # Index 0 should return the DefaultIfEmpty value
    assert "default" == default_if_empty_string.element_at_or_default(0, None)

    # Out-of-bounds indices should return default(string) which is null
    assert default_if_empty_string.element_at_or_default(1, None) is None
    assert default_if_empty_string.element_at_or_default(2, None) is None
