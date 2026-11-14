"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq LeftJoinTests.cs (.NET 10):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/LeftJoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overloads covered by LeftJoinTests:
    LeftJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
        -> outer.left_join(inner, outer_key_selector, inner_key_selector, result_selector[, comparer])
    LeftJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer])  (yields tuples)
        -> outer.left_join(inner, outer_key_selector, inner_key_selector)   (yields JoinTuple(outer, inner))

.NET helper / language mapping:
    struct CustomerRec / OrderRec / AnagramRec / JoinRec -> NamedTuple
    IEnumerable<T> outer                  -> flp_type(list)   (FlpIt and FlpList)
    IEnumerable<T> inner                  -> plain list
    null key (string / int?)              -> None; None keys never match (like .NET's null keys)
    default(TInner) of an unmatched outer -> None (the result selector / JoinTuple receives None as the inner
                                            element); struct defaults (orderID = 0, total = 0) are mapped by
                                            createJoinRec, which treats `None` as `default(OrderRec)`.
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    AssertExtensions.Throws<ArgumentNullException>("x", ...) -> pytest.raises(<…NoneError>) around the
                                            *call* (not the enumeration), because .NET validates eagerly.
    outer == null                         -> flp_type(None): the FlpIt/FlpList constructor rejects None
                                            with SourceNoneError.
    Assert.Equal(IEnumerable, IEnumerable) -> list(...) == [...]
    `null` comparer argument              -> the argument is simply omitted (default equality).

Not implemented (skipped with a reason, as elsewhere in nettests):
    * LeftJoin(..., IEqualityComparer): left_join() has no comparer overload yet. The skipped bodies assume
      left_join(inner, outer_key_selector, inner_key_selector, result_selector, comparer) with a comparer
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
    # an unmatched outer element receives None, standing in for .NET's default(inner struct)
    if order is None:
        return JoinRec(name=cr.name, orderID=0, total=0)
    return JoinRec(name=cr.name, orderID=order.orderID, total=order.total)


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


_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))


class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


# ---------------------------------------------------------------------------
# LeftJoin(outer, inner, outerKeySelector, innerKeySelector, resultSelector[, comparer])
# ---------------------------------------------------------------------------

def test_OuterEmptyInnerNonEmpty(flp_type):
    outer = flp_type([])
    inner = [
        OrderRec(orderID=45321, custID=98022, total=50),
        OrderRec(orderID=97865, custID=32103, total=25),
    ]

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == []


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
    ]

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


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
    ]

    # .NET passes `null` as the comparer, i.e. default equality: the argument is omitted in Python.
    assert list(outer.left_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)) == expected


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
        outer.left_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())
    ) == expected


@_SKIP_COMPARER
def test_OuterNull(flp_type):
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).left_join(
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
        outer.left_join(None, lambda e: e.name, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


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
        outer.left_join(inner, None, lambda e: e.name, createJoinRec, AnagramEqualityComparer())


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
        outer.left_join(inner, lambda e: e.name, None, createJoinRec, AnagramEqualityComparer())


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
        outer.left_join(inner, lambda e: e.name, lambda e: e.name, None, AnagramEqualityComparer())


def test_OuterNullNoComparer(flp_type):
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
        AnagramRec(name="Prakash", orderID=323232, total=9),
    ]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).left_join(inner, lambda e: e.name, lambda e: e.name, createJoinRec)


def test_InnerNullNoComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
        CustomerRec(name="Robert", custID=99022),
    ])

    # .NET: ArgumentNullException("inner"), thrown eagerly at the call.
    with pytest.raises(InnerNoneError):
        outer.left_join(None, lambda e: e.name, lambda e: e.name, createJoinRec)


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
        outer.left_join(inner, None, lambda e: e.name, createJoinRec)


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
        outer.left_join(inner, lambda e: e.name, None, createJoinRec)


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
        outer.left_join(inner, lambda e: e.name, lambda e: e.name, None)


def test_NullElements(flp_type):
    outer = flp_type([None, ""])
    inner = [None, ""]
    expected = [None, ""]

    # EqualityComparer<string>.Default == default equality: the comparer argument is omitted.
    # The None outer element has a None key, stays unmatched and receives None as the inner element.
    assert list(outer.left_join(inner, lambda e: e, lambda e: e, lambda x, y: y)) == expected


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

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndMatches(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98022)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]
    expected = [JoinRec(name="Prakash", orderID=45321, total=50)]

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SingleElementEachAndDoesntMatch(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98922)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]
    expected = [JoinRec(name="Prakash", orderID=0, total=0)]

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_SelectorsReturnNull(flp_type):
    outer = flp_type([None, None])
    inner = [None, None, None]
    expected = [None, None]

    assert list(outer.left_join(inner, lambda e: e, lambda e: e, lambda x, y: x)) == expected
    assert list(outer.left_join(inner, lambda e: e, lambda e: e, lambda x, y: y)) == expected


@_SKIP_COMPARER
def test_NullKeysRemainUnmatched(flp_type):
    outer = flp_type(["#o1", "a", "#o2"])
    inner = ["#i1", "A", "#i2", "b"]
    expected = [
        "#o1:<null>",
        "a:A",
        "#o2:<null>",
    ]

    def key(s):
        return None if s[0] == "#" else s

    # StringComparer.OrdinalIgnoreCase
    ordinal_ignore_case = _Comparer(
        lambda x, y: (x == y) if x is None or y is None else x.lower() == y.lower(),
        lambda x: 0 if x is None else hash(x.lower()),
    )

    assert list(
        outer.left_join(
            inner, key, key,
            lambda o, i: f"{o}:{'<null>' if i is None else i}",
            ordinal_ignore_case,
        )
    ) == expected


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

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


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

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


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
    ]

    assert list(outer.left_join(inner, lambda e: e.custID, lambda e: e.custID, createJoinRec)) == expected


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_ForceNotCollection(range(0, 3))).left_join([], lambda i: i, lambda i: i, lambda o, i: i)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


# ---------------------------------------------------------------------------
# LeftJoin(outer, inner, outerKeySelector, innerKeySelector[, comparer]) -> tuples
# ---------------------------------------------------------------------------

def test_TupleLeftJoin_Basic(flp_type):
    outer = flp_type(["Prakash", "Tim", "Robert"])
    inner = ["prakash", "robert"]

    result = list(outer.left_join(inner, lambda o: o.lower(), lambda i: i.lower()))

    expected = list(
        outer.left_join(inner, lambda o: o.lower(), lambda i: i.lower(), lambda o, i: (o, i))
    )

    assert result == expected
    assert result == [("Prakash", "prakash"), ("Tim", None), ("Robert", "robert")]


def test_TupleLeftJoin_EmptyOuter(flp_type):
    outer = flp_type([])
    inner = ["prakash"]

    assert list(outer.left_join(inner, lambda o: o, lambda i: i)) == []


def test_TupleLeftJoin_EmptyInner(flp_type):
    outer = flp_type(["Prakash"])
    inner = []

    result = list(outer.left_join(inner, lambda o: o, lambda i: i))
    assert len(result) == 1
    assert result[0].outer == "Prakash"
    assert result[0].inner is None


@_SKIP_COMPARER
def test_TupleLeftJoin_WithComparer(flp_type):
    outer = flp_type([
        CustomerRec(name="Prakash", custID=98022),
        CustomerRec(name="Tim", custID=99021),
    ])
    inner = [
        AnagramRec(name="miT", orderID=43455, total=10),
    ]

    result = list(outer.left_join(inner, lambda o: o.name, lambda i: i.name, AnagramEqualityComparer()))

    assert len(result) == 2
    assert any(r.outer.name == "Prakash" and r.inner is None for r in result)
    assert any(r.outer.name == "Tim" and r.inner.name == "miT" for r in result)


def test_TupleLeftJoin_OuterNull(flp_type):
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    # .NET: ArgumentNullException("outer"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).left_join(inner, lambda o: o.custID, lambda i: i.custID)


def test_TupleLeftJoin_InnerNull(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98022)])

    with pytest.raises(InnerNoneError):
        outer.left_join(None, lambda o: o.custID, lambda i: i.custID)


def test_TupleLeftJoin_OuterKeySelectorNull(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98022)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    with pytest.raises(OuterKeySelectorNoneError):
        outer.left_join(inner, None, lambda i: i.custID)


def test_TupleLeftJoin_InnerKeySelectorNull(flp_type):
    outer = flp_type([CustomerRec(name="Prakash", custID=98022)])
    inner = [OrderRec(orderID=45321, custID=98022, total=50)]

    with pytest.raises(InnerKeySelectorNoneError):
        outer.left_join(inner, lambda o: o.custID, None)
