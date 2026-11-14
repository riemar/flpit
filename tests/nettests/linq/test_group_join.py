"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq GroupJoinTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/GroupJoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overloads covered by GroupJoinTests:
    GroupJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
        -> outer.group_join(inner, outer_key_selector, inner_key_selector, result_selector[, comparer])
    GroupJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer])   (.NET 10, yields IGrouping)
        -> outer.group_join(inner, outer_key_selector, inner_key_selector[, comparer=...])
           (yields Grouping(key=outer, items=matching inner elements))

.NET helper / language mapping:
    struct CustomerRec / OrderRec / AnagramRec / JoinRec -> NamedTuple (JoinRec.orderID / .total are lists,
                                            standing in for int?[]; list equality replaces JoinRec.Equals)
    IEnumerable<T> outer                  -> flp_type(list)   (FlpIt and FlpList)
    IEnumerable<T> inner                  -> plain list
    IEnumerable<TInner> passed to the result selector -> FlpList[TInner] (re-enumerable)
    IGrouping<TOuter, TInner>             -> Grouping (.key is the *outer* element)
    null key (string / int?)              -> None; None keys never match (like .NET's null keys)
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    outer.RunOnce() / inner.RunOnce()     -> RunOnceEnumerable via the `run_once` fixture
    AssertExtensions.Throws<ArgumentNullException>("x", ...) -> pytest.raises(<...NoneError>) around the
                                            *call* (not the enumeration), because .NET validates eagerly.
    outer == null                         -> flp_type(None): the FlpIt/FlpList constructor rejects None
                                            with SourceNoneError.
    Assert.Equal(IEnumerable, IEnumerable) -> list(...) == [...]
    Assert.Empty / Assert.Single          -> `== []` / `len(...) == 1`
    `null` comparer argument              -> the argument is simply omitted (default equality).
    EqualityComparer<string>.Default      -> the argument is omitted (default equality).

Not implemented (skipped with a reason, as elsewhere in nettests):
    * GroupJoin(..., IEqualityComparer): group_join() has no comparer overload yet. The skipped bodies assume
      group_join(inner, outer_key_selector, inner_key_selector, result_selector, comparer) and, without a
      result selector, group_join(inner, outer_key_selector, inner_key_selector, comparer=comparer), with a
      comparer object offering equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
"""
from collections.abc import Iterator
from typing import NamedTuple

import pytest

from flpit import (
    flp,
    InnerKeySelectorNoneError,
    InnerNoneError,
    OuterKeySelectorNoneError,
    ResultSelectorNoneError,
    SourceNoneError,
)

_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class CustomerRec(NamedTuple):
    name: str | None = None
    custID: int | None = None


class OrderRec(NamedTuple):
    orderID: int | None = None
    custID: int | None = None
    total: int | None = None


class AnagramRec(NamedTuple):
    name: str | None = None
    orderID: int | None = None
    total: int | None = None


class JoinRec(NamedTuple):
    name: str | None
    orderID: list
    total: list


def createJoinRec(cr, orIE):
    """Both .NET createJoinRec overloads (OrderRec / AnagramRec groups) in one."""
    return JoinRec(
        name=cr.name,
        orderID=[o.orderID for o in orIE],
        total=[o.total for o in orIE],
    )


class _Comparer:
    """IEqualityComparer<T>-like helper for the skipped comparer tests."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


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


class AnagramEqualityComparer(_Comparer):
    def __init__(self):
        super().__init__(_anagram_equals, _anagram_hash)


class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


# ---------------------------------------------------------------------------
# GroupJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
# ---------------------------------------------------------------------------

def test_OuterEmptyInnerNonEmpty(flp_type):
    outer = flp_type([])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=97865, custID=32103, total=25),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == []


@_SKIP_COMPARER
def test_CustomComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[93489], total=[45]),
        JoinRec(name="Bob", orderID=[], total=[]),
        JoinRec(name="Robert", orderID=[93483], total=[19]),
    ]

    assert list(
        outer.group_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())
    ) == expected


@_SKIP_COMPARER
def test_OuterNull(flp_type):
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).group_join(
            inner, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer()
        )


@_SKIP_COMPARER
def test_InnerNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])

    with pytest.raises(InnerNoneError):
        outer.group_join(None, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_OuterKeySelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.group_join(inner, None, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_InnerKeySelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.group_join(inner, lambda e: e.name, None, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_ResultSelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(ResultSelectorNoneError):
        outer.group_join(inner, lambda e: e.name, lambda e: e.name, None, AnagramEqualityComparer())


def test_OuterNullNoComparer(flp_type):
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).group_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)


def test_InnerNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])

    # .NET: ArgumentNullException("inner"), thrown eagerly at the call.
    with pytest.raises(InnerNoneError):
        outer.group_join(None, lambda e: e.name, lambda e: e.name, createJoinRec)


def test_OuterKeySelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.group_join(inner, None, lambda e: e.name, createJoinRec)


def test_InnerKeySelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.group_join(inner, lambda e: e.name, None, createJoinRec)


def test_ResultSelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    with pytest.raises(ResultSelectorNoneError):
        outer.group_join(inner, lambda e: e.name, lambda e: e.name, None)


def test_OuterInnerBothSingleNullElement(flp_type):
    outer = flp_type([None])
    inner = [None]
    expected = [None]

    # EqualityComparer<string>.Default == default equality: the comparer argument is omitted.
    # The null outer element is still produced (with an empty group): None keys never match.
    assert list(outer.group_join(inner, lambda e: e, lambda e: e, lambda x, y: x)) == expected


def test_OuterNonEmptyInnerEmpty(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=43434),
        CustomerRec(name="Bob", custID=34093),
    ])
    inner = []
    expected = [
        JoinRec(name="Tim", orderID=[], total=[]),
        JoinRec(name="Bob", orderID=[], total=[]),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndMatches(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=43434)])
    inner = [OrderRec(orderID=97865, custID=43434, total=25)]
    expected = [JoinRec(name="Tim", orderID=[97865], total=[25])]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndDoesntMatch(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=43434)])
    inner = [OrderRec(orderID=97865, custID=49434, total=25)]
    expected = [JoinRec(name="Tim", orderID=[], total=[])]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SelectorsReturnNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=None),
        CustomerRec(name="Bob", custID=None),
    ])
    inner = [
        OrderRec(orderID=97865, custID=None, total=25),
        OrderRec(orderID=34390, custID=None, total=19),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[], total=[]),
        JoinRec(name="Bob", orderID=[], total=[]),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_InnerSameKeyMoreThanOneElementAndMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
    ])
    inner = [
        OrderRec(orderID=97865, custID=1234, total=25),
        OrderRec(orderID=34390, custID=1234, total=19),
        OrderRec(orderID=34390, custID=9865, total=19),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[97865, 34390], total=[25, 19]),
        JoinRec(name="Bob", orderID=[34390], total=[19]),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_InnerSameKeyMoreThanOneElementAndMatchesRunOnce(flp_type, run_once):
    outer = [
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
    ]
    inner = [
        OrderRec(orderID=97865, custID=1234, total=25),
        OrderRec(orderID=34390, custID=1234, total=19),
        OrderRec(orderID=34390, custID=9865, total=19),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[97865, 34390], total=[25, 19]),
        JoinRec(name="Bob", orderID=[34390], total=[19]),
    ]

    result = flp_type(run_once(outer)).group_join(
        run_once(inner), lambda e: e.custID, lambda e: e.custID, createJoinRec
    )

    assert list(result) == expected


def test_OuterSameKeyMoreThanOneElementAndMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9865),
    ])
    inner = [
        OrderRec(orderID=97865, custID=1234, total=25),
        OrderRec(orderID=34390, custID=9865, total=19),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[97865], total=[25]),
        JoinRec(name="Bob", orderID=[34390], total=[19]),
        JoinRec(name="Robert", orderID=[34390], total=[19]),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_NoMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        OrderRec(orderID=97865, custID=2334, total=25),
        OrderRec(orderID=34390, custID=9065, total=19),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[], total=[]),
        JoinRec(name="Bob", orderID=[], total=[]),
        JoinRec(name="Robert", orderID=[], total=[]),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_NullComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ])
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[], total=[]),
        JoinRec(name="Bob", orderID=[], total=[]),
        JoinRec(name="Robert", orderID=[93483], total=[19]),
    ]

    # .NET passes `null` as the comparer, i.e. default equality: the argument is omitted in Python.
    assert list(outer.group_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)) == expected


def test_NullComparerRunOnce(flp_type, run_once):
    outer = [
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ]
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]
    expected = [
        JoinRec(name="Tim", orderID=[], total=[]),
        JoinRec(name="Bob", orderID=[], total=[]),
        JoinRec(name="Robert", orderID=[93483], total=[19]),
    ]

    # .NET passes `null` as the comparer, i.e. default equality: the argument is omitted in Python.
    result = flp_type(run_once(outer)).group_join(
        run_once(inner), lambda e: e.name, lambda e: e.name, createJoinRec
    )

    assert list(result) == expected


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_ForceNotCollection(range(0, 3))).group_join([], lambda i: i, lambda i: i, lambda o, i: i)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


# ---------------------------------------------------------------------------
# GroupJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer]) -> IGrouping<TOuter, TInner>
# ---------------------------------------------------------------------------

def test_GroupJoinWithoutResultSelector_OuterEmptyInnerNonEmpty(flp_type):
    outer = flp_type([])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=97865, custID=32103, total=25),
    ]

    assert list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID)) == []


def test_GroupJoinWithoutResultSelector_OuterNonEmptyInnerEmpty(flp_type):
    outer_items = [
        CustomerRec(name="Tim", custID=43434),
        CustomerRec(name="Bob", custID=34093),
    ]
    outer = flp_type(outer_items)
    inner = []

    result = list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID))

    assert len(result) == 2
    assert result[0].key == outer_items[0]
    assert list(result[0]) == []
    assert result[1].key == outer_items[1]
    assert list(result[1]) == []


def test_GroupJoinWithoutResultSelector_SingleElementEachAndMatches(flp_type):
    outer_items = [CustomerRec(name="Tim", custID=43434)]
    outer = flp_type(outer_items)
    inner = [OrderRec(orderID=97865, custID=43434, total=25)]

    result = list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID))

    assert len(result) == 1
    assert result[0].key == outer_items[0]
    assert len(result[0]) == 1
    assert result[0].first() == inner[0]


def test_GroupJoinWithoutResultSelector_InnerSameKeyMoreThanOneElementAndMatches(flp_type):
    outer_items = [
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
    ]
    outer = flp_type(outer_items)
    inner = [
        OrderRec(orderID=97865, custID=1234, total=25),
        OrderRec(orderID=34390, custID=1234, total=19),
        OrderRec(orderID=34390, custID=9865, total=19),
    ]

    result = list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID))

    assert len(result) == 2
    assert result[0].key == outer_items[0]
    assert result[0].count() == 2
    assert result[1].key == outer_items[1]
    assert len(result[1]) == 1


def test_GroupJoinWithoutResultSelector_OuterNull(flp_type):
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).group_join(inner, lambda e: e.custID, lambda e: e.custID)


def test_GroupJoinWithoutResultSelector_InnerNull(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=1234)])

    with pytest.raises(InnerNoneError):
        outer.group_join(None, lambda e: e.custID, lambda e: e.custID)


def test_GroupJoinWithoutResultSelector_OuterKeySelectorNull(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=1234)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.group_join(inner, None, lambda e: e.custID)


def test_GroupJoinWithoutResultSelector_InnerKeySelectorNull(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=1234)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.group_join(inner, lambda e: e.custID, None)


def test_GroupJoinWithoutResultSelector_CanIterateMultipleTimes(flp_type):
    outer = flp_type([CustomerRec(name="Tim", custID=1234)])
    inner = [OrderRec(orderID=97865, custID=1234, total=25)]

    result = list(outer.group_join(inner, lambda e: e.custID, lambda e: e.custID))

    assert len(result) == 1

    # Iterate the grouped elements multiple times
    assert len(result[0]) == 1
    assert len(result[0]) == 1
    assert result[0].first() == inner[0]
    assert result[0].first() == inner[0]
    assert list(result[0]) == list(result[0]) == [inner[0]]


@_SKIP_COMPARER
def test_GroupJoinWithoutResultSelector_CustomComparer(flp_type):
    outer_items = [
        CustomerRec(name="Tim", custID=1234),
        CustomerRec(name="Bob", custID=9865),
        CustomerRec(name="Robert", custID=9895),
    ]
    outer = flp_type(outer_items)
    inner = [
        AnagramRec(name="Robert", orderID=93483, total=19),
        AnagramRec(name="miT", orderID=93489, total=45),
    ]

    result = list(
        outer.group_join(inner, lambda e: e.name, lambda e: e.name, comparer=AnagramEqualityComparer())
    )

    assert len(result) == 3
    assert result[0].key == outer_items[0]
    assert len(result[0]) == 1
    assert result[0].first() == inner[1]
    assert result[1].key == outer_items[1]
    assert list(result[1]) == []
    assert result[2].key == outer_items[2]
    assert len(result[2]) == 1
    assert result[2].first() == inner[0]
