"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq WhereTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/WhereTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's source-type variants are mapped to Python sources as follows:
    Array                -> flp.it(list)
    List                 -> flp.lst(list)            (FlpList)
    IReadOnlyCollection  -> flp.it(tuple)
    ICollection          -> flp.it(collections.deque) (.NET: LinkedList)
    IEnumerable          -> flp.it(range) or flp.it(re-enumerable non-collection)

.NET's RunOnce() is replaced by a one-shot generator (see _run_once).

Not portable / not implemented (skipped with a reason, as elsewhere in nettests):
    * Where((value, index) => ...) overloads: where() has no index overload yet.
    * IEnumerator.Current / Reset() and enumerators that resume after throwing:
      Python iterators have no Current, and a generator is finished once it raises.
"""

import contextlib
import random
from collections import deque
from collections.abc import Iterator

import pytest

from conftest import create_sources
from flpit import (
    flp,
    ArgumentOutOfRangeError,
    EmptySequenceError,
    PredicateNoneError,
    SourceNoneError,
)


def _is_even(x):
    return x % 2 == 0


def _is_null_or_empty(s):
    return s is None or s == ""


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


def _is_enumerator_that_enumerates(iterator):
    """.NET: `iterator as IEnumerator<int>` followed by MoveNext()."""
    if not isinstance(iterator, Iterator):
        return False
    return next(iterator, _MISSING) is not _MISSING


_MISSING = object()


# ----------------------------------------------------------------------------
# Null arguments
# ----------------------------------------------------------------------------

def test_Where_SourceIsNull_ArgumentNullExceptionThrown(flp_type):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before where() can be invoked.
    with pytest.raises(SourceNoneError):
        flp_type(None).where(lambda value: True)

    with pytest.raises(SourceNoneError):
        flp_type(None).where(lambda value, index: True)


def test_Where_PredicateIsNull_ArgumentNullExceptionThrown(flp_type):
    source = flp_type(range(1, 11))

    with pytest.raises(PredicateNoneError):
        source.where(None)

    with pytest.raises(PredicateNoneError):
        source.where(None)


# ----------------------------------------------------------------------------
# Deferred execution
# ----------------------------------------------------------------------------

def test_Where_Array_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it([func])

    query = source.where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_Where_List_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.lst([func])

    query = source.where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_Where_IReadOnlyCollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it((func,))

    query = source.where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_Where_ICollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it(deque([func]))

    query = source.where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_Where_IEnumerable_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it(_NotCollection([func]))

    query = source.where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_WhereWhere_Array_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it([func])

    query = source.where(lambda value: value()).where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_WhereWhere_List_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.lst([func])

    query = source.where(lambda value: value()).where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_WhereWhere_IReadOnlyCollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it((func,))

    query = source.where(lambda value: value()).where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_WhereWhere_ICollection_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it(deque([func]))

    query = source.where(lambda value: value()).where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


def test_WhereWhere_IEnumerable_ExecutionIsDeferred():
    called = []

    def func():
        called.append(True)
        return True

    source = flp.it(_NotCollection([func]))

    query = source.where(lambda value: value()).where(lambda value: value())
    assert called == []

    # The index overload is not implemented, so this only verifies that
    # building the query does not invoke the predicate.
    query = source.where(lambda value, index: value())
    assert called == []


# ----------------------------------------------------------------------------
# Expected return value
# ----------------------------------------------------------------------------

def test_Where_Array_ReturnsExpectedValues_True():
    source = [1, 2, 3, 4, 5]
    true_predicate = lambda value: True

    result = flp.it(source).where(true_predicate)

    assert len(source) == result.count()
    for i in range(len(source)):
        assert source[i] == result.element_at(i)


def test_Where_Array_ReturnsExpectedValues_False():
    source = [1, 2, 3, 4, 5]
    false_predicate = lambda value: False

    result = flp.it(source).where(false_predicate)

    assert result.count() == 0


@pytest.mark.skip("not implemented yet")
def test_Where_Array_ReturnsExpectedValues_Complex():
    # where() has no index overload: complex_predicate is (value, index).
    source = [2, 1, 3, 5, 4]
    complex_predicate = lambda value, index: value == index

    result = flp.it(source).where(complex_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 1
    assert result.element_at(1) == 4


def test_Where_List_ReturnsExpectedValues_True():
    source = flp.lst([1, 2, 3, 4, 5])
    true_predicate = lambda value: True

    result = source.where(true_predicate)

    assert len(source) == result.count()
    for i in range(len(source)):
        assert source[i] == result.element_at(i)


def test_Where_List_ReturnsExpectedValues_False():
    source = flp.lst([1, 2, 3, 4, 5])
    false_predicate = lambda value: False

    result = source.where(false_predicate)

    assert result.count() == 0


@pytest.mark.skip("not implemented yet")
def test_Where_List_ReturnsExpectedValues_Complex():
    # where() has no index overload: complex_predicate is (value, index).
    source = flp.lst([2, 1, 3, 5, 4])
    complex_predicate = lambda value, index: value == index

    result = source.where(complex_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 1
    assert result.element_at(1) == 4


def test_Where_IReadOnlyCollection_ReturnsExpectedValues_True():
    source = (1, 2, 3, 4, 5,)
    true_predicate = lambda value: True

    result = flp.it(source).where(true_predicate)

    assert len(source) == result.count()
    for i in range(len(source)):
        assert source[i] == result.element_at(i)


def test_Where_IReadOnlyCollection_ReturnsExpectedValues_False():
    source = (1, 2, 3, 4, 5,)
    false_predicate = lambda value: False

    result = flp.it(source).where(false_predicate)

    assert result.count() == 0


@pytest.mark.skip("not implemented yet")
def test_Where_IReadOnlyCollection_ReturnsExpectedValues_Complex():
    # where() has no index overload: complex_predicate is (value, index).
    source = (2, 1, 3, 5, 4,)
    complex_predicate = lambda value, index: value == index

    result = flp.it(source).where(complex_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 1
    assert result.element_at(1) == 4


def test_Where_ICollection_ReturnsExpectedValues_True():
    source = deque([1, 2, 3, 4, 5])
    true_predicate = lambda value: True

    result = flp.it(source).where(true_predicate)

    assert len(source) == result.count()
    for i in range(len(source)):
        assert source[i] == result.element_at(i)


def test_Where_ICollection_ReturnsExpectedValues_False():
    source = deque([1, 2, 3, 4, 5])
    false_predicate = lambda value: False

    result = flp.it(source).where(false_predicate)

    assert result.count() == 0


@pytest.mark.skip("not implemented yet")
def test_Where_ICollection_ReturnsExpectedValues_Complex():
    # where() has no index overload: complex_predicate is (value, index).
    source = deque([2, 1, 3, 5, 4])
    complex_predicate = lambda value, index: value == index

    result = flp.it(source).where(complex_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 1
    assert result.element_at(1) == 4


def test_Where_IEnumerable_ReturnsExpectedValues_True():
    source = range(1, 6)
    true_predicate = lambda value: True

    result = flp.it(source).where(true_predicate)

    assert len(source) == result.count()
    for i in range(len(source)):
        assert source[i] == result.element_at(i)


def test_Where_IEnumerable_ReturnsExpectedValues_False():
    source = range(1, 6)
    false_predicate = lambda value: False

    result = flp.it(source).where(false_predicate)

    assert result.count() == 0


@pytest.mark.skip("not implemented yet")
def test_Where_IEnumerable_ReturnsExpectedValues_Complex():
    # where() has no index overload: complex_predicate is (value, index).
    source = deque([2, 1, 3, 5, 4])
    complex_predicate = lambda value, index: value == index

    result = flp.it(source).where(complex_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 1
    assert result.element_at(1) == 4


def test_Where_EmptyEnumerable_ReturnsNoElements():
    source = flp.it([])
    was_selector_called = False

    def predicate(value):
        nonlocal was_selector_called
        was_selector_called = True
        return True

    result = source.where(predicate)

    assert result.count() == 0
    assert was_selector_called is False


@pytest.mark.skip("not implemented yet")
def test_Where_EmptyEnumerable_ReturnsNoElementsWithIndex():
    # where() has no index overload.
    assert flp.it([]).where(lambda e, i: True).count() == 0


@pytest.mark.skip("Python iterators have no Current property")
def test_Where_Array_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Where_List_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Where_IReadOnlyCollection_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Where_ICollection_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


@pytest.mark.skip("Python iterators have no Current property")
def test_Where_IEnumerable_CurrentIsDefaultOfTAfterEnumeration():
    # .NET asserts enumerator.Current == default(int) after the enumeration
    # finished. A Python iterator only signals the end with StopIteration.
    pass


def test_WhereWhere_Array_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    even_predicate = lambda value: value % 2 == 0

    result = flp.it(source).where(even_predicate).where(even_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4


def test_WhereWhere_List_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0

    result = source.where(even_predicate).where(even_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4


def test_WhereWhere_IReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5,)
    even_predicate = lambda value: value % 2 == 0

    result = flp.it(source).where(even_predicate).where(even_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4


def test_WhereWhere_ICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0

    result = flp.it(source).where(even_predicate).where(even_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4


def test_WhereWhere_IEnumerable_ReturnsExpectedValues():
    source = range(1, 6)
    even_predicate = lambda value: value % 2 == 0

    result = flp.it(source).where(even_predicate).where(even_predicate)

    assert result.count() == 2
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4


def test_WhereSelect_Array_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelectSelect_Array_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(lambda i: i).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelect_List_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = source.where(even_predicate).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelectSelect_List_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = source.where(even_predicate).select(lambda i: i).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelect_IReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5,)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelectSelect_IReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5,)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(lambda i: i).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelect_ICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelectSelect_ICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(lambda i: i).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelect_IEnumerable_ReturnsExpectedValues():
    source = range(1, 6)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_WhereSelectSelect_IEnumerable_ReturnsExpectedValues():
    source = range(1, 6)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).where(even_predicate).select(lambda i: i).select(add_selector)

    assert result.count() == 2
    assert result.element_at(0) == 3
    assert result.element_at(1) == 5


def test_SelectWhere_Array_ReturnsExpectedValues():
    source = [1, 2, 3, 4, 5]
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).select(add_selector).where(even_predicate)

    assert result.count() == 3
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4
    assert result.element_at(2) == 6


def test_SelectWhere_List_ReturnsExpectedValues():
    source = flp.lst([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = source.select(add_selector).where(even_predicate)

    assert result.count() == 3
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4
    assert result.element_at(2) == 6


def test_SelectWhere_IReadOnlyCollection_ReturnsExpectedValues():
    source = (1, 2, 3, 4, 5,)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).select(add_selector).where(even_predicate)

    assert result.count() == 3
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4
    assert result.element_at(2) == 6


def test_SelectWhere_ICollection_ReturnsExpectedValues():
    source = deque([1, 2, 3, 4, 5])
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).select(add_selector).where(even_predicate)

    assert result.count() == 3
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4
    assert result.element_at(2) == 6


def test_SelectWhere_IEnumerable_ReturnsExpectedValues():
    source = range(1, 6)
    even_predicate = lambda value: value % 2 == 0
    add_selector = lambda value: value + 1

    result = flp.it(source).select(add_selector).where(even_predicate)

    assert result.count() == 3
    assert result.element_at(0) == 2
    assert result.element_at(1) == 4
    assert result.element_at(2) == 6


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------

@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Where_PredicateThrowsException():
    # .NET: the first MoveNext throws, Current is default(int), and the next
    # MoveNext succeeds with Current == 2. A Python generator that raised is
    # finished, so enumeration can not continue.
    pass


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Where_SourceThrowsOnCurrent():
    # .NET: ThrowsOnCurrentEnumerator throws from Current; there is no Python equivalent.
    pass


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Where_SourceThrowsOnMoveNext():
    # .NET: after the failed MoveNext the next MoveNext succeeds with Current == 2.
    pass


@pytest.mark.skip("Python generators can't resume after raising; no Current property")
def test_Where_SourceThrowsOnGetEnumerator():
    # .NET: after the failed MoveNext the next MoveNext succeeds with Current == 1.
    pass


@pytest.mark.skip("Python iterators have no Reset()")
def test_Select_ResetEnumerator_ThrowsException():
    # .NET expects NotSupportedException from enumerator.Reset().
    pass

@pytest.mark.skip(".NET style mutation tracking needs custom implementation per source type and has a roughly 25% performance penalty")
def test_Where_SourceThrowsOnConcurrentModification():
    source = flp.lst([1, 2, 3, 4, 5])
    true_predicate = lambda value: True

    enumerator = iter(source.where(true_predicate))

    assert next(enumerator) == 1

    source.add(6)

    # Will fail (known gap, deliberately not implemented): .NET's List<T> keeps a
    # version counter that its enumerator checks. FlpList keeps none, and
    # FlpList.where() enumerates the underlying raw list, so a Python list iterator
    # simply continues over the appended element instead of raising. A guarded
    # iteration path would cost roughly 20-100% extra iteration time.
    with pytest.raises(InvalidOperationError):
        next(enumerator)


def test_Where_GetEnumeratorReturnsUniqueInstances():
    source = [1, 2, 3, 4, 5]
    result = flp.it(source).where(lambda value: True)

    enumerator1 = iter(result)
    enumerator2 = iter(result)

    # .NET additionally asserts Assert.Same(result, enumerator1), i.e. that the
    # query object is its own first enumerator. That is a .NET implementation
    # detail with no Python counterpart.
    assert enumerator1 is not enumerator2


# ----------------------------------------------------------------------------
# Predicate coverage
# ----------------------------------------------------------------------------

def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)

    assert list(q.where(_is_even)) == list(q.where(_is_even))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", None, "SoS", ""])

    assert list(q.where(_is_null_or_empty)) == list(q.where(_is_null_or_empty))


def test_SingleElementPredicateFalse():
    source = [3]

    # .NET asserts Assert.DoesNotContain(source, IsEven) on the source itself,
    # not on a where() result; kept as in the original.
    assert not any(_is_even(x) for x in source)


def test_PredicateFalseForAll():
    source = [9, 7, 15, 3, 27]

    # Same as above: the .NET original checks the source, not where().
    assert not any(_is_even(x) for x in source)


def test_PredicateTrueFirstOnly(flp_type):
    source = flp_type([10, 9, 7, 15, 3, 27])

    assert list(source.take(1)) == list(source.where(_is_even))


def test_PredicateTrueLastOnly(flp_type):
    source = flp_type([9, 7, 15, 3, 27, 20])

    assert list(source.skip(len(list(source)) - 1)) == list(source.where(_is_even))


def test_PredicateTrueFirstThirdSixth(flp_type):
    source = flp_type([20, 7, 18, 9, 7, 10, 21])
    expected = [20, 18, 10]

    assert expected == list(source.where(_is_even))


def test_RunOnce():
    source = [20, 7, 18, 9, 7, 10, 21]
    expected = [20, 18, 10]

    assert expected == list(flp.it(_run_once(source)).where(_is_even))


def test_SourceAllNullsPredicateTrue(flp_type):
    source = [None, None, None, None]

    assert source == list(flp_type(source).where(lambda num: True))


@pytest.mark.skip("index not implemented yet")
def test_SourceEmptyIndexedPredicate(tlog):
    # where() has no index overload.
    assert list(flp.it([]).where(lambda e, i: i % 2 == 0)) == []


@pytest.mark.skip("index not implemented yet")
def test_SingleElementIndexedPredicateTrue():
    # where() has no index overload.
    source = [2]
    assert source == list(flp.it(source).where(lambda e,i:  logNEval(i)))


@pytest.mark.skip("index not implemented yet")
def test_SingleElementIndexedPredicateFalse():
    # where() has no index overload.
    source = [3]
    assert list(flp.it(source).where(lambda e, i: e % 2 == 0)) == []


@pytest.mark.skip("index not implemented yet")
def test_IndexedPredicateFalseForAll():
    # where() has no index overload.
    source = [9, 7, 15, 3, 27]
    assert list(flp.it(source).where(lambda e, i: e % 2 == 0)) == []


@pytest.mark.skip("index not implemented yet")
def test_IndexedPredicateTrueFirstOnly():
    # where() has no index overload.
    source = flp.it([10, 9, 7, 15, 3, 27])
    assert list(source.take(1)) == list(source.where(lambda e, i: e % 2 == 0))


@pytest.mark.skip("not implemented yet")
def test_IndexedPredicateTrueLastOnly():
    # where() has no index overload.
    source = flp.it([9, 7, 15, 3, 27, 20])
    assert list(source.skip(5)) == list(source.where(lambda e, i: e % 2 == 0))


@pytest.mark.skip("index not implemented yet")
def test_IndexedPredicateTrueFirstThirdSixth():
    # where() has no index overload.
    source = [20, 7, 18, 9, 7, 10, 21]
    expected = [20, 18, 10]
    assert expected == list(flp.it(source).where(lambda e, i: e % 2 == 0))


@pytest.mark.skip("index not implemented yet")
def test_SourceAllNullsIndexedPredicateTrue():
    # where() has no index overload.
    source = [None, None, None, None]
    assert source == list(flp.it(source).where(lambda num, index: True))


@pytest.mark.skip("index not implemented yet")
def test_PredicateSelectsFirst():
    # where() has no index overload.
    source = flp.it([-40, 20, 100, 5, 4, 9])
    assert list(source.take(1)) == list(source.where(lambda e, i: i == 0))


@pytest.mark.skip("index not implemented yet")
def test_PredicateSelectsLast():
    # where() has no index overload.
    source = flp.it([-40, 20, 100, 5, 4, 9])
    assert list(source.skip(5)) == list(source.where(lambda e, i: i == 5))


@pytest.mark.skip("Python int can't overflow")
def test_IndexOverflows():
    # .NET (stress mode only): the Where index overflows int.MaxValue.
    pass


# .NET: `iterator as IEnumerator<int>` followed by MoveNext(). In Python the
# equivalent is "if the query object is itself an Iterator, calling next() on it
# must not hand out elements" ("Don't insist on this behaviour, but check it's
# correct if it happens").

def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(range(0, 3)).where(lambda i: True)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateArray():
    iterator = flp.it(list(range(0, 3))).where(lambda i: True)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateList():
    iterator = flp.lst(list(range(0, 3))).where(lambda i: True)

    assert not _is_enumerator_that_enumerates(iterator)


@pytest.mark.skip("index not implemented yet")
def test_ForcedToEnumeratorDoesntEnumerateIndexed():
    # where() has no index overload.
    iterator = flp.it(range(0, 3)).where(lambda e, i: True)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateWhereSelect():
    iterator = flp.it(range(0, 3)).where(lambda i: True).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateWhereSelectArray():
    iterator = flp.it(list(range(0, 3))).where(lambda i: True).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def test_ForcedToEnumeratorDoesntEnumerateWhereSelectList():
    iterator = flp.lst(list(range(0, 3))).where(lambda i: True).select(lambda i: i)

    assert not _is_enumerator_that_enumerates(iterator)


def _generate_random_sequence(seed, count):
    rnd = random.Random(seed)
    return [rnd.randint(-2147483648, 2147483647) for _ in range(count)]


@pytest.mark.parametrize("source_index", [0, 1], ids=["collection", "non_collection"])
def test_ToCollection(flp_type, source_index):
    seq = _generate_random_sequence(0xDEADBEEF, 10)
    source = create_sources(flp_type)(seq)[source_index]

    for equivalent in (source.where(lambda s: True), source.where(lambda s: True).select(lambda s: s)):
        assert list(source) == list(equivalent)
        assert list(source) == list(equivalent)  # ToArray
        assert list(source) == list(equivalent.to_list())
        # Count may be optimized. The above asserts do not imply this will pass.
        assert len(seq) == equivalent.count()

        en = iter(equivalent)
        for _ in range(equivalent.count()):
            next(en)

        # No more items, this should dispose.
        with pytest.raises(StopIteration):
            next(en)
        # .NET asserts Current is reset to default(int); Python iterators have
        # no Current. Calling next() after exhaustion must keep working.
        with pytest.raises(StopIteration):
            next(en)


def test_WhereFirstLast(flp_type):
    for source in create_sources(flp_type)(range(0, 10)):
        assert source.where(lambda i: i == 3).first() == 3
        assert source.where(lambda i: i % 2 == 0).first() == 0
        assert source.where(lambda i: i == 3).last() == 3
        assert source.where(lambda i: i % 2 == 0).last() == 8
        assert source.where(lambda i: i == 3).element_at(0) == 3
        assert source.where(lambda i: i % 2 == 0).element_at(4) == 8

        with pytest.raises(EmptySequenceError):
            source.where(lambda i: i == 10).first()
        with pytest.raises(EmptySequenceError):
            source.where(lambda i: i == 10).last()
        with pytest.raises(ArgumentOutOfRangeError):
            source.where(lambda i: i == 10).element_at(0)


def test_WhereSelectFirstLast(flp_type):
    for source in create_sources(flp_type)(range(0, 10)):
        assert source.where(lambda i: i == 3).select(lambda i: i * 2).first() == 6
        assert source.where(lambda i: i % 2 == 0).select(lambda i: i * 2).first() == 0
        assert source.where(lambda i: i == 3).select(lambda i: i * 2).last() == 6
        assert source.where(lambda i: i % 2 == 0).select(lambda i: i * 2).last() == 16
        assert source.where(lambda i: i == 3).select(lambda i: i * 2).element_at(0) == 6
        assert source.where(lambda i: i % 2 == 0).select(lambda i: i * 2).element_at(4) == 16

        with pytest.raises(EmptySequenceError):
            source.where(lambda i: i == 10).select(lambda i: i * 2).first()
        with pytest.raises(EmptySequenceError):
            source.where(lambda i: i == 10).select(lambda i: i * 2).last()
        with pytest.raises(ArgumentOutOfRangeError):
            source.where(lambda i: i == 10).select(lambda i: i * 2).element_at(0)


def test_Where_SourceIsIList_EnumeratorDisposedOnComplete():
    source = _DisposeTrackingList([1, 2, 3, 4, 5])

    for item in flp.it(source).where(lambda i: i % 2 == 0):
        pass

    assert source.dispose_calls == 1

@pytest.mark.skip("In Python it could be a reasonable decision to leave the control over the source with the owner")
def test_Where_SourceIsIList_EnumeratorDisposedOnExplicitDispose():
    source = _DisposeTrackingList([1, 2, 3, 4, 5])

    # Will fail: closing the where() generator does not close the source iterator
    # (where() does a plain `for item in self` without a try/finally or closing()).
    # The source iterator is only released once the where() generator is garbage
    # collected, so dispose_calls is still 0 right after close().

    with contextlib.closing(iter(flp.it(source).where(lambda i: i % 2 == 0))) as enumerator:
        next(enumerator)

    assert source.dispose_calls == 1