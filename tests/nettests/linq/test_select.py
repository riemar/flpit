"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq SelectTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SelectTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's source-type variants are mapped to Python sources as follows:
    Array                -> flp.it(list)
    List                 -> flp.lst(list)            (FlpList)
    IReadOnlyCollection  -> flp.it(tuple)
    ICollection          -> flp.it(collections.deque) (.NET: LinkedList)
    IList (AsReadOnly)   -> flp.it(tuple)
    IEnumerable          -> flp.it(range) or flp.it(re-enumerable non-collection)

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).
first_or_default() takes a mandatory default as its first argument; .NET's
default(int) is passed explicitly as 0.

Not portable / not implemented (skipped with a reason, as elsewhere in nettests):
    * Select((value, index) => ...) overloads: select() has no index overload yet.
    * IEnumerator.Current / Reset() and enumerators that resume after throwing:
      Python iterators have no Current, and a generator is finished once it raises.
    * ElementAtOrDefault / LastOrDefault: not implemented yet.
"""

import contextlib
import random
from collections import deque
from collections.abc import Iterator


import pytest

from flpit import (
    flp,
    FlpIt,
    FlpList,
    ArgumentOutOfRangeError,
    EmptySequenceError,
    InvalidOperationError,
    SelectorNoneError,
    SourceNoneError,
)
from flpit.task import Task


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


class _DisposeTrackingList(list):
    """Counts how often an iteration over this list is finished/closed."""

    def __init__(self, items):
        super().__init__(items)
        self.dispose_calls = 0

    def __iter__(self):
        try:
            yield from list.__iter__(self)
        finally:
            self.dispose_calls += 1


class _ThrowsOnCurrent:
    """.NET: Current throws InvalidOperationException for the first element.
    A Python iterator has no Current, so the failure surfaces from next()."""

    def __iter__(self):
        current = 0
        while True:
            current += 1
            if current == 1:
                raise InvalidOperationError()
            yield current


class _ThrowsOnMoveNext:
    """.NET: the first MoveNext throws InvalidOperationException."""

    def __iter__(self):
        raise_first = True
        current = 0
        while True:
            if raise_first:
                raise_first = False
                raise InvalidOperationError()
            current += 1
            yield current


class _ThrowsOnGetEnumerator:
    """.NET: the first GetEnumerator call throws InvalidOperationException."""

    def __init__(self):
        self._calls = 0

    def __iter__(self):
        self._calls += 1
        if self._calls == 1:
            raise InvalidOperationError()
        return iter(range(1, 6))


_MISSING = object()


def _is_enumerator_that_enumerates(iterator):
    """.NET: `iterator as IEnumerator<int>` followed by MoveNext()."""
    if not isinstance(iterator, Iterator):
        return False
    return next(iterator, _MISSING) is not _MISSING


def _wrap(source):
    """Query objects stay as they are; raw containers become FlpIt."""
    if isinstance(source, (FlpIt, FlpList)):
        return source
    return flp.it(source)


def test_SelectSideEffectsExecutedOnCount():
    i = 0

    def side_effect(x):
        nonlocal i
        result = i
        i += 1
        return result

    # If we made no promises about side effects, i could be 0, but in practice users have
    # taken a dependency on side effects executing on Count.
    count = flp.it(range(1, 11)).select(side_effect).count()
    assert count == 10
    assert i == 10

    i = 0
    count = flp.it(range(1, 11)).skip(5).select(side_effect).count()
    assert count == 5
    assert i == 5

    i = 0
    count = flp.it(range(1, 11)).take(5).select(side_effect).count()
    assert count == 5
    assert i == 5

    i = 0
    count = flp.it(range(1, 11)).skip(2).take(3).select(side_effect).count()
    assert count == 3
    assert i == 3


def test_SameResultsRepeatCallsStringQuery():
    q1 = flp.it(["Alen", "Felix", None, None, "X", "Have Space", "Clinton", ""]).select(lambda x1: x1)
    q2 = flp.it([55, 49, 9, -100, 24, 25, -1, 0]).select(lambda x2: x2)

    # from x3 in q1 from x4 in q2 select new { a1 = x3, a2 = x4 }
    # (select_many has no result-selector overload, so the projection is nested)
    q = q1.select_many(lambda x3: q2.select(lambda x4: (x3, x4)))

    assert list(q.select(lambda e: e[0])) == list(q.select(lambda e: e[0]))


def test_SingleElement():
    source = [{"name": "Prakash", "custID": 98088}]
    expected = ["Prakash"]

    assert expected == list(flp.it(source).select(lambda e: e["name"]))


def test_SelectProperty():
    source = [
        {"name": "Prakash", "custID": 98088},
        {"name": "Bob", "custID": 29099},
        {"name": "Chris", "custID": 39033},
        {"name": None, "custID": 30349},
        {"name": "Prakash", "custID": 39030},
    ]
    expected = ["Prakash", "Bob", "Chris", None, "Prakash"]

    assert expected == list(flp.it(source).select(lambda e: e["name"]))


def test_RunOnce():
    source = [
        {"name": "Prakash", "custID": 98088},
        {"name": "Bob", "custID": 29099},
        {"name": "Chris", "custID": 39033},
        {"name": None, "custID": 30349},
        {"name": "Prakash", "custID": 39030},
    ]
    expected = ["Prakash", "Bob", "Chris", None, "Prakash"]

    assert expected == list(flp.it(_run_once(source)).select(lambda e: e["name"]))
    assert expected == list(flp.it(_run_once(list(source))).select(lambda e: e["name"]))  # ToArray
    assert expected == list(flp.it(_run_once(list(source))).select(lambda e: e["name"]))  # ToList


@pytest.mark.skip("index not implemented yet")
def test_EmptyWithIndexedSelector():
    # select() has no index overload.
    assert list(flp.it([]).select(lambda s, i: len(s) + i)) == []


def test_EnumerateFromDifferentThread():
    selected = flp.it(range(0, 100)).where(lambda i: i > 3).select(lambda i: str(i))

    tasks = [Task.run(lambda: selected.to_list()) for _ in range(4)]
    Task.when_all(tasks).result()


@pytest.mark.skip("index not implemented yet")
def test_SingleElementIndexedSelector():
    # select() has no index overload.
    source = [{"name": "Prakash", "custID": 98088}]
    expected = ["Prakash"]

    assert expected == list(flp.it(source).select(lambda e, index: e["name"]))


@pytest.mark.skip("index not implemented yet")
def test_SelectPropertyPassingIndex():
    # select() has no index overload.
    source = [
        {"name": "Prakash", "custID": 98088},
        {"name": "Bob", "custID": 29099},
        {"name": "Chris", "custID": 39033},
        {"name": None, "custID": 30349},
        {"name": "Prakash", "custID": 39030},
    ]
    expected = ["Prakash", "Bob", "Chris", None, "Prakash"]

    assert expected == list(flp.it(source).select(lambda e, i: e["name"]))


@pytest.mark.skip("index not implemented yet")
def test_SelectPropertyUsingIndex():
    # select() has no index overload.
    source = [
        {"name": "Prakash", "custID": 98088},
        {"name": "Bob", "custID": 29099},
        {"name": "Chris", "custID": 39033},
    ]
    expected = ["Prakash", None, None]

    assert expected == list(flp.it(source).select(lambda e, i: e["name"] if i == 0 else None))


@pytest.mark.skip("index not implemented yet")
def test_SelectPropertyPassingIndexOnLast():
    # select() has no index overload.
    source = [
        {"name": "Prakash", "custID": 98088},
        {"name": "Bob", "custID": 29099},
        {"name": "Chris", "custID": 39033},
        {"name": "Robert", "custID": 39033},
        {"name": "Allen", "custID": 39033},
        {"name": "Chuck", "custID": 39033},
    ]
    expected = [None, None, None, None, None, "Chuck"]

    assert expected == list(flp.it(source).select(lambda e, i: e["name"] if i == 5 else None))


@pytest.mark.skip("Python int can't overflow")
def test_Overflow():
    # .NET (stress mode only): the Select index overflows int.MaxValue.
    pass


def test_Select_SourceIsNull_ArgumentNullExceptionThrown(flp_type):
    selector = lambda i: i + 1

    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before select() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).select(selector)


@pytest.mark.skip("index not implemented yet")
def test_Select_SelectorIsNull_ArgumentNullExceptionThrown_Indexed(flp_type):
    # Selector is the (value, index) overload; without it this would be
    # indistinguishable from the non-indexed test.
    source = flp_type(range(1, 11))

    with pytest.raises(SelectorNoneError):
        source.select(None)


@pytest.mark.skip("index not implemented yet")
def test_Select_SourceIsNull_ArgumentNullExceptionThrown_Indexed(flp_type):
    selector = lambda e, i: i + 1

    with pytest.raises(SourceNoneError):
        flp_type(None).select(selector)


def test_Select_SelectorIsNull_ArgumentNullExceptionThrown(flp_type):
    source = flp_type(range(1, 11))

    # Will fail: select() does not validate its selector eagerly. SelectorNoneError
    # exists but is not raised here, so a None selector only fails lazily during
    # enumeration with TypeError: 'NoneType' object is not callable.

    with pytest.raises(SelectorNoneError):
        source.select(None)


def test_Select_SourceIsAnArray_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it([func])

    query = source.select(lambda d: d())

    assert called == []


def test_Select_SourceIsAList_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.lst([func])

    query = source.select(lambda d: d())

    assert called == []


def test_Select_SourceIsIReadOnlyCollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it((func,))

    query = source.select(lambda d: d())

    assert called == []


def test_Select_SourceIsICollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it(deque([func]))

    query = source.select(lambda d: d())

    assert called == []


def test_Select_SourceIsIEnumerable_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it(_NotCollection([func]))

    query = source.select(lambda d: d())

    assert called == []


def test_SelectSelect_SourceIsAnArray_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it([func])

    query = source.select(lambda d: d).select(lambda d: d())

    assert called == []


def test_SelectSelect_SourceIsAList_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.lst([func])

    query = source.select(lambda d: d).select(lambda d: d())

    assert called == []


def test_SelectSelect_SourceIsIReadOnlyCollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it((func,))

    query = source.select(lambda d: d).select(lambda d: d())

    assert called == []


def test_SelectSelect_SourceIsICollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it(deque([func]))

    query = source.select(lambda d: d).select(lambda d: d())

    assert called == []


def test_SelectSelect_SourceIsIEnumerable_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return 1

    source = flp.it(_NotCollection([func]))

    query = source.select(lambda d: d).select(lambda d: d())

    assert called == []


def test_Select_SourceIsAnArray_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    selector = lambda i: i + 1

    query = flp.it(source).select(selector)

    index = 0
    for item in query:
        expected = selector(source[index])
        assert expected == item
        index += 1

    assert len(source) == index


def test_Select_SourceIsAList_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    selector = lambda i: i + 1

    query = source.select(selector)

    index = 0
    for item in query:
        expected = selector(source[index])
        assert expected == item
        index += 1

    assert len(source) == index


def test_Select_SourceIsIReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5)
    selector = lambda i: i + 1

    query = flp.it(source).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(index)
        assert expected == item

    assert len(source) == index


def test_Select_SourceIsICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    selector = lambda i: i + 1

    query = flp.it(source).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(index)
        assert expected == item

    assert len(source) == index


def test_Select_SourceIsIEnumerable_ReturnsExpectedValues():
    nb_of_items = 5
    source = range(1, 1 + nb_of_items)
    selector = lambda i: i + 1

    query = flp.it(source).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(index)
        assert expected == item

    assert nb_of_items == index


def test_SelectSelect_SourceIsAnArray_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    selector = lambda i: i + 1

    query = flp.it(source).select(selector).select(selector)

    index = 0
    for item in query:
        expected = selector(selector(source[index]))
        assert expected == item
        index += 1

    assert len(source) == index


def test_SelectSelect_SourceIsAList_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    selector = lambda i: i + 1

    query = source.select(selector).select(selector)

    index = 0
    for item in query:
        expected = selector(selector(source[index]))
        assert expected == item
        index += 1

    assert len(source) == index


def test_SelectSelect_SourceIsIReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5)
    selector = lambda i: i + 1

    query = flp.it(source).select(selector).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(selector(index))
        assert expected == item

    assert len(source) == index


def test_SelectSelect_SourceIsICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    selector = lambda i: i + 1

    query = flp.it(source).select(selector).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(selector(index))
        assert expected == item

    assert len(source) == index


def test_SelectSelect_SourceIsIEnumerable_ReturnsExpectedValues():
    nb_of_items = 5
    source = range(1, 1 + nb_of_items)
    selector = lambda i: i + 1

    query = flp.it(source).select(selector).select(selector)

    index = 0
    for item in query:
        index += 1
        expected = selector(selector(index))
        assert expected == item

    assert nb_of_items == index


@pytest.mark.skip("Python iterators have no Current property")
def test_Select_SourceIsAnArray_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Select_SourceIsAList_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Select_SourceIsIReadOnlyCollection_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Select_SourceIsICollection_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Select_SourceIsIEnumerable_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


def test_Select_SourceIsEmptyEnumerable_ReturnedCollectionHasNoElements():
    source = flp.it([])
    was_selector_called = False

    def selector(i):
        nonlocal was_selector_called
        was_selector_called = True
        return i + 1

    result = source.select(selector)

    had_items = False
    for item in result:
        had_items = True

    assert had_items is False
    assert was_selector_called is False


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------

def test_Select_ExceptionThrownFromSelector_ExceptionPropagatedToTheCaller():
    source = [1, 2, 3, 4, 5]

    def selector(i):
        raise InvalidOperationError()

    result = flp.it(source).select(selector)
    enumerator = iter(result)

    with pytest.raises(InvalidOperationError):
        next(enumerator)


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Select_ExceptionThrownFromSelector_IteratorCanBeUsedAfterExceptionIsCaught():
    # .NET: after the failed MoveNext the next MoveNext succeeds with Current == 3.
    pass


def test_Select_ExceptionThrownFromCurrentOfSourceIterator_ExceptionPropagatedToTheCaller():
    source = _ThrowsOnCurrent()
    selector = lambda i: i + 1

    result = flp.it(source).select(selector)
    enumerator = iter(result)

    with pytest.raises(InvalidOperationError):
        next(enumerator)


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Select_ExceptionThrownFromCurrentOfSourceIterator_IteratorCanBeUsedAfterExceptionIsCaught():
    # .NET: after the failed MoveNext the next MoveNext succeeds with Current == 3.
    pass


def test_Select_ExceptionThrownFromMoveNextOfSourceIterator_ExceptionPropagatedToTheCaller():
    source = _ThrowsOnMoveNext()
    selector = lambda i: i + 1

    result = flp.it(source).select(selector)
    enumerator = iter(result)

    with pytest.raises(InvalidOperationError):
        next(enumerator)


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Select_ExceptionThrownFromMoveNextOfSourceIterator_IteratorCanBeUsedAfterExceptionIsCaught():
    # .NET: after the failed MoveNext the next MoveNext succeeds with Current == 3.
    pass


def test_Select_ExceptionThrownFromGetEnumeratorOnSource_ExceptionPropagatedToTheCaller():
    source = _ThrowsOnGetEnumerator()
    selector = lambda i: i + 1

    result = flp.it(source).select(selector)
    enumerator = iter(result)

    with pytest.raises(InvalidOperationError):
        next(enumerator)


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Select_ExceptionThrownFromGetEnumeratorOnSource_CurrentIsSetToDefaultOfItemTypeAndIteratorCanBeUsedAfterExceptionIsCaught():
    # .NET: Current is default(string) after the failure and the next MoveNext
    # succeeds with Current == "1".
    pass


@pytest.mark.skip(".NET style mutation tracking needs custom implementation per source type and has a roughly 25% performance penalty")
def test_Select_SourceListGetsModifiedDuringIteration_ExceptionIsPropagated():
    source = flp.lst([1, 2, 3, 4, 5])
    selector = lambda i: i + 1

    result = source.select(selector)
    enumerator = iter(result)

    assert next(enumerator) == 2  # 1 + 1

    source.add(6)

    with pytest.raises(InvalidOperationError):
        next(enumerator)


def test_Select_GetEnumeratorCalledTwice_DifferentInstancesReturned():
    source = [1, 2, 3, 4, 5]
    query = flp.it(source).select(lambda i: i + 1)

    enumerator1 = iter(query)
    enumerator2 = iter(query)

    # .NET additionally asserts Assert.Same(query, enumerator1), i.e. that the
    # query object is its own first enumerator. That is a .NET implementation
    # detail with no Python counterpart.
    assert enumerator1 is not enumerator2


@pytest.mark.skip("Python iterators have no Reset()")
def test_Select_ResetCalledOnEnumerator_ThrowsException():
    # .NET expects NotSupportedException from enumerator.Reset().
    pass


# .NET: `iterator as IEnumerator<int>` followed by MoveNext(). In Python the
# equivalent is "if the query object is itself an Iterator, calling next() on it
# must not hand out elements" ("Don't insist on this behaviour, but check it's
# correct if it happens").

def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


@pytest.mark.skip("index not implemented yet")
def test_ForcedToEnumeratorDoesntEnumerateIndexed():
    # select() has no index overload.
    iterator = flp.it(range(0, 3)).select(lambda e, i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateArray():
    iterator = flp.it(list(range(0, 3))).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateList():
    iterator = flp.lst(list(range(0, 3))).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateIList():
    iterator = flp.it(tuple(range(0, 3))).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateIPartition():
    iterator = flp.it(tuple(range(0, 3))).select(lambda i: i).skip(1)

    assert not _is_enumerator_that_enumerates(iterator)


def test_Select_SourceIsArray_Count():
    source = [1, 2, 3, 4]

    assert len(source) == flp.it(source).select(lambda i: i * 2).count()


def test_Select_SourceIsAList_Count():
    source = flp.lst([1, 2, 3, 4])

    assert len(source) == source.select(lambda i: i * 2).count()


def test_Select_SourceIsAnIList_Count():
    source = (1, 2, 3, 4)

    assert len(source) == flp.it(source).select(lambda i: i * 2).count()


def test_Select_SourceIsArray_Skip():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    assert list(source.skip(2)) == [6, 8]
    assert list(source.skip(2).skip(-1)) == [6, 8]
    assert list(source.skip(1).skip(1)) == [6, 8]
    assert list(source.skip(-1)) == [2, 4, 6, 8]
    assert list(source.skip(4)) == []
    assert list(source.skip(20)) == []


def test_Select_SourceIsList_Skip():
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    assert list(source.skip(2)) == [6, 8]
    assert list(source.skip(2).skip(-1)) == [6, 8]
    assert list(source.skip(1).skip(1)) == [6, 8]
    assert list(source.skip(-1)) == [2, 4, 6, 8]
    assert list(source.skip(4)) == []
    assert list(source.skip(20)) == []


def test_Select_SourceIsIList_Skip():
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    assert list(source.skip(2)) == [6, 8]
    assert list(source.skip(2).skip(-1)) == [6, 8]
    assert list(source.skip(1).skip(1)) == [6, 8]
    assert list(source.skip(-1)) == [2, 4, 6, 8]
    assert list(source.skip(4)) == []
    assert list(source.skip(20)) == []


def test_Select_SourceIsArray_Take():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    assert list(source.take(2)) == [2, 4]
    assert list(source.take(3).take(2)) == [2, 4]
    assert list(source.take(-1)) == []
    assert list(source.take(4)) == [2, 4, 6, 8]
    assert list(source.take(40)) == [2, 4, 6, 8]
    assert list(source.take(1)) == [2]
    assert list(source.skip(1).take(1)) == [4]
    assert list(source.take(3).skip(2)) == [6]
    assert list(source.take(3).take(1)) == [2]


def test_Select_SourceIsList_Take():
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    assert list(source.take(2)) == [2, 4]
    assert list(source.take(3).take(2)) == [2, 4]
    assert list(source.take(-1)) == []
    assert list(source.take(4)) == [2, 4, 6, 8]
    assert list(source.take(40)) == [2, 4, 6, 8]
    assert list(source.take(1)) == [2]
    assert list(source.skip(1).take(1)) == [4]
    assert list(source.take(3).skip(2)) == [6]
    assert list(source.take(3).take(1)) == [2]


def test_Select_SourceIsIList_Take():
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    assert list(source.take(2)) == [2, 4]
    assert list(source.take(3).take(2)) == [2, 4]
    assert list(source.take(-1)) == []
    assert list(source.take(4)) == [2, 4, 6, 8]
    assert list(source.take(40)) == [2, 4, 6, 8]
    assert list(source.take(1)) == [2]
    assert list(source.skip(1).take(1)) == [4]
    assert list(source.take(3).skip(2)) == [6]
    assert list(source.take(3).take(1)) == [2]


def test_Select_SourceIsArray_ElementAt():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at(i) == i * 2 + 2

    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(-1)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(4)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(40)

    assert source.skip(1).element_at(1) == 6

    with pytest.raises(ArgumentOutOfRangeError):
        source.skip(2).element_at(9)


def test_Select_SourceIsList_ElementAt():
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at(i) == i * 2 + 2

    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(-1)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(4)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(40)

    assert source.skip(1).element_at(1) == 6

    with pytest.raises(ArgumentOutOfRangeError):
        source.skip(2).element_at(9)


def test_Select_SourceIsIList_ElementAt():
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at(i) == i * 2 + 2

    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(-1)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(4)
    with pytest.raises(ArgumentOutOfRangeError):
        source.element_at(40)

    assert source.skip(1).element_at(1) == 6

    with pytest.raises(ArgumentOutOfRangeError):
        source.skip(2).element_at(9)


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsArray_ElementAtOrDefault():
    # element_at_or_default does not exist yet; (default, index) is assumed,
    # following first_or_default(default, predicate).
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at_or_default(0, i) == i * 2 + 2

    assert source.element_at_or_default(0, -1) == 0
    assert source.element_at_or_default(0, 4) == 0
    assert source.element_at_or_default(0, 40) == 0
    assert source.skip(1).element_at_or_default(0, 1) == 6
    assert source.skip(2).element_at_or_default(0, 9) == 0


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsList_ElementAtOrDefault():
    # element_at_or_default does not exist yet; (default, index) is assumed,
    # following first_or_default(default, predicate).
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at_or_default(0, i) == i * 2 + 2

    assert source.element_at_or_default(0, -1) == 0
    assert source.element_at_or_default(0, 4) == 0
    assert source.element_at_or_default(0, 40) == 0
    assert source.skip(1).element_at_or_default(0, 1) == 6
    assert source.skip(2).element_at_or_default(0, 9) == 0


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsIList_ElementAtOrDefault():
    # element_at_or_default does not exist yet; (default, index) is assumed,
    # following first_or_default(default, predicate).
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    for i in range(4):
        assert source.element_at_or_default(0, i) == i * 2 + 2

    assert source.element_at_or_default(0, -1) == 0
    assert source.element_at_or_default(0, 4) == 0
    assert source.element_at_or_default(0, 40) == 0
    assert source.skip(1).element_at_or_default(0, 1) == 6
    assert source.skip(2).element_at_or_default(0, 9) == 0


def test_Select_SourceIsArray_First():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    assert source.first() == 2
    assert source.first_or_default(0) == 2
    assert source.skip(2).first() == 6
    assert source.skip(2).first_or_default(0) == 6

    with pytest.raises(EmptySequenceError):
        source.skip(4).first()
    with pytest.raises(EmptySequenceError):
        source.skip(14).first()

    assert source.skip(4).first_or_default(0) == 0
    assert source.skip(14).first_or_default(0) == 0

    empty = flp.it([]).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.first()

    assert empty.first_or_default(0) == 0


def test_Select_SourceIsList_First():
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    assert source.first() == 2
    assert source.first_or_default(0) == 2
    assert source.skip(2).first() == 6
    assert source.skip(2).first_or_default(0) == 6

    with pytest.raises(EmptySequenceError):
        source.skip(4).first()
    with pytest.raises(EmptySequenceError):
        source.skip(14).first()

    assert source.skip(4).first_or_default(0) == 0
    assert source.skip(14).first_or_default(0) == 0

    empty = flp.lst([]).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.first()

    assert empty.first_or_default(0) == 0


def test_Select_SourceIsIList_First():
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    assert source.first() == 2
    assert source.first_or_default(0) == 2
    assert source.skip(2).first() == 6
    assert source.skip(2).first_or_default(0) == 6

    with pytest.raises(EmptySequenceError):
        source.skip(4).first()
    with pytest.raises(EmptySequenceError):
        source.skip(14).first()

    assert source.skip(4).first_or_default(0) == 0
    assert source.skip(14).first_or_default(0) == 0

    empty = flp.it(()).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.first()

    assert empty.first_or_default(0) == 0


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsArray_Last():
    # last_or_default does not exist yet; the default is passed first, following
    # first_or_default(default, predicate).
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2)

    assert source.last() == 8
    assert source.last_or_default(0) == 8
    assert source.take(3).last() == 6
    assert source.take(3).last_or_default(0) == 6

    empty = flp.it([]).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.last()

    assert empty.last_or_default(0) == 0

    with pytest.raises(EmptySequenceError):
        empty.skip(1).last()

    assert empty.skip(1).last_or_default(0) == 0


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsList_Last():
    # last_or_default does not exist yet; the default is passed first, following
    # first_or_default(default, predicate).
    source = flp.lst([1, 2, 3, 4]).select(lambda i: i * 2)

    assert source.last() == 8
    assert source.last_or_default(0) == 8
    assert source.take(3).last() == 6
    assert source.take(3).last_or_default(0) == 6

    empty = flp.lst([]).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.last()

    assert empty.last_or_default(0) == 0

    with pytest.raises(EmptySequenceError):
        empty.skip(1).last()

    assert empty.skip(1).last_or_default(0) == 0


@pytest.mark.skip("not implemented yet")
def test_Select_SourceIsIList_Last():
    # last_or_default does not exist yet; the default is passed first, following
    # first_or_default(default, predicate).
    source = flp.it((1, 2, 3, 4)).select(lambda i: i * 2)

    assert source.last() == 8
    assert source.last_or_default(0) == 8
    assert source.take(3).last() == 6
    assert source.take(3).last_or_default(0) == 6

    empty = flp.it(()).select(lambda i: i * 2)

    with pytest.raises(EmptySequenceError):
        empty.last()

    assert empty.last_or_default(0) == 0

    with pytest.raises(EmptySequenceError):
        empty.skip(1).last()

    assert empty.skip(1).last_or_default(0) == 0


def test_Select_SourceIsArray_SkipRepeatCalls():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2).skip(1)

    assert list(source) == list(source)


def test_Select_SourceIsArraySkipSelect():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2).skip(1).select(lambda i: i + 1)

    assert list(source) == [5, 7, 9]


def test_Select_SourceIsArrayTakeTake():
    source = flp.it([1, 2, 3, 4]).select(lambda i: i * 2).take(2).take(1)

    assert list(source) == [2]
    assert list(source.take(10)) == [2]


def test_Select_SourceIsIPartitionToArray():
    assert list(flp.lst([]).order_by(lambda x: x).select(lambda i: i * 2)) == []
    assert list(flp.lst([1, 2, 3, 4]).order_by(lambda x: x).select(lambda i: i * 2)) == [2, 4, 6, 8]


def test_Select_SourceIsListSkipTakeCount():
    assert flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(3).count() == 3
    assert flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(9).count() == 4
    assert flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(2).count() == 2
    assert flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(8).count() == 0


def test_Select_SourceIsListSkipTakeToArray():
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(3)) == [2, 4, 6]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(9)) == [2, 4, 6, 8]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(2)) == [6, 8]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(8)) == []


def test_Select_SourceIsListSkipTakeToList():
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(3).to_list()) == [2, 4, 6]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).take(9).to_list()) == [2, 4, 6, 8]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(2).to_list()) == [6, 8]
    assert list(flp.lst([1, 2, 3, 4]).select(lambda i: i * 2).skip(8).to_list()) == []


def test_Select_SourceIsIPartitionToList():
    assert list(flp.lst([]).order_by(lambda x: x).select(lambda i: i * 2).to_list()) == []
    assert list(flp.lst([1, 2, 3, 4]).order_by(lambda x: x).select(lambda i: i * 2).to_list()) == [2, 4, 6, 8]


@pytest.mark.parametrize("source", [[], [0], range(1, 31)], ids=["empty", "one_element", "range_1_30"])
def test_MoveNextAfterDispose(source):
    # Select is specialized for a bunch of different types, so we want
    # to make sure this holds true for all of them.
    identity_transforms = [
        lambda e: e,
        lambda e: _NotCollection(e),
        lambda e: list(e),  # ToArray
        lambda e: flp.lst(list(e)),  # ToList
        lambda e: deque(e),  # IList<T> that's not a List
        lambda e: flp.it(e).select(lambda i: i),  # Multiple Select() chains are optimized
    ]

    for equivalent_source in (t(source) for t in identity_transforms):
        result = _wrap(equivalent_source).select(lambda i: i)
        e = iter(result)

        for _ in e:  # Loop until we reach the end of the iterator, @ which pt it gets disposed.
            pass

        # MoveNext should not throw an exception after Dispose.
        with pytest.raises(StopIteration):
            next(e)


def _run_selector_during_count_transforms():
    return [
        lambda e: e,
        lambda e: flp.it(_NotCollection(e)),
        lambda e: flp.it(_NotCollection(e)).skip(1),
        lambda e: flp.it(_NotCollection(e)).where(lambda i: True),
        lambda e: flp.it(list(e)).where(lambda i: True),
        lambda e: flp.lst(list(e)).where(lambda i: True),
        lambda e: flp.it(deque(e)).where(lambda i: True),
        lambda e: e.select(lambda i: i),
        lambda e: e.take(e.count()),
        lambda e: flp.it(list(e)),
        lambda e: flp.lst(list(e)),
        lambda e: flp.it(deque(e)),  # Implements IList<T>.
    ]


@pytest.mark.parametrize("transform_index", range(12))
@pytest.mark.parametrize("n", range(6))
def test_RunSelectorDuringCount(n, transform_index):
    r = random.Random(42)
    enumerable = flp.it(range(1, n + 1)).select(lambda _: r.randint(0, 2147483647))
    source = _run_selector_during_count_transforms()[transform_index](enumerable)

    times_run = 0

    def counting_selector(i):
        nonlocal times_run
        result = times_run
        times_run += 1
        return result

    selected = source.select(counting_selector)
    selected.count()

    assert source.count() == times_run


def test_Select_SourceIsIList_EnumeratorDisposedOnComplete():
    source = _DisposeTrackingList([1, 2, 3, 4, 5])

    for item in flp.it(source).select(lambda i: i * 2):
        pass

    assert source.dispose_calls == 1


@pytest.mark.skip("In Python it could be a reasonable decision to leave the control over the source with the owner")
def test_Select_SourceIsIList_EnumeratorDisposedOnExplicitDispose():
    source = _DisposeTrackingList([1, 2, 3, 4, 5])

    with contextlib.closing(iter(flp.it(source).select(lambda i: i * 2))) as enumerator:
        next(enumerator)

    assert source.dispose_calls == 1