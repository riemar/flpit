"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq UnionTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/UnionTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.
The UnionBy_* tests live in UnionTests.cs upstream (there is no UnionByTests.cs).

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
.NET's int? is mapped to int | None.
.NET's EqualityComparer<string>.Default is Python's default equality/hash, so the test cases
that only pass the default comparer (or a null comparer) run against the comparer-less API.
.NET's ToArray() is mapped to to_list(); Assert.Equal on sequences is mapped to list equality.

Not implemented (skipped with a reason, as elsewhere in nettests):
    * Union(second, IEqualityComparer): union() has no comparer overload yet. The skipped
      bodies assume union(second, comparer) with a comparer object offering
      equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
    * UnionBy (all overloads): union_by() is not implemented yet. The skipped bodies
      assume union_by(second, key_selector) and union_by(second, key_selector, comparer).
"""

from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    SecondNoneError,
    SelectorNoneError,
    SourceNoneError,
)

_SKIP_COMPARER = pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
_SKIP_UNION_BY = pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: union_by")


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


def _not_a_collection(start, count):
    """.NET: NumberRangeGuaranteedNotCollectionType(start, count)."""
    for value in range(start, start + count):
        yield value


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


def _modulo100_equals(x, y):
    if x is None:
        return y is None
    if y is None:
        return False
    return x % 100 == y % 100


def _modulo100_hash(obj):
    return 0 if obj is None else obj % 100 + 1


# Modulo100EqualityComparer : IEqualityComparer<int?>
_MODULO100_COMPARER = _Comparer(_modulo100_equals, _modulo100_hash)

_MISSING = object()


def _is_enumerator_that_enumerates(iterator):
    """.NET: `iterator as IEnumerator<int>` followed by MoveNext()."""
    if not isinstance(iterator, Iterator):
        return False
    return next(iterator, _MISSING) is not _MISSING


def test_SameResultsRepeatCallsIntQuery(flp_type):
    q1 = flp_type([2, 3, None, 2, None, 4, 5]).select(lambda x: x)
    q2 = flp_type([1, 9, None, 4]).select(lambda x: x)

    assert list(q1.union(q2)) == list(q1.union(q2))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q1 = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"]).select(lambda x: x)
    q2 = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS"]).select(lambda x: x)

    assert list(q1.union(q2)) == list(q1.union(q2))


def test_SameResultsRepeatCallsMultipleUnions(flp_type):
    q1 = flp_type([2, 3, None, 2, None, 4, 5]).select(lambda x: x)
    q2 = flp_type([1, 9, None, 4]).select(lambda x: x)
    q3 = flp_type([None, 8, 2, 2, 3]).select(lambda x: x)

    assert list(q1.union(q2).union(q3)) == list(q1.union(q2).union(q3))


def test_BothEmpty(flp_type):
    first = []
    second = []

    assert [] == list(flp_type(first).union(second))


def test_ManyEmpty(flp_type):
    first = []
    second = []
    third = []
    fourth = []

    assert [] == list(flp_type(first).union(second).union(third).union(fourth))


@_SKIP_COMPARER
def test_CustomComparer(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    expected = ["Bob", "Robert", "Tim", "Matt", "Charlie"]

    result = flp_type(first).union(second, _ANAGRAM_COMPARER)

    assert expected == list(result)


@_SKIP_COMPARER
def test_RunOnce(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    expected = ["Bob", "Robert", "Tim", "Matt", "Charlie"]

    result = flp_type(_run_once(first)).union(_run_once(second), _ANAGRAM_COMPARER)

    assert expected == list(result)


@_SKIP_COMPARER
def test_FirstNullCustomComparer(flp_type):
    second = ["ttaM", "Charlie", "Bbo"]

    with pytest.raises(SourceNoneError):
        flp_type(None).union(second, _ANAGRAM_COMPARER)


@_SKIP_COMPARER
def test_SecondNullCustomComparer(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]

    with pytest.raises(SecondNoneError):
        flp_type(first).union(None, _ANAGRAM_COMPARER)


def test_FirstNullNoComparer(flp_type):
    second = ["ttaM", "Charlie", "Bbo"]

    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before union() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).union(second)


def test_SecondNullNoComparer(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]

    with pytest.raises(SecondNoneError):
        flp_type(first).union(None)


def test_SingleNullWithEmpty(flp_type):
    first = [None]
    second = []
    expected = [None]

    # EqualityComparer<string>.Default == Python's default equality.
    assert expected == list(flp_type(first).union(second))


def test_NullEmptyStringMix(flp_type):
    first = [None, None, ""]
    second = [None, None]
    expected = [None, ""]

    # EqualityComparer<string>.Default == Python's default equality.
    assert expected == list(flp_type(first).union(second))


def test_DoubleNullWithEmpty(flp_type):
    first = [None, None]
    second = []
    expected = [None]

    # EqualityComparer<string>.Default == Python's default equality.
    assert expected == list(flp_type(first).union(second))


def test_EmptyWithNonEmpty(flp_type):
    first = []
    second = [2, 4, 5, 3, 2, 3, 9]
    expected = [2, 4, 5, 3, 9]

    assert expected == list(flp_type(first).union(second))


def test_NonEmptyWithEmpty(flp_type):
    first = [2, 4, 5, 3, 2, 3, 9]
    second = []
    expected = [2, 4, 5, 3, 9]

    assert expected == list(flp_type(first).union(second))


def test_CommonElementsShared(flp_type):
    first = [1, 2, 3, 4, 5, 6]
    second = [6, 7, 7, 7, 8, 1]
    expected = [1, 2, 3, 4, 5, 6, 7, 8]

    assert expected == list(flp_type(first).union(second))


def test_SameElementRepeated(flp_type):
    first = [1, 1, 1, 1, 1, 1]
    second = [1, 1, 1, 1, 1, 1]
    expected = [1]

    assert expected == list(flp_type(first).union(second))


def test_RepeatedElementsWithSingleElement(flp_type):
    first = [1, 2, 3, 5, 3, 6]
    second = [7]
    expected = [1, 2, 3, 5, 6, 7]

    assert expected == list(flp_type(first).union(second))


def test_SingleWithAllUnique(flp_type):
    first = [2]
    second = [3, None, 4, 5]
    expected = [2, 3, None, 4, 5]

    assert expected == list(flp_type(first).union(second))


def test_EachHasRepeatsBetweenAndAmongstThemselves(flp_type):
    first = [1, 2, 3, 4, None, 5, 1]
    second = [6, 2, 3, 4, 5, 6]
    expected = [1, 2, 3, 4, None, 5, 6]

    assert expected == list(flp_type(first).union(second))


def test_EachHasRepeatsBetweenAndAmongstThemselvesMultipleUnions(flp_type):
    first = [1, 2, 3, 4, None, 5, 1]
    second = [6, 2, 3, 4, 5, 6]
    third = [2, 8, 2, 3, 2, 8]
    fourth = [None, 1, 7, 2, 7]
    expected = [1, 2, 3, 4, None, 5, 6, 8, 7]

    assert expected == list(flp_type(first).union(second).union(third).union(fourth))


@_SKIP_COMPARER
def test_MultipleUnionsCustomComparer(flp_type):
    first = [1, 102, 903, 204, None, 5, 601]
    second = [6, 202, 903, 204, 5, 106]
    third = [2, 308, 2, 103, 802, 308]
    fourth = [None, 101, 207, 202, 207]
    expected = [1, 102, 903, 204, None, 5, 6, 308, 207]

    result = (
        flp_type(first)
        .union(second, _MODULO100_COMPARER)
        .union(third, _MODULO100_COMPARER)
        .union(fourth, _MODULO100_COMPARER)
    )

    assert expected == list(result)


@_SKIP_COMPARER
def test_MultipleUnionsDifferentComparers(flp_type):
    first = ["Alpha", "Bravo", "Charlie", "Bravo", "Delta", "atleD", "ovarB"]
    second = ["Charlie", "Delta", "Echo", "Foxtrot", "Foxtrot", "choE"]
    third = ["trotFox", "Golf", "Alpha", "choE", "Tango"]

    plain_then_anagram = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Tango"]
    anagram_then_plain = [
        "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "trotFox", "Golf", "choE", "Tango",
    ]

    assert plain_then_anagram == list(flp_type(first).union(second).union(third, _ANAGRAM_COMPARER))
    assert anagram_then_plain == list(flp_type(first).union(second, _ANAGRAM_COMPARER).union(third))


def test_NullEqualityComparer(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    expected = ["Bob", "Robert", "Tim", "Matt", "miT", "ttaM", "Charlie", "Bbo"]

    # .NET calls Union(second, null); the comparer overload with a null comparer is
    # equivalent to the comparer-less call exercised here.
    assert expected == list(flp_type(first).union(second))


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_not_a_collection(0, 3)).union(range(0, 3))

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateMultipleUnions():
    iterator = (
        flp.it(_not_a_collection(0, 3))
        .union(range(0, 3))
        .union(range(2, 6))
        .union([9, 2, 4])
    )

    assert not _is_enumerator_that_enumerates(iterator)


def test_ToArray(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    expected = ["Bob", "Robert", "Tim", "Matt", "miT", "ttaM", "Charlie", "Bbo"]

    assert expected == list(flp_type(first).union(second).to_list())


def test_ToArrayMultipleUnion(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    third = ["Bob", "Albert", "Tim"]
    expected = ["Bob", "Robert", "Tim", "Matt", "miT", "ttaM", "Charlie", "Bbo", "Albert"]

    assert expected == list(flp_type(first).union(second).union(third).to_list())


def test_ToList(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    expected = ["Bob", "Robert", "Tim", "Matt", "miT", "ttaM", "Charlie", "Bbo"]

    assert expected == list(flp_type(first).union(second).to_list())


def test_ToListMultipleUnion(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    third = ["Bob", "Albert", "Tim"]
    expected = ["Bob", "Robert", "Tim", "Matt", "miT", "ttaM", "Charlie", "Bbo", "Albert"]

    assert expected == list(flp_type(first).union(second).union(third).to_list())


def test_Count(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]

    assert 8 == flp_type(first).union(second).count()


def test_CountMultipleUnion(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    third = ["Bob", "Albert", "Tim"]

    assert 9 == flp_type(first).union(second).union(third).count()


def test_RepeatEnumerating(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]

    result = flp_type(first).union(second)

    assert list(result) == list(result)


def test_RepeatEnumeratingMultipleUnions(flp_type):
    first = ["Bob", "Robert", "Tim", "Matt", "miT"]
    second = ["ttaM", "Charlie", "Bbo"]
    third = ["Matt", "Albert", "Ichabod"]

    result = flp_type(first).union(second).union(third)

    assert list(result) == list(result)


def test_HashSetWithBuiltInComparer_HashSetContainsNotUsed():
    # Python sets have no per-instance comparer; "a" and "A" are always distinct.
    input1 = {"a"}
    input2 = ["A"]

    assert ["a", "A"] == list(flp.it(input1).union(input2))
    assert ["a", "A"] == list(flp.it(input1).union(input2))  # .NET: Union(input2, null)
    assert ["a", "A"] == list(flp.it(input1).union(input2))  # .NET: Union(input2, EqualityComparer.Default)

    assert ["A", "a"] == list(flp.it(input2).union(input1))
    assert ["A", "a"] == list(flp.it(input2).union(input1))  # .NET: Union(input1, null)
    assert ["A", "a"] == list(flp.it(input2).union(input1))  # .NET: Union(input1, EqualityComparer.Default)


@_SKIP_COMPARER
def test_HashSetWithBuiltInComparer_CustomComparers():
    input1 = {"a"}
    input2 = ["A"]

    assert ["a"] == list(flp.it(input1).union(input2, _ORDINAL_IGNORE_CASE))
    assert ["A"] == list(flp.it(input2).union(input1, _ORDINAL_IGNORE_CASE))


@_SKIP_UNION_BY
def test_UnionBy_FirstNull_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).union_by(second, lambda x: x)


@_SKIP_UNION_BY
def test_UnionBy_FirstNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    second = ["bBo", "shriC"]

    with pytest.raises(SourceNoneError):
        flp_type(None).union_by(second, lambda x: x, _ANAGRAM_COMPARER)


@_SKIP_UNION_BY
def test_UnionBy_SecondNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).union_by(None, lambda x: x)


@_SKIP_UNION_BY
def test_UnionBy_SecondNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]

    with pytest.raises(SecondNoneError):
        flp_type(first).union_by(None, lambda x: x, _ANAGRAM_COMPARER)


@_SKIP_UNION_BY
def test_UnionBy_KeySelectorNull_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).union_by(second, key_selector)


@_SKIP_UNION_BY
def test_UnionBy_KeySelectorNull_CustomComparer_ThrowsArgumentNullException(flp_type):
    first = ["Bob", "Tim", "Robert", "Chris"]
    second = ["bBo", "shriC"]
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(first).union_by(second, key_selector, _ANAGRAM_COMPARER)


_UNION_BY_TEST_DATA = [
    pytest.param(list(range(0, 7)), list(range(3, 10)), lambda x: x, None, list(range(0, 10)), id="range_overlap"),
    pytest.param(list(range(0, 10)), list(range(10, 20)), lambda x: x, None, list(range(0, 20)), id="range_disjoint"),
    pytest.param([], list(range(0, 5)), lambda x: x, None, list(range(0, 5)), id="empty_first"),
    pytest.param([5] * 20, [], lambda x: x, None, [5], id="repeat_empty_second"),
    pytest.param([5] * 20, [5] * 3, lambda x: x, None, [5], id="repeat_collapses"),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        None,
        ["Bob", "Tim", "Robert", "Chris", "bBo", "shriC"],
        id="strings_default_comparer",
    ),
    pytest.param(
        ["Bob", "Tim", "Robert", "Chris"],
        ["bBo", "shriC"],
        lambda x: x,
        _ANAGRAM_COMPARER,
        ["Bob", "Tim", "Robert", "Chris"],
        id="strings_anagram_comparer",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Martin", 20)],
        [("Peter", 21), ("John", 30), ("Toby", 33)],
        lambda x: x[1],
        None,
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Peter", 21), ("Toby", 33)],
        id="tuples_by_age",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Martin", 20)],
        [("Toby", 33), ("Harry", 35), ("tom", 67)],
        lambda x: x[0],
        None,
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Martin", 20), ("Toby", 33), ("tom", 67)],
        id="tuples_by_name_default_comparer",
    ),
    pytest.param(
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Martin", 20)],
        [("Toby", 33), ("Harry", 35), ("tom", 67)],
        lambda x: x[0],
        _ORDINAL_IGNORE_CASE,
        [("Tom", 20), ("Dick", 30), ("Harry", 40), ("Martin", 20), ("Toby", 33)],
        id="tuples_by_name_ordinal_ignore_case",
    ),
]


@_SKIP_UNION_BY
@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _UNION_BY_TEST_DATA)
def test_UnionBy_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(first).union_by(second, key_selector)
    else:
        result = flp_type(first).union_by(second, key_selector, comparer)

    assert expected == list(result)


@_SKIP_UNION_BY
@pytest.mark.parametrize("first, second, key_selector, comparer, expected", _UNION_BY_TEST_DATA)
def test_UnionBy_RunOnce_HasExpectedOutput(flp_type, first, second, key_selector, comparer, expected):
    if comparer is None:
        result = flp_type(_run_once(first)).union_by(_run_once(second), key_selector)
    else:
        result = flp_type(_run_once(first)).union_by(_run_once(second), key_selector, comparer)

    assert expected == list(result)


# ---------------------------------------------------------------------------
# FlpIt-specific execution invariants (no .NET counterpart)
# ---------------------------------------------------------------------------

def test_Union_IsDeferred_DoesNotConsumeSources():
    first = _run_once([1, 2, 3])
    second = _run_once([3, 4])

    query = flp.it(first).union(second)

    # Building the query consumed nothing; both generators are still untouched.
    assert [1, 2, 3] == list(first)
    assert [3, 4] == list(second)
    assert [] == list(query)  # both exhausted by the assertions above (one-shot semantics)


def test_Union_SecondIsNotEnumeratedUntilFirstIsExhausted():
    log = []

    def first():
        for x in [1, 2, 2]:
            log.append(("first", x))
            yield x

    def second():
        for x in [2, 3]:
            log.append(("second", x))
            yield x

    assert [1, 2, 3] == list(flp.it(first()).union(second()))
    assert log == [
        ("first", 1), ("first", 2), ("first", 2),
        ("second", 2), ("second", 3),
    ]


def test_Union_StreamsAndStopsEarly():
    consumed_first = []
    consumed_second = []

    def first():
        for x in [1, 2, 3]:
            consumed_first.append(x)
            yield x

    def second():
        for x in [4, 5]:
            consumed_second.append(x)
            yield x

    iterator = iter(flp.it(first()).union(second()))

    assert next(iterator) == 1
    assert consumed_first == [1]
    assert consumed_second == []

    assert [2, 3, 4] == [next(iterator) for _ in range(3)]
    assert consumed_second == [4]


def test_Union_SecondNoneIsRaisedAtCallTime():
    # Argument validation is eager, as in .NET; enumeration stays deferred.
    with pytest.raises(SecondNoneError):
        flp.it([1, 2, 3]).union(None)


def test_Union_ReEnumeratesReiterableSources():
    query = flp.it([1, 2, 2]).union([2, 3, 3])

    assert [1, 2, 3] == list(query)
    assert [1, 2, 3] == list(query)
