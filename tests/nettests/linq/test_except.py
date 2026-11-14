"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ExceptTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ExceptTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.
The ExceptBy_* tests live in ExceptTests.cs upstream (there is no ExceptByTests.cs),
so except_ and except_by are both covered here.

`except` is a reserved word in Python, so Except / ExceptBy map to except_ / except_by.

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
.NET's int? is mapped to int | None.
.NET's EqualityComparer<string>.Default is Python's default equality/hash, so the test cases
that only pass the default comparer run against the comparer-less API.

Not implemented (skipped with a reason, as elsewhere in nettests):
    * Except(second, IEqualityComparer) and ExceptBy(second, keySelector, IEqualityComparer):
      except_() / except_by() have no comparer overload yet. The skipped bodies assume
      except_(second, comparer) and except_by(second, key_selector, comparer), with a comparer
      object offering equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
"""

from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    SelectorNoneError,
    SecondNoneError,
    SourceNoneError,
)

_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")


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

    assert list(q1.except_(q2)) == list(q1.except_(q2))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q1 = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"]).select(lambda x: x)
    q2 = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS"]).select(lambda x: x)

    assert list(q1.except_(q2)) == list(q1.except_(q2))


_INT_TEST_DATA = [
    pytest.param([], [], [], id="empty_empty"),
    pytest.param([], [-6, -8, -6, 2, 0, 0, 5, 6], [], id="empty_first"),
    pytest.param([1, 1, 1, 1, 1], [2, 3, 4], [1], id="duplicates_collapse"),
]


@pytest.mark.parametrize("first, second, expected", _INT_TEST_DATA)
def test_Int(flp_type, first, second, expected):
    # The .NET theory passes a null comparer for every row; the comparer overload is
    # therefore equivalent to the comparer-less call exercised here.
    assert expected == list(flp_type(first).except_(second))


_STRING_TEST_DATA = [
    # EqualityComparer<string>.Default rows: default comparer == Python's default equality.
    pytest.param([None], [], [None], None, id="single_null_default_comparer"),
    pytest.param([None, None, ""], [None], [""], None, id="null_collapse_default_comparer"),
    pytest.param([None, None], [], [None], None, id="duplicate_nulls_default_comparer"),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        ["Bob", "Tim", "Robert", "Chris"],
        None,
        id="null_comparer",
    ),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        ["Tim", "Robert"],
        _ANAGRAM_COMPARER,
        id="anagram_comparer",
        marks=_SKIP_COMPARER,
    ),
]


@pytest.mark.parametrize("first, second, expected, comparer", _STRING_TEST_DATA)
def test_String(flp_type, first, second, expected, comparer):
    if comparer is None:
        result = flp_type(first).except_(second)
    else:
        result = flp_type(first).except_(second, comparer)

    assert expected == list(result)


_NULLABLE_INT_TEST_DATA = [
    pytest.param(
        [-6, -8, -6, 2, 0, 0, 5, 6, None, None],
        [],
        [-6, -8, 2, 0, 5, 6, None],
        id="empty_second",
    ),
    pytest.param(
        [1, 2, 2, 3, 4, 5],
        [5, 3, 2, 6, 6, 3, 1, None, None],
        [4],
        id="mostly_excluded",
    ),
    pytest.param(
        [2, 3, None, 2, None, 4, 5],
        [1, 9, None, 4],
        [2, 3, 5],
        id="null_excluded",
    ),
]


@pytest.mark.parametrize("first, second, expected", _NULLABLE_INT_TEST_DATA)
def test_NullableInt(flp_type, first, second, expected):
    assert expected == list(flp_type(first).except_(second))


@pytest.mark.parametrize("first, second, expected", _NULLABLE_INT_TEST_DATA)
def test_NullableIntRunOnce(flp_type, first, second, expected):
    assert expected == list(flp_type(_run_once(first)).except_(_run_once(second)))


def test_FirstNull_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before except_() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).except_(second)


@_SKIP_COMPARER
def test_FirstNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).except_(second, _ANAGRAM_COMPARER)


def test_SecondNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).except_(None)


@_SKIP_COMPARER
def test_SecondNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).except_(None, _ANAGRAM_COMPARER)


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).except_(range(0, 3))

    assert not _is_enumerator_that_enumerates(iterator)


def test_HashSetWithBuiltInComparer_HashSetContainsNotUsed():
    # Python sets have no per-instance comparer; "a" and "A" are always distinct.
    input1 = {"a"}
    input2 = ["A"]

    assert ["a"] == list(flp.it(input1).except_(input2))
    assert ["A"] == list(flp.it(input2).except_(input1))


@_SKIP_COMPARER
def test_HashSetWithBuiltInComparer_CustomComparers():
    input1 = {"a"}
    input2 = ["A"]

    assert ["a"] == list(flp.it(input1).except_(input2, _DEFAULT_COMPARER))
    assert [] == list(flp.it(input1).except_(input2, _ORDINAL_IGNORE_CASE))

    assert ["A"] == list(flp.it(input2).except_(input1, _DEFAULT_COMPARER))
    assert [] == list(flp.it(input2).except_(input1, _ORDINAL_IGNORE_CASE))


def test_ExceptBy_FirstNull_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    # See test_FirstNull_ThrowsArgumentNullException: the constructor raises first.
    with pytest.raises(SourceNoneError):
        flp_type(None).except_by(second, lambda x: x)


@_SKIP_COMPARER
def test_ExceptBy_FirstNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).except_by(second, lambda x: x, _ANAGRAM_COMPARER)


def test_ExceptBy_SecondNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).except_by(None, lambda x: x)


@_SKIP_COMPARER
def test_ExceptBy_SecondNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).except_by(None, lambda x: x, _ANAGRAM_COMPARER)


def test_ExceptBy_KeySelectorNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).except_by(second, key_selector)


@_SKIP_COMPARER
def test_ExceptBy_KeySelectorNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).except_by(second, key_selector, _ANAGRAM_COMPARER)


_EXCEPT_BY_TEST_DATA = [
    pytest.param(list(range(0, 10)), list(range(0, 5)), lambda x: x, None, list(range(5, 10)), id="range"),
    pytest.param([5] * 20, [], lambda x: x, None, [5], id="repeat_empty_second"),
    pytest.param([5] * 20, [5] * 3, lambda x: x, None, [], id="repeat_all_excluded"),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        None,
        ["Bob", "Tim", "Robert", "Chris"],
        id="strings_default_comparer",
    ),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        _ANAGRAM_COMPARER,
        ["Tim", "Robert"],
        id="strings_anagram_comparer",
        marks=_SKIP_COMPARER,
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        [15, 20, 40],
        lambda x: x[1],
        None,
        [("Dick", 30)],
        id="tuples_by_age",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        ["moT"],
        lambda x: x[0],
        None,
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        id="tuples_by_name_default_comparer",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        ["moT"],
        lambda x: x[0],
        _ANAGRAM_COMPARER,
        [("Dick", 30), ("Harry", 40)],
        id="tuples_by_name_anagram_comparer",
        marks=_SKIP_COMPARER,
    ),
]


@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _EXCEPT_BY_TEST_DATA)
def test_ExceptBy_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(first).except_by(second, key_selector)
    else:
        result = flp_type(first).except_by(second, key_selector, comparer)

    assert expected == list(result)


@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _EXCEPT_BY_TEST_DATA)
def test_ExceptBy_RunOnce_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(_run_once(first)).except_by(_run_once(second), key_selector)
    else:
        result = flp_type(_run_once(first)).except_by(_run_once(second), key_selector, comparer)

    assert expected == list(result)


# ---------------------------------------------------------------------------
# FlpIt-specific execution invariants (no .NET counterpart)
# ---------------------------------------------------------------------------

def test_Except_IsDeferred_DoesNotConsumeSources():
    first = _run_once([1, 2, 3])
    second = _run_once([2])

    query = flp.it(first).except_(second)

    # Building the query consumed nothing; both generators are still untouched.
    assert [1, 2, 3] == list(first)
    assert [2] == list(second)
    assert [] == list(query)  # both exhausted by the assertions above (one-shot semantics)


def test_ExceptBy_KeySelectorRunsLazily():
    calls = []

    def key_selector(x):
        calls.append(x)
        return x

    query = flp.it([1, 2, 3]).except_by([2], key_selector)
    assert calls == []

    assert [1, 3] == list(query)
    assert calls == [1, 2, 3]
