"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SelectManyTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SelectManyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's StringWithIntArray is mapped to types.SimpleNamespace(name=..., total=...).
.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
TestEnumerable<int> (a lazy, non-collection IEnumerable) is mapped to _NotCollection.

Not portable / not implemented (skipped with a reason, as elsewhere in nettests):
    * SelectMany((value, index) => ...) overloads: select_many() has no index overload yet.
    * SelectMany(collectionSelector, resultSelector): select_many() has no result
      selector overload yet.
    * Int32 overflow (IndexOverflow, ThrowOverflowExceptionOnConstituentLargeCounts):
      Python int can't overflow.
"""

import random
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from conftest import create_sources
from flpit import (
    flp,
    SelectorNoneError,
    SourceNoneError,
)


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


class _NotCollection:
    """Re-enumerable iterable without __len__ / __getitem__ (not a collection)."""

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        for item in self._items:
            yield item


class _GeneratorFactoryIterable:
    """Iterable that starts a fresh generator on every iteration (like DelegateIterator)."""

    def __init__(self, factory):
        self._factory = factory

    def __iter__(self):
        return self._factory()


_MISSING = object()


def _is_enumerator_that_enumerates(iterator):
    """.NET: `iterator as IEnumerator<int>` followed by MoveNext()."""
    if not isinstance(iterator, Iterator):
        return False
    return next(iterator, _MISSING) is not _MISSING


def _s(name, total):
    """StringWithIntArray { name, total }"""
    return SimpleNamespace(name=name, total=total)


def _source():
    return [
        _s("Prakash", [1, 2, 3, 4]),
        _s("Bob", [5, 6]),
        _s("Chris", []),
        _s(None, [8, 9]),
        _s("Prakash", [-10, 100]),
    ]


def _all_empty_source():
    return [
        _s("Prakash", []),
        _s("Bob", []),
        _s("Chris", []),
        _s(None, []),
        _s("Prakash", []),
    ]


def test_EmptySource():
    assert list(flp.it([]).select_many(lambda e: e.total)) == []


@pytest.mark.skip("index not implemented yet")
def test_EmptySourceIndexedSelector():
    assert list(flp.it([]).select_many(lambda e, i: e.total)) == []


@pytest.mark.skip("result selector not implemented yet")
def test_EmptySourceResultSelector():
    assert list(flp.it([]).select_many(lambda e: e.total, lambda e, f: str(f))) == []


@pytest.mark.skip("index not implemented yet")
def test_EmptySourceResultSelectorIndexedSelector():
    assert list(flp.it([]).select_many(lambda e, i: e.total, lambda e, f: str(f))) == []


def test_SingleElement():
    expected = [90, 55, None, 43, 89]
    source = [_s("Prakash", expected)]

    assert expected == list(flp.it(source).select_many(lambda e: e.total))


def test_NonEmptySelectingEmpty():
    source = _all_empty_source()

    assert list(flp.it(source).select_many(lambda e: e.total)) == []


@pytest.mark.skip("index not implemented yet")
def test_NonEmptySelectingEmptyIndexedSelector():
    source = _all_empty_source()

    assert list(flp.it(source).select_many(lambda e, i: e.total)) == []


@pytest.mark.skip("result selector not implemented yet")
def test_NonEmptySelectingEmptyWithResultSelector():
    source = _all_empty_source()

    assert list(flp.it(source).select_many(lambda e: e.total, lambda e, f: str(f))) == []


@pytest.mark.skip("index not implemented yet")
def test_NonEmptySelectingEmptyIndexedSelectorWithResultSelector():
    source = _all_empty_source()

    assert list(flp.it(source).select_many(lambda e, i: e.total, lambda e, f: str(f))) == []


def test_ResultsSelected():
    source = _source()
    expected = [1, 2, 3, 4, 5, 6, 8, 9, -10, 100]

    assert expected == list(flp.it(source).select_many(lambda e: e.total))


def test_RunOnce():
    source = _source()
    expected = [1, 2, 3, 4, 5, 6, 8, 9, -10, 100]

    assert expected == list(flp.it(_run_once(source)).select_many(lambda e: _run_once(e.total)))


@pytest.mark.skip("index not implemented yet")
def test_SourceEmptyIndexUsed():
    assert list(flp.it([]).select_many(lambda e, index: e.total)) == []


@pytest.mark.skip("index not implemented yet")
def test_SingleElementIndexUsed():
    expected = [90, 55, None, 43, 89]
    source = [_s("Prakash", expected)]

    assert expected == list(flp.it(source).select_many(lambda e, index: e.total))


@pytest.mark.skip("index not implemented yet")
def test_NonEmptySelectingEmptyIndexUsed():
    source = _all_empty_source()

    assert list(flp.it(source).select_many(lambda e, index: e.total)) == []


@pytest.mark.skip("index not implemented yet")
def test_ResultsSelectedIndexUsed():
    source = _source()
    expected = [1, 2, 3, 4, 5, 6, 8, 9, -10, 100]

    assert expected == list(flp.it(source).select_many(lambda e, index: e.total))


@pytest.mark.skip("index not implemented yet")
def test_IndexCausingFirstToBeSelected():
    source = _source()

    assert source[0].total == list(flp.it(source).select_many(lambda e, i: e.total if i == 0 else []))


@pytest.mark.skip("index not implemented yet")
def test_IndexCausingLastToBeSelected():
    source = _source()
    source[4] = _s("Robert", [-10, 100])

    assert source[-1].total == list(flp.it(source).select_many(lambda e, i: e.total if i == 4 else []))


@pytest.mark.skip("Python int can't overflow")
def test_IndexOverflow():
    # .NET (stress mode only): the SelectMany index overflows int.MaxValue.
    pass


@pytest.mark.skip("result selector not implemented yet")
def test_ResultSelector():
    source = _source()
    expected = ["1", "2", "3", "4", "5", "6", "8", "9", "-10", "100"]

    assert expected == list(flp.it(source).select_many(lambda e: e.total, lambda e, f: str(f)))


@pytest.mark.skip("result selector not implemented yet")
def test_NullResultSelector():
    # A dedicated ResultSelectorNoneError may be preferable to SelectorNoneError.
    with pytest.raises(SelectorNoneError):
        flp.it([]).select_many(lambda e: e.total, None)


@pytest.mark.skip("index not implemented yet")
def test_NullResultSelectorIndexedSelector():
    with pytest.raises(SelectorNoneError):
        flp.it([]).select_many(lambda e, i: e.total, None)


@pytest.mark.skip("result selector not implemented yet")
def test_NullSourceWithResultSelector(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).select_many(lambda e: e.total, lambda e, f: str(f))


@pytest.mark.skip("result selector not implemented yet")
def test_NullCollectionSelector():
    with pytest.raises(SelectorNoneError):
        flp.it([]).select_many(None, lambda e, f: str(f))


@pytest.mark.skip("index not implemented yet")
def test_NullIndexedCollectionSelector():
    with pytest.raises(SelectorNoneError):
        flp.it([]).select_many(None, lambda e, f: str(f))


def test_NullSource(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before select_many() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).select_many(lambda e: e.total)


@pytest.mark.skip("index not implemented yet")
def test_NullSourceIndexedSelector(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).select_many(lambda e, i: e.total)


@pytest.mark.skip("index not implemented yet")
def test_NullSourceIndexedSelectorWithResultSelector(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).select_many(lambda e, i: e.total, lambda e, f: str(f))


def test_NullSelector(flp_type):
    # Will fail: select_many() does not validate its selector eagerly. SelectorNoneError
    # exists but is not raised here, so a None selector only fails lazily during
    # enumeration with TypeError: 'NoneType' object is not callable.
    with pytest.raises(SelectorNoneError):
        flp_type([]).select_many(None)


@pytest.mark.skip("index not implemented yet")
def test_NullIndexedSelector(flp_type):
    # Selector is the (value, index) overload; without it this would be
    # indistinguishable from the non-indexed test.
    with pytest.raises(SelectorNoneError):
        flp_type([]).select_many(None)


@pytest.mark.skip("index not implemented yet")
def test_IndexCausingFirstToBeSelectedWithResultSelector():
    source = _source()
    expected = ["1", "2", "3", "4"]

    assert expected == list(
        flp.it(source).select_many(lambda e, i: e.total if i == 0 else [], lambda e, f: str(f))
    )


@pytest.mark.skip("index not implemented yet")
def test_IndexCausingLastToBeSelectedWithResultSelector():
    source = _source()
    source[4] = _s("Robert", [-10, 100])
    expected = ["-10", "100"]

    assert expected == list(
        flp.it(source).select_many(lambda e, i: e.total if i == 4 else [], lambda e, f: str(f))
    )


# .NET: `iterator as IEnumerator<int>` followed by MoveNext(). In Python the
# equivalent is "if the query object is itself an Iterator, calling next() on it
# must not hand out elements" ("Don't insist on this behaviour, but check it's
# correct if it happens").

def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).select_many(lambda i: [])

    assert not _is_enumerator_that_enumerates(iterator)


@pytest.mark.skip("index not implemented yet")
def test_ForcedToEnumeratorDoesntEnumerateIndexed():
    iterator = flp.it(range(0, 3)).select_many(lambda e, i: [])

    assert not _is_enumerator_that_enumerates(iterator)


@pytest.mark.skip("result selector not implemented yet")
def test_ForcedToEnumeratorDoesntEnumerateResultSel():
    iterator = flp.it(range(0, 3)).select_many(lambda i: [], lambda e, i: e)

    assert not _is_enumerator_that_enumerates(iterator)


@pytest.mark.skip("index not implemented yet")
def test_ForcedToEnumeratorDoesntEnumerateIndexedResultSel():
    iterator = flp.it(range(0, 3)).select_many(lambda e, i: [], lambda e, i: e)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ParameterizedTests(flp_type):
    for i in range(1, 21):
        for source in create_sources(flp_type)(range(1, i + 1)):
            selector = lambda n: flp.range(i, i + n)  # Enumerable.Range(i, n)

            aggregated = source.select(lambda x: selector(x)).aggregate(
                lambda l, r: l.concat(r)
            )
            expected = list(aggregated)

            actual = source.select_many(selector)

            assert expected == list(actual)
            assert len(expected) == actual.count()  # SelectMany may employ an optimized Count implementation.
            assert expected == list(actual)  # ToArray
            assert expected == list(actual.to_list())


@pytest.mark.parametrize("sub_length", [1, 2, 3, 5, 8, 13, 21, 34])
@pytest.mark.parametrize("source_length", [1, 2, 3, 5, 8, 13, 21, 34])
def test_DisposeAfterEnumeration(source_length, sub_length):
    source_state = 0
    sub_index = 0  # Index within the arrays the sub-collection is supposed to be at.
    sub_state = [0] * source_length
    source_disposed = False
    sub_collection_disposed = [False] * source_length

    def source_iterator():
        nonlocal source_state, source_disposed
        try:
            while True:
                source_state += 1
                if not source_state <= source_length:
                    return
                yield 0
        finally:
            source_disposed = True

    def sub_collection_iterator():
        nonlocal sub_index
        try:
            while True:
                sub_state[sub_index] += 1  # Return True `sub_length` times.
                if not sub_state[sub_index] <= sub_length:
                    return
                yield sub_state[sub_index]
        finally:
            # Record that disposal happened, and move on to the next index.
            sub_collection_disposed[sub_index] = True
            sub_index += 1

    source = _GeneratorFactoryIterable(source_iterator)
    sub_collection = _GeneratorFactoryIterable(sub_collection_iterator)

    iterator = flp.it(source).select_many(lambda _: sub_collection)

    index = 0  # How much have we gone into the iterator?
    e = iter(iterator)
    for item in e:
        assert sub_state[sub_index] == item  # Verify Current.
        assert index // sub_length == sub_index
        assert source_disposed is False  # Not yet.

        # This represents whether the sub-collection we're iterating through right now
        # has been disposed. Also not yet.
        assert sub_collection_disposed[sub_index] is False

        # However, all of the sub-collections before us should have been disposed.
        # Their indices should also be maxed out.
        assert all(s == sub_length + 1 for s in sub_state[:sub_index])
        assert all(sub_collection_disposed[:sub_index])

        index += 1

    assert source_disposed is True
    assert sub_index == source_length
    assert all(s == sub_length + 1 for s in sub_state)
    assert all(sub_collection_disposed)

    # .NET additionally asserts enumerator.Current == default(int) before and after
    # MoveNext() on the disposed enumerator; Python iterators have no Current.
    with pytest.raises(StopIteration):
        next(e)


@pytest.mark.skip("Python int can't overflow")
def test_ThrowOverflowExceptionOnConstituentLargeCounts():
    # .NET (speed-optimized builds only): Count() of huge constituents throws
    # OverflowException. Running this in Python would try to enumerate ~2**31 items.
    pass


def _to_array_data_sources():
    """Lazy non-collections (TestEnumerable) interleaved with plain lists."""
    return [
        # Marker at the end
        [_NotCollection([0]), _NotCollection([1]), _NotCollection([2]), [3]],
        # Marker at beginning
        [[0], _NotCollection([1]), _NotCollection([2]), _NotCollection([3])],
        # Marker in middle
        [_NotCollection([0]), [1], _NotCollection([2])],
        # Non-marker in middle
        [[0], _NotCollection([1]), [2]],
        # Big arrays (marker in middle)
        [
            _NotCollection(list(range(0, 100))),
            list(range(100, 200)),
            _NotCollection(list(range(200, 300))),
        ],
        # Big arrays (non-marker in middle)
        [
            list(range(0, 100)),
            _NotCollection(list(range(100, 200))),
            list(range(200, 300)),
        ],
        # Interleaved (first marker)
        [[0], _NotCollection([1]), [2], _NotCollection([3]), [4]],
        # Interleaved (first non-marker)
        [_NotCollection([0]), [1], _NotCollection([2]), [3], _NotCollection([4])],
    ]


@pytest.mark.parametrize(
    "data_index",
    range(8),
    ids=[
        "marker_at_end",
        "marker_at_beginning",
        "marker_in_middle",
        "non_marker_in_middle",
        "big_arrays_marker_in_middle",
        "big_arrays_non_marker_in_middle",
        "interleaved_first_marker",
        "interleaved_first_non_marker",
    ],
)
def test_CollectionInterleavedWithLazyEnumerables_ToArray(data_index):
    arrays = _to_array_data_sources()[data_index]

    # See https://github.com/dotnet/runtime/issues/23389
    results = list(flp.it(arrays).select_many(lambda ar: ar))

    for i in range(len(results)):
        assert results[i] == i


@pytest.mark.parametrize("count", [10])
def test_EvaluateSelectorOncePerItem(count):
    times_called_map = [0] * count
    source = flp.it(range(0, 10))

    def selector(index):
        times_called_map[index] += 1
        return [index]

    iterator = source.select_many(selector)

    # Iteration
    for index in iterator:
        assert times_called_map[: index + 1] == [1] * (index + 1)
        assert times_called_map[index + 1:] == [0] * (len(times_called_map) - index - 1)

    times_called_map[:] = [0] * count

    # ToArray
    list(iterator)
    assert times_called_map == [1] * len(times_called_map)

    times_called_map[:] = [0] * count

    # ToList
    iterator.to_list()
    assert times_called_map == [1] * len(times_called_map)

    times_called_map[:] = [0] * count

    # ToHashSet
    set(iterator)
    assert times_called_map == [1] * len(times_called_map)