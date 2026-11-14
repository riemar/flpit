"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ReverseTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ReverseTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper / language mapping:
    Enumerable.Reverse(source)       -> source.reverse()   (the deferred LINQ Reverse operator)
    IEnumerable<T> source            -> flp_type(list)     (FlpIt and FlpList)
    default(T)                       -> 0 for int data, None for string data (passed as test parameter)
    ToArray()                        -> list(...)          (flpit has no ToArray)
    ElementAtOrDefault(i)            -> _element_at_or_default(...) (flpit has no such operator)
    RunOnce()                        -> flp.it(run_once(...)) (conftest `run_once`)
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    Assert.Equal(actual, actual)     -> list(actual) == list(actual) (repeat enumeration)

Known reasons for failures in this file:
    * FlpIt has no reverse() at all.
    * FlpList.reverse() is the in-place List<T>.Reverse(): it mutates and returns None instead of
      returning a deferred, reversed sequence like Enumerable.Reverse.
"""
from collections.abc import Iterator

import pytest

from flpit import flp, SourceNoneError


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


def _element_at_or_default(source, index, default):
    """Enumerable.ElementAtOrDefault: flpit has no such operator, so emulate it via element_at."""
    try:
        return source.element_at(index)
    except Exception:
        return default


_INTEGERS = [
    [],  # No elements.
    [1],  # One element.
    [9999, 0, 888, -1, 66, -777, 1, 2, -12345],  # Distinct elements.
    [-10, 0, 5, 0, 9, 100, 9],  # Some repeating elements.
]

# (collection, default(T)): the int collections, then the same collections as strings.
_REVERSE_DATA = [(c, 0) for c in _INTEGERS] + [([str(i) for i in c], None) for c in _INTEGERS]


# ---------------------------------------------------------------------------
# ReverseTests
# ---------------------------------------------------------------------------

def test_InvalidArguments(flp_type):
    # .NET: ArgumentNullException("source") for IEnumerable<string> and string[]; flp: constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).reverse()
    with pytest.raises(SourceNoneError):
        flp_type(None).reverse()


def _assert_reverse(source, expected, default):
    # EXPECTED FAIL: FlpIt has no reverse(); FlpList.reverse() reverses in place and returns None,
    # so `actual` is not an enumerable sequence.
    actual = source.reverse()

    assert expected == list(actual)
    assert len(expected) == actual.count()  # Count may be optimized.
    assert expected == list(actual)  # ToArray()
    assert expected == list(actual.to_list())

    assert (expected[0] if expected else default) == actual.first_or_default(default)
    assert (expected[-1] if expected else default) == actual.last_or_default(default)

    for i in range(len(expected)):
        assert expected[i] == actual.element_at(i)

        assert expected[i:] == list(actual.skip(i))
        assert expected[:i] == list(actual.take(i))

    assert default == _element_at_or_default(actual, -1, default)
    assert default == _element_at_or_default(actual, len(expected), default)

    assert expected == list(actual.select(lambda _: _))
    assert expected == list(actual.where(lambda _: True))

    assert list(actual) == list(actual)  # Repeat the enumeration against itself.


@pytest.mark.parametrize("collection, default", _REVERSE_DATA)
def test_Reverse(collection, default):
    source = flp.it(collection)
    expected = list(collection)
    expected.reverse()

    _assert_reverse(source, expected, default)


@pytest.mark.parametrize("collection, default", _REVERSE_DATA)
def test_ReverseArray( collection, default):
    source = flp.it(collection)
    expected = list(collection)
    expected.reverse()

    _assert_reverse(flp.it(source), expected, default)  # source.ToArray().Reverse()


@pytest.mark.parametrize("collection, default", _REVERSE_DATA)
def test_RunOnce(flp_type, run_once, collection, default):
    expected = list(collection)
    expected.reverse()

    # EXPECTED FAIL: FlpIt has no reverse(); (FlpIt only, run_once is wrapped in flp.it).
    actual = flp.it(run_once(collection)).reverse()

    assert expected == list(actual)


def test_ForcedToEnumeratorDoesntEnumerate():
    # EXPECTED FAIL: FlpIt has no reverse().
    iterator = flp.it(_ForceNotCollection(range(0, 3))).reverse()
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)
