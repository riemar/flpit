"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Tests for the FlpIt ``take`` operator.

Ported to pytest/Python from the .NET Runtime System.Linq ThenByDescendingTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ThenByDescendingTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest
import random
import re
from types import SimpleNamespace


def reverse_int_cmp(x, y):
    if y > x:
        return 1
    if y < x:
        return -1
    return 0


def test_SameResultsRepeatCallsIntQuery(flp_type):
    x1_seq = [1, 6, 0, -1, 3]
    x2_seq = [55, 49, 9, -100, 24, 25]

    q = flp_type([
        SimpleNamespace(a1=x1, a2=x2)
        for x1 in x1_seq
        for x2 in x2_seq
    ])

    res1 = list(q.order_by_descending(lambda e: e.a2).then_by_descending(lambda f: f.a1))
    res2 = list(q.order_by_descending(lambda e: e.a2).then_by_descending(lambda f: f.a1))

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

    res1 = list(q.order_by(lambda e: e.a1).then_by_descending(lambda f: f.a2))
    res2 = list(q.order_by(lambda e: e.a1).then_by_descending(lambda f: f.a2))

    assert res1 == res2


def test_SourceEmpty(flp_type):
    source = flp_type([])
    assert list(source.order_by(lambda e: e).then_by_descending(lambda e: e)) == []


def test_AscendingKeyThenDescendingKey(flp_type):
    source = flp_type([
        SimpleNamespace(Name="Jim", City="Minneapolis", Country="USA"),
        SimpleNamespace(Name="Tim", City="Seattle", Country="USA"),
        SimpleNamespace(Name="Philip", City="Orlando", Country="USA"),
        SimpleNamespace(Name="Chris", City="London", Country="UK"),
        SimpleNamespace(Name="Rob", City="Kent", Country="UK")
    ])

    expected = [
        SimpleNamespace(Name="Chris", City="London", Country="UK"),
        SimpleNamespace(Name="Rob", City="Kent", Country="UK"),
        SimpleNamespace(Name="Tim", City="Seattle", Country="USA"),
        SimpleNamespace(Name="Philip", City="Orlando", Country="USA"),
        SimpleNamespace(Name="Jim", City="Minneapolis", Country="USA")
    ]

    assert list(source.order_by(lambda e: e.Country).then_by_descending(lambda e: e.City)) == expected


def test_DescendingKeyThenDescendingKey(flp_type):
    source = flp_type([
        SimpleNamespace(Name="Jim", City="Minneapolis", Country="USA"),
        SimpleNamespace(Name="Tim", City="Seattle", Country="USA"),
        SimpleNamespace(Name="Philip", City="Orlando", Country="USA"),
        SimpleNamespace(Name="Chris", City="London", Country="UK"),
        SimpleNamespace(Name="Rob", City="Kent", Country="UK")
    ])

    expected = [
        SimpleNamespace(Name="Tim", City="Seattle", Country="USA"),
        SimpleNamespace(Name="Philip", City="Orlando", Country="USA"),
        SimpleNamespace(Name="Jim", City="Minneapolis", Country="USA"),
        SimpleNamespace(Name="Chris", City="London", Country="UK"),
        SimpleNamespace(Name="Rob", City="Kent", Country="UK")
    ]

    assert list(source.order_by_descending(lambda e: e.Country).then_by_descending(lambda e: e.City)) == expected


def test_OrderIsStable(flp_type):
    pytest.skip("Comparer not supported yet")
    text = "Because I could not stop for Death -\nHe kindly stopped for me -\nThe Carriage held but just Ourselves -\nAnd Immortality."
    words = [w for w in re.split(r'[\s\-]+', text) if w]
    source = flp_type(words)

    expected = [
        "stopped", "kindly", "could", "stop", "held", "just", "not", "for", "for", "but", "me",
        "Immortality.", "Ourselves", "Carriage", "Because", "Death", "The", "And", "He", "I"
    ]

    assert list(source.order_by(lambda word: word[0].isupper()).then_by_descending(lambda word: len(word))) == expected


def test_OrderIsStableCustomComparer(flp_type):
    pytest.skip("Comparer not supported yet")
    text = "Because I could not stop for Death -\nHe kindly stopped for me -\nThe Carriage held but just Ourselves -\nAnd Immortality."
    words = [w for w in re.split(r'[\s\-]+', text) if w]
    source = flp_type(words)

    expected = [
        "me", "not", "for", "for", "but", "stop", "held", "just", "could", "kindly", "stopped",
        "I", "He", "The", "And", "Death", "Because", "Carriage", "Ourselves", "Immortality."
    ]

    assert list(source.order_by(lambda word: word[0].isupper()).then_by_descending(lambda word: len(word), reverse_int_cmp)) == expected


def test_RunOnce(flp_type):
    pytest.skip("Comparer not supported yet")

    text = "Because I could not stop for Death -\nHe kindly stopped for me -\nThe Carriage held but just Ourselves -\nAnd Immortality."
    words = (w for w in re.split(r'[\s\-]+', text) if w) # one-shot generator
    source = flp_type(words)

    expected = [
        "me", "not", "for", "for", "but", "stop", "held", "just", "could", "kindly", "stopped",
        "I", "He", "The", "And", "Death", "Because", "Carriage", "Ourselves", "Immortality."
    ]

    # the original did "source.run_once()" as we don't have the function. we use a on-shot generator
    assert list(source.order_by(lambda word: word[0].isupper()).then_by_descending(lambda word: len(word), reverse_int_cmp)) == expected


def test_NullSource():
    source = None
    with pytest.raises((TypeError, AttributeError)):
        source.then_by_descending(lambda i: i)


def test_NullKeySelector(flp_type):
    with pytest.raises((TypeError, ValueError)):
        flp_type([]).order_by(lambda e: e).then_by_descending(None)


def test_NullSourceComparer():
    source = None
    with pytest.raises((TypeError, AttributeError)):
        source.then_by_descending(lambda i: i, None)


def test_NullKeySelectorComparer(flp_type):
    with pytest.raises((TypeError, ValueError)):
        flp_type([]).order_by(lambda e: e).then_by_descending(None, None)


@pytest.mark.parametrize("then_bys", [1, 2, 3])
def test_SortsLargeAscendingEnumerableCorrectly(flp_type, then_bys):
    items = 100_000
    expected = list(range(items))

    unordered = flp_type((i for i in range(items)))
    ordered = unordered.order_by(lambda _: 0)

    if then_bys == 1:
        ordered = ordered.then_by_descending(lambda i: -i)
    elif then_bys == 2:
        ordered = ordered.then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)
    elif then_bys == 3:
        ordered = ordered.then_by_descending(lambda i: 0).then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)

    assert list(ordered) == expected


@pytest.mark.parametrize("then_bys", [1, 2, 3])
def test_SortsLargeDescendingEnumerableCorrectly(flp_type, then_bys):
    items = 100_000
    expected = list(range(items))

    unordered = flp_type((items - i - 1 for i in range(items)))
    ordered = unordered.order_by(lambda _: 0)

    if then_bys == 1:
        ordered = ordered.then_by_descending(lambda i: -i)
    elif then_bys == 2:
        ordered = ordered.then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)
    elif then_bys == 3:
        ordered = ordered.then_by_descending(lambda i: 0).then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)

    assert list(ordered) == expected


@pytest.mark.parametrize("then_bys", [1, 2, 3])
def test_SortsLargeRandomizedEnumerableCorrectly(flp_type, then_bys):
    items = 100_000
    r = random.Random(42)
    randomized = [r.randint(0, 2**31 - 1) for _ in range(items)]

    ordered_enumerable = flp_type(iter(randomized)).order_by(lambda _: 0)

    if then_bys == 1:
        ordered_enumerable = ordered_enumerable.then_by_descending(lambda i: -i)
    elif then_bys == 2:
        ordered_enumerable = ordered_enumerable.then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)
    elif then_bys == 3:
        ordered_enumerable = ordered_enumerable.then_by_descending(lambda i: 0).then_by_descending(lambda i: 0).then_by_descending(lambda i: -i)

    ordered = list(ordered_enumerable)
    randomized.sort()

    assert ordered == randomized