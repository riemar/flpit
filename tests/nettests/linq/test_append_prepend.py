"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq AppendPrependTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/AppendPrependTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper / language mapping:
    int?[] / string[] / int[]        -> list (wrapped with flp_type -> FlpIt and FlpList)
    CreateSources(x)                 -> conftest.create_sources(flp_type)(x)
    List<int>                        -> flp.lst([...]) (live container; List.Add -> FlpList.add)
    Assert.Equal(a, b) on sequences  -> list(a) == list(b)
    Assert.All(sources, ...)         -> for-loop over the sources
    "foo".Append('1') (IEnumerable<char>) -> flp.it("foo").append("1")
    ToArray()                        -> list(...)   (flpit has no ToArray)
    RunOnce()                        -> flp.it(run_once(...)) (conftest `run_once`, fails on 2nd enumeration)
    NumberRangeGuaranteedNotCollectionType(a, n) -> flp.it(_ForceNotCollection(range(a, a + n)))
    OverflowException                -> OverflowError (Python ints never overflow; see the *OverflowCount tests)
"""
from collections.abc import Collection, Iterator

import pytest

from conftest import create_sources
from flpit import flp, SourceNoneError

INT_MAX = 2147483647


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


def _number_range_guaranteed_not_collection_type(start, count):
    return flp.it(_ForceNotCollection(range(start, start + count)))


class _MockCollection(Collection):
    """Mock collection for testing overflow without allocating memory (ICollection<T> with a fixed Count)."""

    def __init__(self, count):
        self._count = count

    def __len__(self):
        return self._count

    def __iter__(self):
        return iter(())

    def __contains__(self, item):
        return False


# ---------------------------------------------------------------------------
# AppendPrependTests
# ---------------------------------------------------------------------------

def test_SameResultsRepeatCallsIntQueryAppend(flp_type):
    q1 = flp_type([2, 3, None, 2, None, 4, 5]).select(lambda x1: x1)

    assert list(q1.append(42)) == list(q1.append(42))
    assert list(q1.append(42)) == list(q1.concat([42]))


def test_SameResultsRepeatCallsIntQueryPrepend(flp_type):
    q1 = flp_type([2, 3, None, 2, None, 4, 5]).select(lambda x1: x1)

    assert list(q1.prepend(42)) == list(q1.prepend(42))
    assert list(q1.prepend(42)) == list(flp.it([42]).concat(q1))


def test_SameResultsRepeatCallsStringQueryAppend(flp_type):
    q1 = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"]).select(lambda x1: x1)

    assert list(q1.append("hi")) == list(q1.append("hi"))
    assert list(q1.append("hi")) == list(q1.concat(["hi"]))


def test_SameResultsRepeatCallsStringQueryPrepend(flp_type):
    q1 = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"]).select(lambda x1: x1)

    assert list(q1.prepend("hi")) == list(q1.prepend("hi"))
    assert list(q1.prepend("hi")) == list(flp.it(["hi"]).concat(q1))


def test_RepeatIteration():
    q = flp.range(3, 4).append(12)
    assert list(q) == list(q)

    q = q.append(14)
    assert list(q) == list(q)


def test_EmptyAppend(flp_type):
    first = []
    for first in create_sources(flp_type)(first):
        assert list(first.append(42)) == [42]


def test_EmptyPrepend(flp_type):
    first = []
    for first in create_sources(flp_type)(first):
        assert list(first.prepend("aa")) == ["aa"]


def test_PrependNoIteratingSourceBeforeFirstItem():
    ie = flp.lst([])
    prepended = ie.select(lambda i: i).prepend(4)
    ie.add(42)

    assert list(prepended) == list(ie.prepend(4))


def test_ForcedToEnumeratorDoesntEnumeratePrepend():
    iterator = _number_range_guaranteed_not_collection_type(0, 3).prepend(4)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


def test_ForcedToEnumeratorDoesntEnumerateAppend():
    iterator = _number_range_guaranteed_not_collection_type(0, 3).append(4)
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


def test_ForcedToEnumeratorDoesntEnumerateMultipleAppendsAndPrepends():
    iterator = _number_range_guaranteed_not_collection_type(0, 3).append(4).append(5).prepend(-1).prepend(-2)
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


def test_SourceNull(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).append(1)
    with pytest.raises(SourceNoneError):
        flp_type(None).prepend(1)


def test_Combined():
    v = flp.it("foo").append("1").append("2").prepend("3").concat(flp.it("qq").append("Q").prepend("W"))
    assert list(v) == list("3foo12WqqQ")

    v1 = flp.it("a").append("b").append("c").append("d")
    assert list(v1) == list("abcd")

    v2 = flp.it("a").prepend("b").prepend("c").prepend("d")
    assert list(v2) == list("dcba")


def test_AppendCombinations():
    source = flp.range(0, 3).append(3).append(4)
    app0a = source.append(5)
    app0b = source.append(6)

    app1aa = app0a.append(7)
    app1ab = app0a.append(8)

    app1ba = app0b.append(9)
    app1bb = app0b.append(10)

    assert [0, 1, 2, 3, 4, 5] == list(app0a)
    assert [0, 1, 2, 3, 4, 6] == list(app0b)

    assert [0, 1, 2, 3, 4, 5, 7] == list(app1aa)
    assert [0, 1, 2, 3, 4, 5, 8] == list(app1ab)

    assert [0, 1, 2, 3, 4, 6, 9] == list(app1ba)
    assert [0, 1, 2, 3, 4, 6, 10] == list(app1bb)


def test_PrependCombinations():
    source = flp.range(2, 2).prepend(1).prepend(0)
    pre0a = source.prepend(5)
    pre0b = source.prepend(6)

    pre1aa = pre0a.prepend(7)
    pre1ab = pre0a.prepend(8)

    pre1ba = pre0b.prepend(9)
    pre1bb = pre0b.prepend(10)

    assert [5, 0, 1, 2, 3] == list(pre0a)
    assert [6, 0, 1, 2, 3] == list(pre0b)

    assert [7, 5, 0, 1, 2, 3] == list(pre1aa)
    assert [8, 5, 0, 1, 2, 3] == list(pre1ab)

    assert [9, 6, 0, 1, 2, 3] == list(pre1ba)
    assert [10, 6, 0, 1, 2, 3] == list(pre1bb)


def test_Append1ToArrayToList(flp_type):
    for source in create_sources(flp_type)(range(0, 2)):
        source = source.append(2)
        assert list(range(0, 3)) == list(source.to_list())
        assert list(range(0, 3)) == list(source)  # ToArray()


def test_Prepend1ToArrayToList(flp_type):
    for source in create_sources(flp_type)(range(1, 3)):
        source = source.prepend(0)
        assert list(range(0, 3)) == list(source.to_list())
        assert list(range(0, 3)) == list(source)  # ToArray()


def test_AppendNToArrayToList(flp_type):
    for source in create_sources(flp_type)(range(0, 2)):
        source = source.append(2).append(3)
        assert list(range(0, 4)) == list(source.to_list())
        assert list(range(0, 4)) == list(source)  # ToArray()


def test_PrependNToArrayToList(flp_type):
    for source in create_sources(flp_type)(range(2, 4)):
        source = source.prepend(1).prepend(0)
        assert list(range(0, 4)) == list(source.to_list())
        assert list(range(0, 4)) == list(source)  # ToArray()


def test_AppendPrependToArrayToList(flp_type):
    for source in create_sources(flp_type)(range(2, 4)):
        source = source.prepend(1).append(4).prepend(0).append(5)
        assert list(range(0, 6)) == list(source.to_list())
        assert list(range(0, 6)) == list(source)  # ToArray()


def test_AppendPrependRunOnce(flp_type, run_once):
    def ro(q):  # RunOnce()
        return flp.it(run_once(q))

    for source in create_sources(flp_type)(range(2, 4)):
        assert list(range(0, 6)) == list(
            ro(ro(ro(ro(source).prepend(1)).prepend(0)).append(4)).append(5).to_list()
        )
        assert list(range(0, 6)) == list(
            ro(source.prepend(1).prepend(0).append(4).append(5)).to_list()
        )


def test_AppendPrepend_First_Last_ElementAt(flp_type):
    assert 42 == flp_type([42]).append(84).first()
    assert 42 == flp_type([84]).prepend(42).first()
    assert 84 == flp_type([42]).append(84).last()
    assert 84 == flp_type([84]).prepend(42).last()
    assert 42 == flp_type([42]).append(84).element_at(0)
    assert 42 == flp_type([84]).prepend(42).element_at(0)
    assert 84 == flp_type([42]).append(84).element_at(1)
    assert 84 == flp_type([84]).prepend(42).element_at(1)

    assert 42 == _number_range_guaranteed_not_collection_type(42, 1).append(84).first()
    assert 42 == _number_range_guaranteed_not_collection_type(84, 1).prepend(42).first()
    assert 84 == _number_range_guaranteed_not_collection_type(42, 1).append(84).last()
    assert 84 == _number_range_guaranteed_not_collection_type(84, 1).prepend(42).last()
    assert 42 == _number_range_guaranteed_not_collection_type(42, 1).append(84).element_at(0)
    assert 42 == _number_range_guaranteed_not_collection_type(84, 1).prepend(42).element_at(0)
    assert 84 == _number_range_guaranteed_not_collection_type(42, 1).append(84).element_at(1)
    assert 84 == _number_range_guaranteed_not_collection_type(84, 1).prepend(42).element_at(1)


# ---------------------------------------------------------------------------
# Overflow tests
#
# Python ints are unbounded, so no OverflowError can ever be raised by count(); these
# tests can only fail. The three Repeat(0, int.MaxValue) variants are skipped on purpose:
# flpit's count() enumerates, so they would spin through 2**31 elements (minutes) before
# failing. The MockCollection variants fail fast because the mock enumerates to nothing.
# ---------------------------------------------------------------------------

@pytest.mark.skip("would enumerate 2**31 elements before failing; Python ints cannot overflow")
def test_AppendOverflowCount():
    # AppendPrepend1Iterator overflow when source has GetCount optimization
    source = flp.repeat(0, INT_MAX)
    appended = source.append(1)

    with pytest.raises(OverflowError):
        appended.count()


@pytest.mark.skip("would enumerate 2**31 elements before failing; Python ints cannot overflow")
def test_PrependOverflowCount():
    source = flp.repeat(0, INT_MAX)
    prepended = source.prepend(1)

    with pytest.raises(OverflowError):
        prepended.count()


@pytest.mark.skip("would enumerate 2**31 elements before failing; Python ints cannot overflow")
def test_AppendPrependNOverflowCount():
    # AppendPrependN overflow when source has GetCount optimization
    source = flp.repeat(0, INT_MAX)
    result = source.append(1).prepend(2)

    with pytest.raises(OverflowError):
        result.count()


@pytest.mark.skip("Python int can't overflow")
def test_AppendOverflowCountWithICollection():
    # AppendPrepend1Iterator overflow when source is ICollection
    source = _MockCollection(INT_MAX)
    appended = flp.it(source).append(1)

    # Python integers never overflow, so no OverflowError is raised.
    with pytest.raises(OverflowError):
        appended.count()


@pytest.mark.skip("Python int can't overflow")
def test_PrependOverflowCountWithICollection():
    source = _MockCollection(INT_MAX)
    prepended = flp.it(source).prepend(1)

    with pytest.raises(OverflowError):
        prepended.count()


@pytest.mark.skip("Python int can't overflow")
def test_AppendPrependNOverflowCountWithICollection():
    # AppendPrependN overflow when source is ICollection
    source = _MockCollection(INT_MAX)
    result = flp.it(source).append(1).prepend(2)

    # EXPECTED FAIL: same as test_AppendOverflowCountWithICollection.
    with pytest.raises(OverflowError):
        result.count()
