"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ContainsTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ContainsTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper / language mapping:
    IdentityTransforms<int>()          -> _transforms(flp_type): one callable per conftest.create_sources variant
    transform(data)                    -> create_sources(flp_type)(data)[k]
    RunOnce()                          -> flp.it(run_once(...)) (conftest `run_once`)
    IEqualityComparer<T>               -> _Comparer(equals, get_hash_code), same shape as test_distinct.py
    AnagramEqualityComparer            -> _ANAGRAM_COMPARER
    StringComparer.Ordinal(IgnoreCase) -> _ORDINAL / _ORDINAL_IGNORE_CASE
    HashSet<string>(comparer)          -> plain set (Python sets cannot carry a custom comparer)
    int? / null                        -> int | None / None
    (Nullable)NumberRangeGuaranteedNotCollectionType / RepeatedNullableNumberGuaranteedNotCollectionType
                                       -> _ForceNotCollection(...)
    Contains(value) / Contains(value, comparer) -> contains(value) / contains(value, comparer)
                                       (the comparer overload is ASSUMED API, like the skipped bodies in test_distinct.py)
    DefaultIfEmpty / Shuffle / Union / Distinct(comparer) -> assumed names default_if_empty(default),
                                       shuffle(), union(second[, comparer]), distinct(comparer)

Known reasons for failures in this file:
    * FlpIt has no contains() at all (only FlpList does) -> AttributeError for every FlpIt case.
    * No comparer overload: contains(value, comparer) raises TypeError.
    * default_if_empty / shuffle / union / distinct(comparer) are not implemented.
"""
from collections.abc import Iterator

import pytest

from conftest import create_sources
from flpit import flp, SourceNoneError

INT_MIN = -2147483648


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


class _Comparer:
    """IEqualityComparer<T>-like helper."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


_ORDINAL = _Comparer(lambda x, y: x == y, lambda x: hash(x))
_ORDINAL_IGNORE_CASE = _Comparer(
    lambda x, y: (x == y) if x is None or y is None else x.lower() == y.lower(),
    lambda x: 0 if x is None else hash(x.lower()),
)
_ANAGRAM_COMPARER = _Comparer(
    lambda x, y: (x == y) if x is None or y is None else sorted(x) == sorted(y),
    lambda x: 0 if x is None else hash("".join(sorted(x))),
)
_ALWAYS_EQUAL_COMPARER = _Comparer(lambda x, y: True, lambda x: 0)  # EqualityComparer<int>.Create((x, y) => true, x => 0)


def _transforms(flp_type):
    """EnumerableTests.IdentityTransforms<T>(): conftest.create_sources yields two shapes per source."""
    return [lambda data, k=k: create_sources(flp_type)(data)[k] for k in range(2)]


def _ro(run_once, source):
    return flp.it(run_once(source))


# ---------------------------------------------------------------------------
# ContainsTests
# ---------------------------------------------------------------------------

def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)

    assert q.contains(-1) == q.contains(-1)


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: x is not None and x != "")

    assert q.contains("X") == q.contains("X")


_INT_TEST_DATA = [
    ([], 6, False),
    ([8, 10, 3, 0, -8], 6, False),
    ([8, 10, 3, 0, -8], 8, True),
    ([8, 10, 3, 0, -8], -8, True),
    ([8, 0, 10, 3, 0, -8, 0], 0, True),
    (list(range(0, 0)), 0, False),
    (list(range(4, 9)), 3, False),
    (list(range(3, 8)), 3, True),
    (list(range(3, 8)), 7, True),
    (list(range(10, 13)), 10, True),
]


@pytest.mark.parametrize("k", [0, 1])
@pytest.mark.parametrize("data, value, expected", _INT_TEST_DATA)
def test_Int(flp_type, k, data, value, expected):
    source = _transforms(flp_type)[k](data)

    # contains(value, comparer) (here comparer=None) is not a supported overload (TypeError).
    assert expected == source.contains(value)
    # assert expected == source.contains(value, None)


@pytest.mark.parametrize("k", [0, 1])
@pytest.mark.parametrize("data, value, expected", _INT_TEST_DATA)
def test_IntRunOnce(flp_type, run_once, k, data, value, expected):
    source = _transforms(flp_type)[k](data)

    assert expected == _ro(run_once, source).contains(value)
    # assert expected == _ro(run_once, source).contains(value, None)


_STRING_TEST_DATA = [
    ([None], _ORDINAL, None, True),
    (["Bob", "Robert", "Tim"], None, "trboeR", False),
    (["Bob", "Robert", "Tim"], None, "Tim", True),
    # (["Bob", "Robert", "Tim"], _ANAGRAM_COMPARER, "trboeR", True),
    # (["Bob", "Robert", "Tim"], _ANAGRAM_COMPARER, "nevar", False),
]


@pytest.mark.parametrize("source, comparer, value, expected", _STRING_TEST_DATA)
def test_String(flp_type, source, comparer, value, expected):
    source = flp_type(source)

    if comparer is None:
        assert expected == source.contains(value)
    # assert expected == source.contains(value, comparer)


@pytest.mark.parametrize("source, comparer, value, expected", _STRING_TEST_DATA)
def test_StringRunOnce(flp_type, run_once, source, comparer, value, expected):
    source = flp_type(source)

    if comparer is None:
        assert expected == _ro(run_once, source).contains(value)
    # assert expected == _ro(run_once, source).contains(value, comparer)


_NULLABLE_INT_TEST_DATA = [
    ([8, 0, 10, 3, 0, -8, 0], None, False),
    ([8, 0, 10, None, 3, 0, -8, 0], None, True),
    (_ForceNotCollection(range(3, 7)), None, False),
    (_ForceNotCollection([None] * 5), None, True),
]


@pytest.mark.parametrize("source, value, expected", _NULLABLE_INT_TEST_DATA)
def test_NullableInt(flp_type, source, value, expected):
    source = flp_type(source)

    assert expected == source.contains(value)
    # assert expected == source.contains(value, None)


def test_NullSource_ThrowsArgumentNullException(flp_type):
    # .NET: ArgumentNullException("source") for both overloads; flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).contains(42)
    with pytest.raises(SourceNoneError):
        flp_type(None).contains(42, _ORDINAL)


@pytest.mark.skip("comparer not supported")
def test_ExplicitNullComparerDoesNotDeferToCollection(flp_type):
    source = flp_type({"ABC"})  # HashSet<string>(new AnagramEqualityComparer())

    assert not source.contains("BAC", None)


@pytest.mark.skip("comparer not supported")
def test_ExplicitComparerDoesNotDeferToCollection(flp_type):
    source = flp_type({"ABC"})

    assert source.contains("abc", _ORDINAL_IGNORE_CASE)


@pytest.mark.skip("comparer not supported")
def test_ExplicitComparerDoestNotDeferToCollectionWithComparer(flp_type):
    source = flp_type({"ABC"})  # HashSet<string>(StringComparer.OrdinalIgnoreCase)

    assert source.contains("BAC", _ANAGRAM_COMPARER)


@pytest.mark.skip("comparer not supported")
def test_NoComparerDoesDeferToCollection(flp_type):
    source = flp_type({"ABC"})  # HashSet<string>(StringComparer.OrdinalIgnoreCase)

    assert source.contains("abc")


def test_FollowingVariousOperators(flp_type):
    source = flp.range(1, 3)
    for transform in _transforms(flp_type):

        transformed_source = transform(list(source))
        transformed_empty = transform([])

        assert transformed_source.contains(1)
        assert transformed_source.contains(2)
        assert transformed_source.contains(3)
        assert not transformed_source.contains(0)
        assert not transformed_source.contains(4)

        # Append/Prepend
        ap = transformed_source.append(4).prepend(5).append(6).prepend(7)
        assert ap.contains(3)
        assert ap.contains(4)
        assert ap.contains(5)
        assert ap.contains(6)
        assert ap.contains(7)
        assert not ap.contains(8)

        # Concat
        assert transform([4, 5, 6]).concat(transformed_source).contains(2)
        assert not transform([4, 5, 6]).concat(transformed_source).contains(7)
        assert transform([4, 5, 6]).concat(transform([7, 8, 9])).concat(transformed_source).contains(2)
        assert not transform([4, 5, 6]).concat(transform([7, 8, 9])).concat(transformed_source).contains(10)

        # DefaultIfEmpty
        # not supported yet
        # assert transformed_source.default_if_empty(4).contains(1)
        # assert not transformed_empty.default_if_empty(4).contains(0)
        # assert transformed_empty.default_if_empty(4).contains(4)
        # assert not transformed_source.default_if_empty(4).contains(4)
        # assert not transformed_source.default_if_empty(0).contains(4)
        # assert not transformed_source.default_if_empty().contains(0)
        # assert transformed_empty.default_if_empty().contains(0)
        # assert not transformed_source.default_if_empty().contains(4)

        # Distinct
        assert transform(list(source.concat(source))).distinct().contains(2)
        assert not transform(list(source.concat(source))).distinct().contains(4)
        assert transform(list(source.concat(source))).distinct().contains(1)
        # assert transform(list(source.concat(source))).distinct(_ALWAYS_EQUAL_COMPARER).contains(1)
        # assert not transform(list(source.concat(source))).distinct(_ALWAYS_EQUAL_COMPARER).contains(2)
        # assert not transform(list(source.concat(source))).distinct(_ALWAYS_EQUAL_COMPARER).contains(0)

        # OrderBy
        assert transformed_source.order_by(lambda x: x).contains(2)
        assert transformed_source.order_by(lambda x: x).then_by(lambda x: x).contains(2)
        assert not transformed_source.order_by(lambda x: x).contains(4)
        assert not transformed_source.order_by(lambda x: x).then_by(lambda x: x).contains(4)

        # OrderByDescending
        assert transformed_source.order_by_descending(lambda x: x).contains(2)
        assert transformed_source.order_by_descending(lambda x: x).then_by_descending(lambda x: x).contains(2)
        assert not transformed_source.order_by_descending(lambda x: x).contains(4)
        assert not transformed_source.order_by_descending(lambda x: x).then_by_descending(lambda x: x).contains(4)

        # Where/Select
        assert transformed_source.where(lambda x: x > 1).contains(2)
        assert not transformed_source.where(lambda x: x > 3).contains(2)
        assert transformed_source.select(lambda x: x * 2).contains(6)
        assert not transformed_source.select(lambda x: x * 2).contains(3)
        assert transformed_source.where(lambda x: x % 2 == 0).select(lambda x: x * 2).contains(4)
        assert not transformed_source.where(lambda x: x % 2 == 0).select(lambda x: x * 2).contains(6)

        # SelectMany
        assert transformed_source.select_many(lambda x: [x]).contains(2)
        assert transformed_source.select_many(lambda x: [x, x * 2]).contains(2)
        assert not transformed_source.select_many(lambda x: [x]).contains(4)
        assert transformed_source.select_many(lambda x: [x, x * 2]).contains(4)
        assert not transformed_source.select_many(lambda x: [x, x * 2]).contains(5)

        # Shuffle
        # not supported yet
        # assert transformed_source.shuffle().contains(2)
        # assert not transformed_source.shuffle().contains(4)
        # assert not transformed_source.shuffle().take(1).contains(4)
        # assert transformed_source.shuffle().take(3).contains(2)
        # assert not transformed_source.shuffle().take(1).contains(4)
        # trial = 0
        # while trial < 100 and not transformed_source.shuffle().take(1).contains(3):
        #     if trial == 99:
        #         pytest.fail("Shuffle().Take() didn't contain value after 100 tries. "
        #                     "The chances of that are infinitesimal with a correct implementation.")
        #     trial += 1

        # Skip/Take
        assert transformed_source.skip(2).contains(3)
        assert transformed_source.skip(2).take(1).contains(3)
        assert transformed_source.take(1).contains(1)
        assert not transformed_source.take(1).contains(2)
        assert not transformed_source.take(1).contains(2)
        assert not transformed_source.take(2).contains(3)
        assert not transformed_source.skip(1).take(1).contains(1)
        assert transformed_source.skip(1).take(1).contains(2)
        assert not transformed_source.skip(1).take(1).contains(3)

        # Union
        # not supported yet
        # assert transformed_source.union(transform([4])).contains(4)
        # assert transformed_source.union(transform([4]), _ALWAYS_EQUAL_COMPARER).contains(1)
        # assert not transformed_source.union(transform([4]), _ALWAYS_EQUAL_COMPARER).contains(4)
        # assert not transformed_source.union(transform([3])).contains(4)

    # DefaultIfEmpty
    # not supported yet
    # assert flp.it([]).default_if_empty(1).contains(1)
    # assert not flp.it([]).default_if_empty(1).contains(0)

    # Distinct
    assert flp.it(["a", "A"]).distinct().contains("a")
    assert flp.it(["a", "A"]).distinct().contains("A")
    # assert flp.it(["a", "A"]).distinct(_ORDINAL_IGNORE_CASE).contains("a")
    # assert not flp.it(["a", "A"]).distinct(_ORDINAL_IGNORE_CASE).contains("A")

    # Repeat
    assert flp.repeat(1, 5).contains(1)
    assert not flp.repeat(1, 5).contains(2)

    # Cast
    assert flp.it([1, 2, 3]).cast(object).contains(2)
    assert flp.it([1, 2, 3]).cast(int).contains(2)
    assert not flp.it([1, 2, 3]).cast(int).contains(4)

    # OfType
    assert flp.it([1, "2", 3]).of_type(int).contains(3)
    assert not flp.it([1, "2", 3]).of_type(int).contains(4)
    assert not flp.it([1, "2", 3]).of_type(int).contains(2)
    assert flp.it([1, "2", 3]).of_type(str).contains("2")
    assert not flp.it([1, "2", 3]).of_type(str).contains("4")

    # Union
    # not supported yet
    # assert flp.it(["a"]).union(["A"]).contains("a")
    # assert flp.it(["a"]).union(["A"]).contains("A")
    # assert flp.it(["a"]).union(["A"], _ORDINAL_IGNORE_CASE).contains("a")
    # assert not flp.it(["a"]).union(["A"], _ORDINAL_IGNORE_CASE).contains("A")
