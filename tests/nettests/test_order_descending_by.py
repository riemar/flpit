"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Tests for the FlpIt ``take`` operator.

Ported to pytest/Python from the .NET Runtime System.Linq OrderDescendingTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/OrderDescendingTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import random
from types import SimpleNamespace
import pytest


def case_insensitive_cmp(x, y):
    x_lower = x.casefold() if x is not None else None
    y_lower = y.casefold() if y is not None else None

    if x_lower == y_lower:
        return 0
    if x_lower is None:
        return -1
    if y_lower is None:
        return 1
    return 1 if x_lower > y_lower else -1


def extreme_cmp(x, y):
    if x == y:
        return 0
    if x < y:
        return -2147483648
    return 2147483647


def test_SameResultsRepeatCallsIntQuery(flp_type):
    x1_seq = [1, 6, 0, -1, 3]
    x2_seq = [55, 49, 9, -100, 24, 25]

    q = flp_type([
        SimpleNamespace(a1=x1, a2=x2)
        for x1 in x1_seq
        for x2 in x2_seq
    ])

    res1 = list(q.order_by_descending(lambda e: e.a1))
    res2 = list(q.order_by_descending(lambda e: e.a1))

    assert res1 == res2


def test_SameResultsRepeatCallsStringQuery(flp_type):
    x1_seq = [55, 49, 9, -100, 24, 25, -1, 0]
    x2_seq = ["!@#$%^", "C", "AAA", "", None, "Calling Twice", "SoS", ""]

    q = flp_type([
        SimpleNamespace(a1=x1, a2=x2)
        for x1 in x1_seq
        for x2 in x2_seq
        if x2 is not None and x2 != ""
    ])

    res1 = list(q.order_by_descending(lambda e: e.a1).then_by(lambda f: f.a2))
    res2 = list(q.order_by_descending(lambda e: e.a1).then_by(lambda f: f.a2))

    assert res1 == res2


def test_SourceEmpty(flp_type):
    source = flp_type([])
    assert list(source.order_by_descending(lambda e: e)) == []


def test_KeySelectorReturnsNull(flp_type):
    source = flp_type([None, None, None])
    expected = [None, None, None]

    assert list(source.order_by_descending(lambda e: e)) == expected


def test_ElementsAllSameKey(flp_type):
    source = flp_type([9, 9, 9, 9, 9, 9])
    expected = [9, 9, 9, 9, 9, 9]

    assert list(source.order_by_descending(lambda e: e)) == expected


def test_KeySelectorCalled(flp_type):
    source = flp_type([
        SimpleNamespace(Name="Alpha", Score=90),
        SimpleNamespace(Name="Robert", Score=45),
        SimpleNamespace(Name="Prakash", Score=99),
        SimpleNamespace(Name="Bob", Score=0),
    ])
    expected = [
        SimpleNamespace(Name="Robert", Score=45),
        SimpleNamespace(Name="Prakash", Score=99),
        SimpleNamespace(Name="Bob", Score=0),
        SimpleNamespace(Name="Alpha", Score=90),
    ]

    # original line set explicitly None for comparer, which is currently unsupported
    # assert list(source.order_by_descending(lambda e: e.Name, None)) == expected
    assert list(source.order_by_descending(lambda e: e.Name)) == expected


def test_FirstAndLastAreDuplicatesCustomComparer(flp_type):
    pytest.skip("Comparer not supported yet")
    source = flp_type(["Prakash", "Alpha", "DAN", "dan", "Prakash"])
    expected = ["Prakash", "Prakash", "DAN", "dan", "Alpha"]

    assert list(source.order_by_descending(lambda e: e, case_insensitive_cmp)) == expected


def test_RunOnce(flp_type):
    pytest.skip("Comparer not supported yet")
    source = flp_type(["Prakash", "Alpha", "DAN", "dan", "Prakash"])
    expected = ["Prakash", "Prakash", "DAN", "dan", "Alpha"]

    assert list(source.run_once().order_by_descending(lambda e: e, case_insensitive_cmp)) == expected


def test_FirstAndLastAreDuplicatesNullPassedAsComparer(flp_type):
    source = flp_type([5, 1, 3, 2, 5])
    expected = [5, 5, 3, 2, 1]

    # original line set explicitly None for comparer, which is currently unsupported
    # assert list(source.order_by_descending(lambda e: e, None)) == expected
    assert list(source.order_by_descending(lambda e: e)) == expected


def test_SourceReverseOfResultNullPassedAsComparer(flp_type):
    source = flp_type([-75, -50, 0, 5, 9, 30, 100])
    expected = [100, 30, 9, 5, 0, -50, -75]

    # original line set explicitly None for comparer, which is currently unsupported
    # assert list(source.order_by_descending(lambda e: e, None)) == expected
    assert list(source.order_by_descending(lambda e: e)) == expected


def test_SameKeysVerifySortStable(flp_type):
    source = flp_type([
        SimpleNamespace(Name="Alpha", Score=90),
        SimpleNamespace(Name="Robert", Score=45),
        SimpleNamespace(Name="Prakash", Score=99),
        SimpleNamespace(Name="Bob", Score=90),
        SimpleNamespace(Name="Thomas", Score=45),
        SimpleNamespace(Name="Tim", Score=45),
        SimpleNamespace(Name="Mark", Score=45),
    ])
    expected = [
        SimpleNamespace(Name="Prakash", Score=99),
        SimpleNamespace(Name="Alpha", Score=90),
        SimpleNamespace(Name="Bob", Score=90),
        SimpleNamespace(Name="Robert", Score=45),
        SimpleNamespace(Name="Thomas", Score=45),
        SimpleNamespace(Name="Tim", Score=45),
        SimpleNamespace(Name="Mark", Score=45),
    ]

    assert list(source.order_by_descending(lambda e: e.Score)) == expected


def test_OrderByExtremeComparer(flp_type):
    pytest.skip("Comparer not supported yet")
    out_of_order = flp_type([7, 1, 0, 9, 3, 5, 4, 2, 8, 6])

    ordered = list(out_of_order.order_by_descending(lambda i: i, extreme_cmp))
    expected = list(reversed(range(10)))

    assert ordered == expected


def test_NullSource():
    source = None
    with pytest.raises((TypeError, AttributeError)):
        source.order_by_descending(lambda i: i)


def test_NullKeySelector(flp_type):
    key_selector = None
    with pytest.raises((TypeError, ValueError)):
        flp_type([]).order_by_descending(key_selector)


def test_SortsLargeAscendingEnumerableCorrectly(flp_type):
    items = 1_000_000
    expected = list(range(items))

    unordered = flp_type((i for i in range(items))).select(lambda i: i)
    ordered = unordered.order_by_descending(lambda i: -i)

    assert list(ordered) == expected


def test_SortsLargeDescendingEnumerableCorrectly(flp_type):
    items = 1_000_000
    expected = list(range(items))

    unordered = flp_type((items - i - 1 for i in range(items)))
    ordered = unordered.order_by_descending(lambda i: -i)

    assert list(ordered) == expected


@pytest.mark.parametrize("items", [0, 1, 2, 3, 8, 16, 1024, 4096, 1_000_000])
def test_SortsRandomizedEnumerableCorrectly(flp_type, items):
    r = random.Random(42)
    randomized = [r.randint(0, 2**31 - 1) for _ in range(items)]

    # iter() simulates ForceNotCollection
    ordered = list(flp_type(iter(randomized)).order_by_descending(lambda i: -i))

    randomized.sort()
    assert ordered == randomized


def test_OrderByDescending_FirstLast_MatchesArray(flp_type):
    arrays = [
        [1],
        [1, 1],
        [1, 2, 1],
        [1, 2, 1, 3],
        [2, 1, 3, 1, 4],
    ]

    for objects in arrays:
        source = flp_type(objects)
        # Using `is` closely reflects Assert.Same reference checking
        assert source.order_by_descending(lambda x: x).first() is list(source.order_by_descending(lambda x: x))[0]
        assert source.order_by_descending(lambda x: x).last() is list(source.order_by_descending(lambda x: x))[-1]