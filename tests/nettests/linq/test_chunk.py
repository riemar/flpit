"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ChunkTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ChunkTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper mapping:
    int[] chunk                     -> FlpList[int] (compared as list)
    Enumerable.Empty<int>()         -> flp_type([])
    FastInfiniteEnumerator<int>     -> _FastInfiniteEnumerator (iterable that is its own iterator)
    CreateSources(array)            -> _create_sources(flp_type, array) (see IdentityTransforms below)
    IEnumerator.MoveNext()/Current  -> next(iterator)
    Assert.False(MoveNext())        -> pytest.raises(StopIteration)
    List<int>                       -> flp.lst([...]) (the live, mutable container)
    List<int>.Add / .Remove         -> FlpList.add / FlpList.remove
"""
from collections import deque
from collections.abc import Collection, Iterator, Sequence

import pytest

from flpit import flp, ArgumentOutOfRangeError, SourceNoneError

INT_MAX = 2147483647


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class _FastInfiniteEnumerator(Iterator):
    """Mirrors FastInfiniteEnumerator<T>: endless sequence of default(T), enumerable and enumerator at once."""

    def __iter__(self):
        return self

    def __next__(self):
        return 0  # default(int)


class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


class _ReadOnlyCollection(Sequence):
    """ReadOnlyCollection<T>: an IList<T> that is neither List<T> nor T[]."""

    def __init__(self, source):
        self._items = tuple(source)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]


class _TestReadOnlyCollection(Collection):
    """TestReadOnlyCollection<T>: sized + iterable, but not indexable."""

    def __init__(self, source):
        self._items = tuple(source)

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, item):
        return item in self._items


def _identity_transforms(flp_type):
    """EnumerableTests.IdentityTransforms<int>(): the same data in many container shapes."""
    return [
        lambda e: flp_type(list(e)),                       # e => e (int[] original)
        lambda e: flp_type(tuple(e)),                      # e.ToArray()
        lambda e: flp_type(list(e)),                       # e.ToList()
        lambda e: flp_type(_ReadOnlyCollection(e)),        # ReadOnlyCollection<T>
        lambda e: flp_type(deque(e)),                      # TestCollection<T> (ICollection<T> that's not IList<T>)
        lambda e: flp_type(_TestReadOnlyCollection(e)),    # TestReadOnlyCollection<T>
        lambda e: flp_type(_ForceNotCollection(e)),        # ForceNotCollection(e)
    ]


def _create_sources(flp_type, source):
    """EnumerableTests.CreateSources<int>(source)."""
    return [transform(source) for transform in _identity_transforms(flp_type)]


# ---------------------------------------------------------------------------
# ChunkTests
# ---------------------------------------------------------------------------

def test_Empty(flp_type):
    assert list(flp_type([]).chunk(4)) == []


def test_ThrowsOnNullSource(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).chunk(5)


@pytest.mark.parametrize("size", [0, -1])
def test_ThrowsWhenSizeIsNonPositive(flp_type, size):
    source = [1]
    # .NET throws ArgumentOutOfRangeException("size") eagerly, without enumerating.
    # EXPECTED FAIL: chunk() raises a plain ValueError for size <= 0 instead of
    # ArgumentOutOfRangeError (which derives from ArgumentError/TypeError, not ValueError).
    with pytest.raises(ArgumentOutOfRangeError):
        flp_type(source).chunk(size)


def test_ChunkSourceLazily():
    # flp.it only: FlpList(...) would materialize the infinite source.
    chunks = iter(flp.it(_FastInfiniteEnumerator()).chunk(5))
    assert list(next(chunks)) == [0, 0, 0, 0, 0]
    assert next(chunks) is not None  # Assert.True(chunks.MoveNext())


@pytest.mark.parametrize("array", [[9999, 0, 888, -1, 66, -777, 1, 2, -12345]])
def test_ChunkSourceRepeatCalls(flp_type, array):
    for source in _create_sources(flp_type, array):
        assert list(map(list, source.chunk(3))) == list(map(list, source.chunk(3)))


@pytest.mark.parametrize("array", [[9999, 0, 888, -1, 66, -777, 1, 2, -12345]])
def test_ChunkSourceEvenly(flp_type, array):
    for source in _create_sources(flp_type, array):
        chunks = iter(source.chunk(3))
        assert list(next(chunks)) == [9999, 0, 888]
        assert list(next(chunks)) == [-1, 66, -777]
        assert list(next(chunks)) == [1, 2, -12345]
        with pytest.raises(StopIteration):
            next(chunks)


@pytest.mark.parametrize("array", [[9999, 0, 888, -1, 66, -777, 1, 2]])
def test_ChunkSourceUnevenly(flp_type, array):
    for source in _create_sources(flp_type, array):
        chunks = iter(source.chunk(3))
        assert list(next(chunks)) == [9999, 0, 888]
        assert list(next(chunks)) == [-1, 66, -777]
        assert list(next(chunks)) == [1, 2]
        with pytest.raises(StopIteration):
            next(chunks)


@pytest.mark.parametrize("array", [[9999, 0]])
def test_ChunkSourceSmallerThanMaxSize(flp_type, array):
    for source in _create_sources(flp_type, array):
        chunks = iter(source.chunk(3))
        assert list(next(chunks)) == [9999, 0]
        with pytest.raises(StopIteration):
            next(chunks)


@pytest.mark.parametrize("array", [[]])
def test_EmptySourceYieldsNoChunks(flp_type, array):
    for source in _create_sources(flp_type, array):
        chunks = iter(source.chunk(3))
        with pytest.raises(StopIteration):
            next(chunks)


def test_RemovingFromSourceBeforeIterating():
    # .NET List<int> -> flp.lst(...): the query is built over the live container.
    lst = flp.lst([9999, 0, 888, -1, 66, -777, 1, 2, -12345])
    chunks = lst.chunk(3)
    lst.remove(66)

    assert list(map(list, chunks)) == [[9999, 0, 888], [-1, -777, 1], [2, -12345]]


def test_AddingToSourceBeforeIterating():
    lst = flp.lst([9999, 0, 888, -1, 66, -777, 1, 2, -12345])
    chunks = lst.chunk(3)
    lst.add(10)  # List<T>.Add; FlpList.append() is the non-mutating LINQ Append

    assert list(map(list, chunks)) == [[9999, 0, 888], [-1, 66, -777], [1, 2, -12345], [10]]


# reproduces https://github.com/dotnet/runtime/issues/67132
def test_DoesNotPrematurelyAllocateHugeArray():
    chunks = list(flp.range(0, 10).chunk(INT_MAX))

    assert list(map(list, chunks)) == [list(range(0, 10))]
