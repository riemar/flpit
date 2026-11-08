"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq DistinctTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/DistinctTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.
The DistinctBy_* tests live in DistinctTests.cs upstream (there is no DistinctByTests.cs),
so distinct and distinct_by are both covered here.

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
.NET's decimal/long/float/double element types are mapped to Decimal/int/float.

Not implemented (skipped with a reason, as elsewhere in nettests):
    * Distinct(IEqualityComparer) and DistinctBy(keySelector, IEqualityComparer):
      distinct() / distinct_by() have no comparer overload yet. The skipped bodies assume
      distinct(comparer) and distinct_by(key_selector, comparer), with a comparer object
      offering equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
"""

from decimal import Decimal
from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    SelectorNoneError,
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


# EqualityComparer<string>.Default / StringComparer.Ordinal
_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))
_ORDINAL = _DEFAULT_COMPARER
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
    q = flp_type([0, 9999, 0, 888, -1, 66, -1, -777, 1, 2, -12345, 66, 66, -1, -1]).where(
        lambda x: x > -2147483648
    )

    assert list(q.distinct()) == list(q.distinct())


def test_SameResultsRepeatCallsStringQuery(flp_type):
    # Faithful to the original: the predicate is string.IsNullOrEmpty, so the query is empty.
    q = flp_type(["!@#$%^", "C", "AAA", "Calling Twice", "SoS"]).where(
        lambda x: x is None or x == ""
    )

    assert list(q.distinct()) == list(q.distinct())


def test_EmptySource(flp_type):
    source = []

    assert list(flp_type(source).distinct()) == []


def test_EmptySourceRunOnce(flp_type):
    source = []

    assert list(flp.it(_run_once(source)).distinct()) == []


@_SKIP_COMPARER
def test_SingleNullElementExplicitlyUseDefaultComparer(flp_type):
    source = [None]
    expected = [None]

    assert expected == list(flp_type(source).distinct(_DEFAULT_COMPARER))


@_SKIP_COMPARER
def test_EmptyStringDistinctFromNull(flp_type):
    source = [None, None, ""]
    expected = [None, ""]

    assert expected == list(flp_type(source).distinct(_DEFAULT_COMPARER))


@_SKIP_COMPARER
def test_CollapsDuplicateNulls(flp_type):
    source = [None, None]
    expected = [None]

    assert expected == list(flp_type(source).distinct(_DEFAULT_COMPARER))


def test_SourceAllDuplicates(flp_type):
    source = [5, 5, 5, 5, 5, 5]
    expected = [5]

    assert expected == list(flp_type(source).distinct())


def test_AllUnique(flp_type):
    source = [2, -5, 0, 6, 10, 9]

    assert source == list(flp_type(source).distinct())


def test_SomeDuplicatesIncludingNulls(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]
    expected = [1, 2, None]

    assert expected == list(flp_type(source).distinct())


def test_SomeDuplicatesIncludingNullsRunOnce(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]
    expected = [1, 2, None]

    assert expected == list(flp.it(_run_once(source)).distinct())


def test_LastSameAsFirst(flp_type):
    source = [1, 2, 3, 4, 5, 1]
    expected = [1, 2, 3, 4, 5]

    assert expected == list(flp_type(source).distinct())


# Multiple elements repeat non-consecutively
def test_RepeatsNonConsecutive(flp_type):
    source = [1, 1, 2, 2, 4, 3, 1, 3, 2]
    expected = [1, 2, 4, 3]

    assert expected == list(flp_type(source).distinct())


def test_RepeatsNonConsecutiveRunOnce(flp_type):
    source = [1, 1, 2, 2, 4, 3, 1, 3, 2]
    expected = [1, 2, 4, 3]

    assert expected == list(flp.it(_run_once(source)).distinct())


def test_NullComparer(flp_type):
    source = ["Bob", "Tim", "bBo", "miT", "Robert", "iTm"]
    expected = ["Bob", "Tim", "bBo", "miT", "Robert", "iTm"]

    assert expected == list(flp_type(source).distinct())


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before distinct() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).distinct()


@_SKIP_COMPARER
def test_NullSourceCustomComparer(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).distinct(_ORDINAL)


@_SKIP_COMPARER
def test_CustomEqualityComparer(flp_type):
    source = ["Bob", "Tim", "bBo", "miT", "Robert", "iTm"]
    expected = ["Bob", "Tim", "Robert"]

    assert expected == list(flp_type(source).distinct(_ANAGRAM_COMPARER))


@_SKIP_COMPARER
def test_CustomEqualityComparerRunOnce(flp_type):
    source = ["Bob", "Tim", "bBo", "miT", "Robert", "iTm"]
    expected = ["Bob", "Tim", "Robert"]

    assert expected == list(flp.it(_run_once(source)).distinct(_ANAGRAM_COMPARER))


_SEQUENCES_WITH_DUPLICATES = [
    pytest.param([1, 1, 1, 2, 3, 5, 5, 6, 6, 10], id="int"),
    pytest.param([1, 1, 1, 2, 3, 5, 5, 6, 6, 10], id="long"),
    pytest.param([1.0, 1.0, 1.0, 2.0, 3.0, 5.0, 5.0, 6.0, 6.0, 10.0], id="float"),
    pytest.param([1.0, 1.0, 1.0, 2.0, 3.0, 5.0, 5.0, 6.0, 6.0, 10.0], id="double"),
    pytest.param([Decimal(x) for x in (1, 1, 1, 2, 3, 5, 5, 6, 6, 10)], id="decimal"),
    pytest.param(
        [
            "add",
            "add",
            "subtract",
            "multiply",
            "divide",
            "divide2",
            "subtract",
            "add",
            "power",
            "exponent",
            "hello",
            "class",
            "namespace",
            "namespace",
            "namespace",
        ],
        id="string",
    ),
]


@pytest.mark.parametrize("original", _SEQUENCES_WITH_DUPLICATES)
def test_FindDistinctAndValidate(flp_type, original):
    # Convert to list to avoid repeated enumerations of the enumerables.
    original_list = list(original)
    distinct_list = list(flp_type(original_list).distinct())

    # Ensure the result doesn't contain duplicates.
    hash_set = set()
    for i in distinct_list:
        assert i not in hash_set
        hash_set.add(i)

    original_set = set(original)
    assert hash_set >= original_set  # Superset
    assert hash_set <= original_set  # Subset


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).distinct()

    assert not _is_enumerator_that_enumerates(iterator)


def test_ToArray(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]
    expected = [1, 2, None]

    assert expected == list(flp_type(source).distinct())


def test_ToList(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]
    expected = [1, 2, None]

    assert expected == list(flp_type(source).distinct().to_list())


def test_Count(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]

    assert flp_type(source).distinct().count() == 3


def test_RepeatEnumerating(flp_type):
    source = [1, 1, 1, 2, 2, 2, None, None]
    result = flp_type(source).distinct()

    assert list(result) == list(result)


def test_DistinctBy_SourceNull_ThrowsArgumentNullException(flp_type):
    first = None

    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before distinct_by() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(first).distinct_by(lambda x: x)

    # The comparer overload does not exist yet; this call is never reached
    # because the constructor already raised.
    with pytest.raises(SourceNoneError):
        flp_type(first).distinct_by(lambda x: x, _ANAGRAM_COMPARER)


def test_DistinctBy_KeySelectorNull_ThrowsArgumentNullException(flp_type):
    source = ["Bob", "Tim", "Robert", "Chris"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).distinct_by(key_selector)

    # comparer overload doesn't exist yet. it might ever exist as this isn't actually a thing in Python
    # with pytest.raises(SelectorNoneError):
    #     flp_type(source).distinct_by(key_selector, _ANAGRAM_COMPARER)


_DISTINCT_BY_TEST_DATA = [
    pytest.param([], lambda x: x, None, [], id="empty"),
    pytest.param(list(range(0, 10)), lambda x: x, None, list(range(0, 10)), id="range_0_10"),
    pytest.param(list(range(5, 15)), lambda x: True, None, [5], id="constant_key"),
    pytest.param(list(range(0, 20)), lambda x: x % 5, None, list(range(0, 5)), id="modulo_key"),
    pytest.param([5] * 20, lambda x: x, None, [5], id="repeat"),
    pytest.param(
        ["Bob", "bob", "tim", "Bob", "Tim"],
        lambda x: x,
        None,
        ["Bob", "bob", "tim", "Tim"],
        id="strings_default_comparer",
    ),
    pytest.param(
        ["Bob", "bob", "tim", "Bob", "Tim"],
        lambda x: x,
        _ORDINAL_IGNORE_CASE,
        ["Bob", "tim"],
        id="strings_ignore_case",
        marks=_SKIP_COMPARER,
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        lambda x: x[1],
        None,
        [("Tom", 20), ("Dick", 30), ("Harry", 40)],
        id="tuples_unique_age",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 20), ("Harry", 40)],
        lambda x: x[1],
        None,
        [("Tom", 20), ("Harry", 40)],
        id="tuples_duplicate_age",
    ),
    pytest.param(
        [("Bob", 20), ("bob", 30), ("Harry", 40)],
        lambda x: x[0],
        None,
        [("Bob", 20), ("bob", 30), ("Harry", 40)],
        id="tuples_name_default_comparer",
    ),
    pytest.param(
        [("Bob", 20), ("bob", 30), ("Harry", 40)],
        lambda x: x[0],
        _ORDINAL_IGNORE_CASE,
        [("Bob", 20), ("Harry", 40)],
        id="tuples_name_ignore_case",
        marks=_SKIP_COMPARER,
    ),
]


@pytest.mark.parametrize("source, key_selector, comparer, expected", _DISTINCT_BY_TEST_DATA)
def test_DistinctBy_HasExpectedOutput(flp_type, source, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(source).distinct_by(key_selector)
    else:
        result = flp_type(source).distinct_by(key_selector, comparer)

    assert expected == list(result)


@pytest.mark.parametrize("source, key_selector, comparer, expected", _DISTINCT_BY_TEST_DATA)
def test_DistinctBy_RunOnce_HasExpectedOutput(flp_type, source, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(_run_once(source)).distinct_by(key_selector)
    else:
        result = flp_type(_run_once(source)).distinct_by(key_selector, comparer)

    assert expected == list(result)