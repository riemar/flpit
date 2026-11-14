"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq FullJoinTests.cs (.NET 10):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/FullJoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overloads covered by FullJoinTests:
    FullJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
        -> outer.full_join(inner, outer_key_selector, inner_key_selector, result_selector[, comparer])
    FullJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer])   (yields tuples)
        -> outer.full_join(inner, outer_key_selector, inner_key_selector)    (yields JoinTuple(outer, inner))

.NET helper / language mapping:
    struct CustomerRec / OrderRec / AnagramRec / JoinRec -> NamedTuple
    IEnumerable<T> outer                  -> flp_type(list)   (FlpIt and FlpList)
    IEnumerable<T> inner                  -> plain list
    null key (string / int?)              -> None; None keys never match (like .NET's null keys)
    default(TOuter) / default(TInner) of an unmatched side -> None (the result selector / JoinTuple receives
                                            None); struct defaults (name = null, orderID = 0, total = 0)
                                            are mapped by createJoinRec, which treats `None` as default(struct).
    default(int) in the tuple overload    -> None (Python has no value-type defaults), so the .NET
                                            expectation `(1, 0)` / `(0, 4)` reads `(1, None)` / `(None, 4)`.
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    AssertExtensions.Throws<ArgumentNullException>("x", ...) -> pytest.raises(<…NoneError>) around the
                                            *call* (not the enumeration), because .NET validates eagerly.
    outer == null                         -> flp_type(None): the FlpIt/FlpList constructor rejects None
                                            with SourceNoneError.
    Assert.Equal(IEnumerable, IEnumerable) -> list(...) == [...]
    `null` comparer argument              -> the argument is simply omitted (default equality).

Not implemented (skipped with a reason, as elsewhere in nettests):
    * FullJoin(..., IEqualityComparer): full_join() has no comparer overload yet. The skipped bodies assume
      full_join(inner, outer_key_selector, inner_key_selector, result_selector, comparer) with a comparer
      object offering equals(x, y) and get_hash_code(x) like IEqualityComparer<T>.
"""
from collections.abc import Iterator
from typing import NamedTuple

import pytest

from flpit import (
    flp,
    InnerKeySelectorNoneError,
    InnerNoneError,
    JoinTuple,
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
    custID: int = 0


class OrderRec(NamedTuple):
    orderID: int = 0
    custID: int = 0
    total: int = 0


class AnagramRec(NamedTuple):
    name: str | None = None
    orderID: int = 0
    total: int = 0


class JoinRec(NamedTuple):
    name: str | None = None
    orderID: int = 0
    total: int = 0


def createJoinRec(cr, order):
    # an unmatched side receives None, standing in for .NET's default(struct)
    name = None if cr is None else cr.name
    if order is None:
        return JoinRec(name=name, orderID=0, total=0)
    return JoinRec(name=name, orderID=order.orderID, total=order.total)


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


# StringComparer.OrdinalIgnoreCase
_ORDINAL_IGNORE_CASE = _Comparer(
    lambda x, y: (x == y) if x is None or y is None else x.lower() == y.lower(),
    lambda x: 0 if x is None else hash(x.lower()),
)


class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


# ---------------------------------------------------------------------------
# FullJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
# ---------------------------------------------------------------------------

def test_BothEmpty(flp_type):
    outer = flp_type([])
    inner = []

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == []


def test_OuterEmptyInnerNonEmpty(flp_type):
    outer = flp_type([])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=97865, custID=32103, total=25),
    ]
    expected = [
        JoinRec(name=None, orderID=45321, total=50),
        JoinRec(name=None, orderID=97865, total=25),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_OuterNonEmptyInnerEmpty(flp_type):
    outer = flp_type([
        CustomerRec(name="Tim", custID=43434),
        CustomerRec(name="Bob", custID=34093),
    ])
    inner = []
    expected = [
        JoinRec(name="Tim", orderID=0, total=0),
        JoinRec(name="Bob", orderID=0, total=0),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndMatches(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98022)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]
    expected = [JoinRec(name="Prakash", orderID=45321, total=50)]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndDoesntMatch(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98922)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]
    expected = [
        JoinRec(name="Prakash", orderID=0, total=0),
        JoinRec(name=None, orderID=45321, total=50),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_FirstOuterMatchesLastInnerLastOuterMatchesFirstInnerSameNumberElements(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        OrderRec(orderID=45321, custID=99022, total=50),
        OrderRec(orderID=43421, custID=29022, total=20),
        OrderRec(orderID=95421, custID=98022, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=95421, total=9),
        JoinRec(name="Tim", orderID=0, total=0),
        JoinRec(name="Robert", orderID=45321, total=50),
        JoinRec(name=None, orderID=43421, total=20),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_NoMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Bob", custID=99022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        OrderRec(orderID=45321, custID=18022, total=50),
        OrderRec(orderID=43421, custID=29022, total=20),
        OrderRec(orderID=95421, custID=39021, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=0, total=0),
        JoinRec(name="Bob", orderID=0, total=0),
        JoinRec(name="Tim", orderID=0, total=0),
        JoinRec(name="Robert", orderID=0, total=0),
        JoinRec(name=None, orderID=45321, total=50),
        JoinRec(name=None, orderID=43421, total=20),
        JoinRec(name=None, orderID=95421, total=9),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_InnerSameKeyMoreThanOneElementAndMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=45421, custID=98022, total=10),
        OrderRec(orderID=43421, custID=99022, total=20),
        OrderRec(orderID=85421, custID=98022, total=18),
        OrderRec(orderID=95421, custID=99021, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=45321, total=50),
        JoinRec(name="Prakash", orderID=45421, total=10),
        JoinRec(name="Prakash", orderID=85421, total=18),
        JoinRec(name="Tim", orderID=95421, total=9),
        JoinRec(name="Robert", orderID=43421, total=20),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_OuterSameKeyMoreThanOneElementAndMatches(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Bob", custID=99022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=43421, custID=99022, total=20),
        OrderRec(orderID=95421, custID=99021, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=45321, total=50),
        JoinRec(name="Bob", orderID=43421, total=20),
        JoinRec(name="Tim", orderID=95421, total=9),
        JoinRec(name="Robert", orderID=43421, total=20),
    ]

    assert list(outer.full_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_NullComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=323232, total=9),
        JoinRec(name="Tim", orderID=0, total=0),
        JoinRec(name="Robert", orderID=0, total=0),
        JoinRec(name=None, orderID=43455, total=10),
    ]

    # .NET passes `null` as the comparer, i.e. default equality: the argument is omitted in Python.
    assert list(outer.full_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)) == expected


@_SKIP_COMPARER
def test_CustomComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]
    expected = [
        JoinRec(name="Prakash", orderID=323232, total=9),
        JoinRec(name="Tim", orderID=43455, total=10),
        JoinRec(name="Robert", orderID=0, total=0),
    ]

    assert list(
        outer.full_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())
    ) == expected


def test_SelectorsReturnNull(flp_type):
    outer = flp_type([None, None])
    inner = [None, None, None]
    expected = [None, None, None, None, None]

    # null keys never match: both outer elements and all three inner elements are emitted unmatched
    assert list(outer.full_join(inner, lambda e: e, lambda e: e, lambda x, y: x)) == expected
    assert list(outer.full_join(inner, lambda e: e, lambda e: e, lambda x, y: y)) == expected


def test_NullElements(flp_type):
    outer = flp_type([None, ""])
    inner = [None, ""]
    expected = [None, "", None]

    # EqualityComparer<string>.Default == default equality: the comparer argument is omitted.
    assert list(outer.full_join(inner, lambda e: e, lambda e: e, lambda x, y: y)) == expected


@_SKIP_COMPARER
def test_NullKeysAreUnmatchedButPreserved(flp_type):
    outer = flp_type(["#o1", "a", "#o2"])
    inner = ["#i1", "A", "#i2", "b"]
    expected = [
        ("#o1", None),
        ("a", "A"),
        ("#o2", None),
        (None, "#i1"),
        (None, "#i2"),
        (None, "b"),
    ]

    def key(s):
        return None if s[0] == "#" else s

    # StringComparer.OrdinalIgnoreCase
    assert [tuple(r) for r in outer.full_join(inner, key, key, _ORDINAL_IGNORE_CASE)] == expected


@_SKIP_COMPARER
def test_OuterNull(flp_type):
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).full_join(
            inner, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer()
        )


@_SKIP_COMPARER
def test_InnerNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])

    with pytest.raises(InnerNoneError):
        outer.full_join(None, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_OuterKeySelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.full_join(inner, None, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_InnerKeySelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.full_join(inner, lambda e: e.name, None, createJoinRec, AnagramEqualityComparer())


@_SKIP_COMPARER
def test_ResultSelectorNull(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(ResultSelectorNoneError):
        outer.full_join(inner, lambda e: e.name, lambda e: e.name, None, AnagramEqualityComparer())


def test_OuterNullNoComparer(flp_type):
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).full_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)


def test_InnerNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])

    # .NET: ArgumentNullException("inner"), thrown eagerly at the call.
    with pytest.raises(InnerNoneError):
        outer.full_join(None, lambda e: e.name, lambda e: e.name, createJoinRec)


def test_OuterKeySelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.full_join(inner, None, lambda e: e.name, createJoinRec)


def test_InnerKeySelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.full_join(inner, lambda e: e.name, None, createJoinRec)


def test_ResultSelectorNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    with pytest.raises(ResultSelectorNoneError):
        outer.full_join(inner, lambda e: e.name, lambda e: e.name, None)


# ---------------------------------------------------------------------------
# FullJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer]) -> tuples
# ---------------------------------------------------------------------------

def test_TupleOverloadMatchesResultSelector(flp_type):
    outer = flp_type([1, 2, 3])
    inner = [2, 3, 4]

    result = list(outer.full_join(inner, lambda o: o, lambda i: i))

    assert len(result) == 4
    # .NET: (1, 0) and (0, 4) with default(int); Python: None for the missing side.
    assert result[0] == (1, None)
    assert result[1] == (2, 2)
    assert result[2] == (3, 3)
    assert result[3] == (None, 4)
    assert all(isinstance(r, JoinTuple) for r in result)


@_SKIP_COMPARER
def test_TupleOverloadWithComparer(flp_type):
    outer = flp_type(["a", "B"])
    inner = ["A", "c"]

    result = list(outer.full_join(inner, lambda o: o, lambda i: i, _ORDINAL_IGNORE_CASE))

    assert len(result) == 3
    assert result[0] == ("a", "A")
    assert result[1] == ("B", None)
    assert result[2] == (None, "c")


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_ForceNotCollection(range(0, 3))).full_join([], lambda i: i, lambda i: i, lambda o, i: i)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)
