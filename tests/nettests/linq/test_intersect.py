"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq IntersectTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/IntersectTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.
The IntersectBy_* tests live in IntersectTests.cs upstream (there is no IntersectByTests.cs).

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
.NET's int? is mapped to int | None.
.NET's EqualityComparer<string>.Default is Python's default equality/hash, so the test cases
that only pass the default comparer run against the comparer-less API.

Not implemented (skipped with a reason, as elsewhere in nettests):
    * Intersect(second, IEqualityComparer): intersect() has no comparer overload yet. The
      skipped bodies assume intersect(second, comparer) with a comparer object offering
      equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
    * IntersectBy (all overloads): intersect_by() is not implemented yet. The skipped bodies
      assume intersect_by(second, key_selector) and intersect_by(second, key_selector, comparer).
"""

from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    SecondNoneError,
    SelectorNoneError,
    SourceNoneError,
)

_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")
_SKIP_INTERSECT_BY = pytest.mark.skip("intersect_by not implemented yet")


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


class _Comparer:
    """IEqualityComparer<T>-like helper for the skipped comparer tests."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


# EqualityComparer<string>.Default
_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))

# StringComparer.OrdinalIgnoreCase
_ORDINAL_IGNORE_CASE = _Comparer(
    lambda x, y: (x == y) if x is None or y is None else x.lower() == y.lower(),
    lambda x: 0 if x is None else hash(x.lower()),
)


def _anagram_equals(x, y):
    if x is None or y is None:
        return x == y
    return sorted(x) == sorted(y)


def _anagram_hash(obj):
    if obj is None:
        return 0
    result = len(obj)
    for c in obj:
        result ^= ord(c)
    return result


_ANAGRAM_COMPARER = _Comparer(_anagram_equals, _anagram_hash)

_MISSING = object()


def _is_enumerator_that_enumerates(iterator):
    """.NET: `iterator as IEnumerator<int>` followed by MoveNext()."""
    if not isinstance(iterator, Iterator):
        return False
    return next(iterator, _MISSING) is not _MISSING


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q1 = flp_type([2, 3, None, 2, None, 4, 5]).select(lambda x: x)
    q2 = flp_type([1, 9, None, 4]).select(lambda x: x)

    assert list(q1.intersect(q2)) == list(q1.intersect(q2))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q1 = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"]).select(lambda x: x)
    q2 = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS"]).select(lambda x: x)

    assert list(q1.intersect(q2)) == list(q1.intersect(q2))


_INT_TEST_DATA = [
    pytest.param([], [], [], id="empty_empty"),
    pytest.param([-5, 3, -2, 6, 9], [0, 5, 2, 10, 20], [], id="disjoint"),
    pytest.param([1, 2, 2, 3, 4, 3, 5], [1, 4, 4, 2, 2, 2], [1, 2, 4], id="duplicates_collapse_in_first_order"),
    pytest.param([1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1], id="all_equal"),
]


@pytest.mark.parametrize("first, second, expected", _INT_TEST_DATA)
def test_Int(flp_type, first, second, expected):
    # The .NET theory also calls Intersect(second, null); the comparer overload with a
    # null comparer is equivalent to the comparer-less call exercised here.
    assert expected == list(flp_type(first).intersect(second))


_STRING_TEST_DATA = [
    # EqualityComparer<string>.Default rows: default comparer == Python's default equality.
    pytest.param([None], [], [], None, id="single_null_empty_second_default_comparer"),
    pytest.param([None, None, ""], [None], [None], None, id="null_collapse_default_comparer"),
    pytest.param([None, None], [], [], None, id="duplicate_nulls_empty_second_default_comparer"),
    pytest.param(
        ["Tim", "Bob", "Mike", "Robert"],
        ["ekiM", "bBo"],
        [],
        None,
        id="null_comparer",
    ),
    pytest.param(
        ["Tim", "Bob", "Mike", "Robert"],
        ["ekiM", "bBo"],
        ["Bob", "Mike"],
        _ANAGRAM_COMPARER,
        id="anagram_comparer",
        marks=_SKIP_COMPARER,
    ),
]


@pytest.mark.parametrize("first, second, expected, comparer", _STRING_TEST_DATA)
def test_String(flp_type, first, second, expected, comparer):
    if comparer is None:
        result = flp_type(first).intersect(second)
    else:
        result = flp_type(first).intersect(second, comparer)

    assert expected == list(result)


_NULLABLE_INT_TEST_DATA = [
    pytest.param([], [-5, 0, None, 1, 2, 9, 2], [], id="empty_first"),
    pytest.param([-5, 0, 1, 2, None, 9, 2], [], [], id="empty_second"),
    pytest.param([1, 2, None, 3, 4, 5, 6], [6, 7, 7, 7, None, 8, 1], [1, None, 6], id="null_intersects"),
]


@pytest.mark.parametrize("first, second, expected", _NULLABLE_INT_TEST_DATA)
def test_NullableInt(flp_type, first, second, expected):
    assert expected == list(flp_type(first).intersect(second))


@pytest.mark.parametrize("first, second, expected", _NULLABLE_INT_TEST_DATA)
def test_NullableIntRunOnce(flp_type, first, second, expected):
    assert expected == list(flp_type(_run_once(first)).intersect(_run_once(second)))


def test_FirstNull_ThrowsArgumentNullException(flp_type):
    second = ["ekiM", "bBo"]

    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before intersect() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).intersect(second)


@_SKIP_COMPARER
def test_FirstNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    second = ["ekiM", "bBo"]

    with pytest.raises(SourceNoneError):
        flp_type(None).intersect(second, _ANAGRAM_COMPARER)


def test_SecondNull_ThrowsArgumentNullException(flp_type):
    first = ["Tim", "Bob", "Mike", "Robert"]

    with pytest.raises(SecondNoneError):
        flp_type(first).intersect(None)


@_SKIP_COMPARER
def test_SecondNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Tim", "Bob", "Mike", "Robert"]

    with pytest.raises(SecondNoneError):
        flp_type(first).intersect(None, _ANAGRAM_COMPARER)


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).intersect(range(0, 3))

    assert not _is_enumerator_that_enumerates(iterator)


def test_HashSetWithBuiltInComparer_HashSetContainsNotUsed():
    # Python sets have no per-instance comparer; "a" and "A" are always distinct.
    input1 = {"a"}
    input2 = ["A"]

    assert [] == list(flp.it(input1).intersect(input2))
    assert [] == list(flp.it(input2).intersect(input1))


@_SKIP_COMPARER
def test_HashSetWithBuiltInComparer_CustomComparers():
    input1 = {"a"}
    input2 = ["A"]

    assert [] == list(flp.it(input1).intersect(input2, _DEFAULT_COMPARER))
    assert ["a"] == list(flp.it(input1).intersect(input2, _ORDINAL_IGNORE_CASE))

    assert [] == list(flp.it(input2).intersect(input1, _DEFAULT_COMPARER))
    assert ["A"] == list(flp.it(input2).intersect(input1, _ORDINAL_IGNORE_CASE))


@_SKIP_INTERSECT_BY
def test_IntersectBy_FirstNull_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).intersect_by(second, lambda x: x)


@_SKIP_INTERSECT_BY
def test_IntersectBy_FirstNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).intersect_by(second, lambda x: x, _ANAGRAM_COMPARER)


@_SKIP_INTERSECT_BY
def test_IntersectBy_SecondNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).intersect_by(None, lambda x: x)


@_SKIP_INTERSECT_BY
def test_IntersectBy_SecondNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).intersect_by(None, lambda x: x, _ANAGRAM_COMPARER)


@_SKIP_INTERSECT_BY
def test_IntersectBy_KeySelectorNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).intersect_by(second, key_selector)


@_SKIP_INTERSECT_BY
def test_IntersectBy_KeySelectorNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).intersect_by(second, key_selector, _ANAGRAM_COMPARER)


_INTERSECT_BY_TEST_DATA = [
    pytest.param(list(range(0, 10)), list(range(0, 5)), lambda x: x, None, list(range(0, 5)), id="range"),
    pytest.param(list(range(0, 10)), list(range(10, 20)), lambda x: x, None, [], id="range_disjoint"),
    pytest.param([5] * 20, [], lambda x: x, None, [], id="repeat_empty_second"),
    pytest.param([5] * 20, [5] * 3, lambda x: x, None, [5], id="repeat_collapses"),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        None,
        [],
        id="strings_default_comparer",
    ),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        _ANAGRAM_COMPARER,
        ["Bob", "Chris"],
        id="strings_anagram_comparer",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        [15, 20, 40],
        lambda x: x[1],
        None,
        [("Tom", 20), ("Harry", 40)],
        id="tuples_by_age",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        ["moT"],
        lambda x: x[0],
        None,
        [],
        id="tuples_by_name_default_comparer",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        ["moT"],
        lambda x: x[0],
        _ANAGRAM_COMPARER,
        [("Tom", 20)],
        id="tuples_by_name_anagram_comparer",
    ),
]


@_SKIP_INTERSECT_BY
@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _INTERSECT_BY_TEST_DATA)
def test_IntersectBy_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(first).intersect_by(second, key_selector)
    else:
        result = flp_type(first).intersect_by(second, key_selector, comparer)

    assert expected == list(result)


@_SKIP_INTERSECT_BY
@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _INTERSECT_BY_TEST_DATA)
def test_IntersectBy_RunOnce_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(_run_once(first)).intersect_by(_run_once(second), key_selector)
    else:
        result = flp_type(_run_once(first)).intersect_by(_run_once(second), key_selector, comparer)

    assert expected == list(result)


# ---------------------------------------------------------------------------
# FlpIt-specific execution invariants (no .NET counterpart)
# ---------------------------------------------------------------------------

def test_Intersect_IsDeferred_DoesNotConsumeSources():
    first = _run_once([1, 2, 3])
    second = _run_once([2])

    query = flp.it(first).intersect(second)

    # Building the query consumed nothing; both generators are still untouched.
    assert [1, 2, 3] == list(first)
    assert [2] == list(second)
    assert [] == list(query)  # both exhausted by the assertions above (one-shot semantics)


def test_Intersect_SecondIsFullyEnumeratedBeforeFirst():
    log = []

    def first():
        for x in [1, 2, 3]:
            log.append(("first", x))
            yield x

    def second():
        for x in [3, 1]:
            log.append(("second", x))
            yield x

    assert [1, 3] == list(flp.it(first()).intersect(second()))
    assert log == [
        ("second", 3), ("second", 1),
        ("first", 1), ("first", 2), ("first", 3),
    ]


def test_Intersect_StreamsFirstAndStopsEarly():
    consumed = []

    def first():
        for x in [1, 2, 3, 4]:
            consumed.append(x)
            yield x

    iterator = iter(flp.it(first()).intersect([1, 2]))

    assert next(iterator) == 1
    assert consumed == [1]


def test_Intersect_ReEnumeratesReiterableSources():
    query = flp.it([1, 2, 2, 3]).intersect([2, 3, 3])

    assert [2, 3] == list(query)
    assert [2, 3] == list(query)
