"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ToLookupTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ToLookupTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET helper / language mapping:
    ILookup<K, T> / Lookup<K, T>           -> Lookup
    lookup.Count / lookup[key]             -> len(lookup) / lookup[key]
    lookup.Contains(key)                   -> lookup.contains(key) (and `key in lookup`)
    lookup.Count()                         -> lookup.count()
    ICollection<IGrouping>.Contains(g)     -> `g in list(lookup)` (`in` on a Lookup tests keys, like ILookup.Contains)
    ICollection<IGrouping>.CopyTo          -> list(lookup)
    anonymous types { Name, Score }        -> namedtuple _Item(name, score)
    IEqualityComparer<T>                   -> _Comparer(equals, get_hash_code)
    RunOnce()                              -> one-shot generator (_run_once)
    ArgumentNullException("x")             -> pytest.raises(<...NoneError>) around the call (eager operator)

to_lookup() implements ToLookup(keySelector) and ToLookup(keySelector, elementSelector). The comparer
overloads are not implemented yet; the skipped bodies assume a keyword-only `comparer` argument
(like the skipped group_by() comparer bodies):

    to_lookup(key_selector, element_selector=..., *, comparer=None)
"""
from collections import namedtuple
from collections.abc import Collection
from dataclasses import dataclass

import pytest

from flpit import (
    flp,
    ElementSelectorNoneError,
    Grouping,
    Lookup,
    SelectorNoneError,
    SourceNoneError,
)

_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")

_Item = namedtuple("_Item", ["name", "score"])


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


class _Comparer:
    """IEqualityComparer<T>-like helper for the skipped comparer tests."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))


def _anagram_equals(x, y):
    if x is None or y is None:
        return x == y
    return sorted(x) == sorted(y)


def _anagram_hash(obj):
    if obj is None:
        return 0
    return hash("".join(sorted(obj)))


class AnagramEqualityComparer(_Comparer):
    def __init__(self):
        super().__init__(_anagram_equals, _anagram_hash)


def _assert_matches(keys, elements, lookup):
    assert lookup is not None
    assert keys is not None
    assert elements is not None

    num = 0
    el_iterator = iter(elements)
    for key in keys:
        assert lookup.contains(key)

        for e in lookup[key]:
            current = next(el_iterator)  # StopIteration == Assert.True(MoveNext()) failing
            assert e == current
        num += 1
    assert next(el_iterator, _END) is _END
    assert num == len(lookup)


_END = object()


def test_SameResultsRepeatCall(flp_type):
    q1 = flp_type(["Alen", "Felix", None, None, "X", "Have Space", "Clinton", ""]).select(lambda x1: x1)
    q2 = flp_type([55, 49, 9, -100, 24, 25, -1, 0]).select(lambda x2: x2)

    q = q1.select_many(lambda x3: q2.select(lambda x4: (x3, x4)))

    assert list(q.to_lookup(lambda e: e[0])) == list(q.to_lookup(lambda e: e[0]))


def test_Empty(flp_type):
    _assert_matches([], [], flp_type([]).to_lookup(lambda i: i))
    assert not flp_type([]).to_lookup(lambda i: i).contains(0)
    assert list(flp_type([]).to_lookup(lambda i: i)[0]) == []


def test_NullKeyIncluded(flp_type):
    key = ["Chris", "Bob", None, "Tim"]
    element = [50, 95, 55, 90]
    source = flp_type(key).zip(element, lambda k, e: _Item(name=k, score=e))

    _assert_matches(key, source, source.to_lookup(lambda e: e.name))


@_SKIP_COMPARER
def test_OneElementCustomComparer(flp_type):
    key = ["Chris"]
    source = flp_type([_Item(name="risCh", score=50)])

    _assert_matches(key, source, source.to_lookup(lambda e: e.name, comparer=AnagramEqualityComparer()))


def test_UniqueElementsElementSelector(flp_type):
    key = ["Chris", "Prakash", "Tim", "Robert", "Brian"]
    element = [50, 100, 95, 60, 80]
    source = flp_type([_Item(name=k, score=e) for k, e in zip(key, element)])

    _assert_matches(key, element, source.to_lookup(lambda e: e.name, lambda e: e.score))


def _duplicate_key_source():
    key = ["Chris", "Prakash", "Robert"]
    element = [50, 80, 100, 95, 99, 56]
    source = [
        _Item(name=key[0], score=element[0]),
        _Item(name=key[1], score=element[2]),
        _Item(name=key[2], score=element[5]),
        _Item(name=key[1], score=element[3]),
        _Item(name=key[0], score=element[1]),
        _Item(name=key[1], score=element[4]),
    ]
    return key, element, source


@_SKIP_COMPARER
def test_DuplicateKeys(flp_type):
    key, element, source = _duplicate_key_source()

    _assert_matches(
        key, element,
        flp_type(source).to_lookup(lambda e: e.name, lambda e: e.score, comparer=AnagramEqualityComparer()),
    )


@_SKIP_COMPARER
def test_RunOnce(flp_type):
    key, element, source = _duplicate_key_source()

    _assert_matches(
        key, element,
        flp_type(_run_once(source)).to_lookup(lambda e: e.name, lambda e: e.score, comparer=AnagramEqualityComparer()),
    )


def test_Count(flp_type):
    _, _, source = _duplicate_key_source()

    assert flp_type(source).to_lookup(lambda e: e.name, lambda e: e.score).count() == 3


@_SKIP_COMPARER
def test_EmptySource(flp_type):
    key = []
    element = []
    source = flp_type(key).zip(element, lambda k, e: _Item(name=k, score=e))

    _assert_matches(
        key, element,
        source.to_lookup(lambda e: e.name, lambda e: e.score, comparer=AnagramEqualityComparer()),
    )


@_SKIP_COMPARER
def test_SingleNullKeyAndElement(flp_type):
    key = [None]
    element = [None]
    source = flp_type([None])

    _assert_matches(key, element, source.to_lookup(lambda e: e, lambda e: e, comparer=_DEFAULT_COMPARER))


def test_NullSource(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError, match="'source'"):
        flp_type(None).to_lookup(lambda i: i // 10)


@_SKIP_COMPARER
def test_NullSourceExplicitComparer(flp_type):
    with pytest.raises(SourceNoneError, match="'source'"):
        flp_type(None).to_lookup(lambda i: i // 10, comparer=_DEFAULT_COMPARER)


def test_NullSourceElementSelector(flp_type):
    with pytest.raises(SourceNoneError, match="'source'"):
        flp_type(None).to_lookup(lambda i: i // 10, lambda i: i + 2)


@_SKIP_COMPARER
def test_NullSourceElementSelectorExplicitComparer(flp_type):
    with pytest.raises(SourceNoneError, match="'source'"):
        flp_type(None).to_lookup(lambda i: i // 10, lambda i: i + 2, comparer=_DEFAULT_COMPARER)


def test_NullKeySelector(flp_type):
    key_selector = None
    with pytest.raises(SelectorNoneError, match="'keySelector'"):
        flp_type(range(1000)).to_lookup(key_selector)


@_SKIP_COMPARER
def test_NullKeySelectorExplicitComparer(flp_type):
    key_selector = None
    with pytest.raises(SelectorNoneError, match="'keySelector'"):
        flp_type(range(1000)).to_lookup(key_selector, comparer=_DEFAULT_COMPARER)


def test_NullKeySelectorElementSelector(flp_type):
    key_selector = None
    with pytest.raises(SelectorNoneError, match="'keySelector'"):
        flp_type(range(1000)).to_lookup(key_selector, lambda i: i + 2)


@_SKIP_COMPARER
def test_NullKeySelectorElementSelectorExplicitComparer(flp_type):
    key_selector = None
    with pytest.raises(SelectorNoneError, match="'keySelector'"):
        flp_type(range(1000)).to_lookup(key_selector, lambda i: i + 2, comparer=_DEFAULT_COMPARER)


def test_NullElementSelector(flp_type):
    element_selector = None
    with pytest.raises(ElementSelectorNoneError, match="'elementSelector'"):
        flp_type(range(1000)).to_lookup(lambda i: i // 10, element_selector)


@_SKIP_COMPARER
def test_NullElementSelectorExplicitComparer(flp_type):
    element_selector = None
    with pytest.raises(ElementSelectorNoneError, match="'elementSelector'"):
        flp_type(range(1000)).to_lookup(lambda i: i // 10, element_selector, comparer=_DEFAULT_COMPARER)


# ---------------------------------------------------------------------------
# ApplyResultSelector
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Role:
    id: int = 0

    def __eq__(self, other):
        return isinstance(other, Role) and self.id == other.id

    def __hash__(self):
        return self.id


@dataclass
class Membership:
    id: int
    role: Role
    count_me: bool


@dataclass
class RoleMetadata:
    role: Role
    count_a: int
    countr_b: int


@pytest.mark.skip("result selector not implemented yet")
@pytest.mark.parametrize("enum_type", [1, 2, 3])
def test_ApplyResultSelectorForGroup(flp_type, enum_type):
    # .NET exercises GroupBy(keySelector, resultSelector) here (Lookup's internal ApplyResultSelector);
    # the body assumes group_by()'s keyword-only result_selector (see test_group_by.py).
    roles = [Role(id=1), Role(id=2), Role(id=3)]

    memberships = flp_type(range(50)).select(
        lambda i: Membership(id=i, role=roles[i % 3], count_me=i % 3 == 0)
    )

    grouping = memberships.group_by(
        lambda m: m.role,
        result_selector=lambda role, mems: RoleMetadata(
            role=role,
            count_a=mems.count(lambda m: m.count_me),
            countr_b=mems.count(lambda m: not m.count_me),
        ),
    )

    if enum_type == 1:
        result = grouping.to_list()
    elif enum_type == 2:
        result = list(grouping)  # ToArray()
    else:
        result = grouping

    expected = [
        RoleMetadata(role=Role(id=1), count_a=17, countr_b=0),
        RoleMetadata(role=Role(id=2), count_a=0, countr_b=17),
        RoleMetadata(role=Role(id=3), count_a=0, countr_b=16),
    ]

    assert list(result) == expected


@pytest.mark.skip("apply_result_selector() not implemented yet")
def test_ApplyResultSelector(flp_type):
    lookup = flp_type([1, 2, 2, 3, 3, 3]).to_lookup(lambda i: i)

    def _selector(key, elements):
        assert key == elements.count()
        return elements.sum()

    sums = lookup.apply_result_selector(_selector)
    assert list(sums) == [1, 4, 9]


# ---------------------------------------------------------------------------
# ICollection<IGrouping<TKey, TElement>>
# ---------------------------------------------------------------------------

def _nop_grouping():
    """NopGrouping: an empty grouping with key "" that is never part of the lookup."""
    return Grouping("", [])


@pytest.mark.parametrize("count", [0, 1, 10])
def test_LookupImplementsICollection(flp_type, count):
    assert isinstance(flp_type(range(count)).to_lookup(str), Collection)
    assert isinstance(flp_type(range(count)).to_lookup(str, lambda i: i), Collection)
    # comparer overloads (StringComparer.OrdinalIgnoreCase) not implemented yet

    collection = flp_type(range(count)).to_lookup(str)
    assert isinstance(collection, Lookup)
    assert len(collection) == count
    # IsReadOnly / Add / Remove / Clear throw NotSupportedException -> no mutators exist
    for mutator in ("add", "remove", "clear", "__setitem__", "__delitem__"):
        assert not hasattr(collection, mutator)

    if count > 0:
        first = collection.first()
        last = collection.last()
        assert first in list(collection)
        assert last in list(collection)
    assert _nop_grouping() not in list(collection)

    items = list(collection)  # CopyTo
    assert list(collection.select(lambda i: i)) == items
    assert items == list(flp_type(range(count)).to_lookup(str))
    assert items == flp_type(range(count)).to_lookup(str).to_list()
