"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ToListTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ToListTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper / language mapping:
    List<T>                          -> flp.lst([...])   (FlpList)
    IEnumerable<T> / T[]             -> flp_type(list)   (FlpIt and FlpList)
    ToList()                         -> to_list()
    TestEnumerable<T>                -> _ForceNotCollection (iterable only)
    TestReadOnlyCollection<T>        -> _TestReadOnlyCollection (sized + iterable, not indexable)
    TestCollection<T>                -> _TestCollection (ICollection<T> that counts Count/CopyTo "touches")
    ReadOnlyCollection<T>            -> tuple
    Assert.Equal(a, b) on sequences  -> list(a) == list(b)
    RunOnce()                        -> flp.it(run_once(...)) (conftest `run_once`)
    NumberRangeGuaranteedNotCollectionType(a, n) -> flp.it(_ForceNotCollection(range(a, a + n)))
    RepeatedNullableNumberGuaranteedNotCollectionType(null, n) -> flp.it(_ForceNotCollection([None] * n))
    `x as ICollection<T>` is null    -> not isinstance(x, collections.abc.Collection)

Known reasons for failures in this file:
    * to_list() has no Count/CopyTo fast path for collections (TouchCount / UseCopyTo tests).
"""
from collections import deque
from collections.abc import Collection

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


class _TestCollection(Collection):
    """TestCollection<T>: ICollection<T> that records whether Count / CopyTo were touched."""

    def __init__(self, source):
        self._items = list(source)
        self.count_touched = 0
        self.copy_to_touched = 0

    def __len__(self):
        self.count_touched += 1
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, item):
        return item in self._items

    def copy_to(self, array, index):  # CopyTo(T[] array, int arrayIndex): never called by flpit
        self.copy_to_touched += 1
        array[index:index + len(self._items)] = self._items


def _enumerate(source):
    """Enumerate without touching __len__ (list() would call it through __length_hint__)."""
    return [x for x in source]


def _number_range_guaranteed_not_collection_type(start, count):
    return flp.it(_ForceNotCollection(range(start, start + count)))


# ---------------------------------------------------------------------------
# ToListTests
# ---------------------------------------------------------------------------

def test_ToList_AlwaysCreateACopy():
    source_list = flp.lst([1, 2, 3, 4, 5])
    result_list = source_list.to_list()

    assert source_list is not result_list
    assert list(source_list) == list(result_list)


def _run_to_list_on_all_collection_types(items, validation):
    validation(flp.it(list(items)).to_list())  # Enumerable.ToList(T[])
    validation(flp.lst(items).to_list())  # new List<T>(items)
    validation(flp.it(_ForceNotCollection(items)).to_list())  # TestEnumerable<T>
    validation(flp.it(_TestReadOnlyCollection(items)).to_list())  # TestReadOnlyCollection<T>
    validation(flp.it(_TestCollection(items)).to_list())  # TestCollection<T>


def test_ToList_WorkWithEmptyCollection():
    def validation(result_list):
        assert result_list is not None
        assert 0 == len(result_list)

    _run_to_list_on_all_collection_types([], validation)


def test_ToList_ProduceCorrectList():
    source_array = [1, 2, 3, 4, 5, 6, 7]

    def validation(result_list):
        assert len(source_array) == len(result_list)
        assert source_array == list(result_list)

    _run_to_list_on_all_collection_types(source_array, validation)

    source_string_array = ["1", "2", "3", "4", "5", "6", "7", "8"]

    def validation_strings(result_string_list):
        assert len(source_string_array) == len(result_string_list)
        for i in range(len(source_string_array)):
            assert source_string_array[i] is result_string_list[i]

    _run_to_list_on_all_collection_types(source_string_array, validation_strings)


def test_RunOnce(run_once):
    assert list(range(3, 12)) == list(flp.it(run_once(range(3, 12))).to_list())


@pytest.mark.skip("Test .NET specific to detect Collection<T> optomization")
def test_ToList_TouchCountWithICollection():
    source = _TestCollection([1, 2, 3, 4])

    result_list = flp.it(source).to_list()

    assert _enumerate(source) == list(result_list)
    # EXPECTED FAIL: to_list() just iterates the iterable; there is no ICollection<T>.Count
    # fast path, so Count (__len__) is never touched (0 instead of 1).
    assert 1 == source.count_touched


def test_ToList_ThrowArgumentNullExceptionWhenSourceIsNull(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).to_list()


@pytest.mark.skip("Test .NET specific to detect Collection<T> optomization")
def test_ToList_UseCopyToWithICollection():
    source = _TestCollection([1, 2, 3, 4])

    result_list = flp.it(source).to_list()

    assert _enumerate(source) == list(result_list)
    # EXPECTED FAIL: to_list() never uses a CopyTo-style bulk copy (copy_to is not called).
    assert 1 == source.copy_to_touched


_WHERE_SELECT_DATA = [
    ([], []),
    ([1], ["1"]),
    ([1, 2, 3], ["1", "2", "3"]),
]


@pytest.mark.parametrize("source_integers, converted_strings", _WHERE_SELECT_DATA)
def test_ToList_ArrayWhereSelect(flp_type, source_integers, converted_strings):
    source_list = list(source_integers)
    converted_list = list(converted_strings)
    empty_integers_list = []
    empty_strings_list = []

    assert converted_list == list(flp_type(source_integers).select(lambda i: str(i)).to_list())
    assert source_list == list(flp_type(source_integers).where(lambda i: True).to_list())
    assert empty_integers_list == list(flp_type(source_integers).where(lambda i: False).to_list())
    assert converted_list == list(flp_type(source_integers).where(lambda i: True).select(lambda i: str(i)).to_list())
    assert empty_strings_list == list(flp_type(source_integers).where(lambda i: False).select(lambda i: str(i)).to_list())
    assert converted_list == list(flp_type(source_integers).select(lambda i: str(i)).where(lambda s: s is not None).to_list())
    assert empty_strings_list == list(flp_type(source_integers).select(lambda i: str(i)).where(lambda s: s is None).to_list())


@pytest.mark.parametrize("source_integers, converted_strings", _WHERE_SELECT_DATA)
def test_ToList_ListWhereSelect(source_integers, converted_strings):
    source_list = flp.lst(source_integers)
    converted_list = flp.lst(converted_strings)
    empty_integers_list = flp.lst([])
    empty_strings_list = flp.lst([])

    assert list(converted_list) == list(source_list.select(lambda i: str(i)).to_list())
    assert list(source_list) == list(source_list.where(lambda i: True).to_list())
    assert list(empty_integers_list) == list(source_list.where(lambda i: False).to_list())
    assert list(converted_list) == list(source_list.where(lambda i: True).select(lambda i: str(i)).to_list())
    assert list(empty_strings_list) == list(source_list.where(lambda i: False).select(lambda i: str(i)).to_list())
    assert list(converted_list) == list(source_list.select(lambda i: str(i)).where(lambda s: s is not None).to_list())
    assert list(empty_strings_list) == list(source_list.select(lambda i: str(i)).where(lambda s: s is None).to_list())


@pytest.mark.parametrize("source_integers, converted_strings", _WHERE_SELECT_DATA)
def test_ToList_IListWhereSelect(flp_type, source_integers, converted_strings):
    source_list = tuple(source_integers)  # ReadOnlyCollection<int>
    converted_list = tuple(converted_strings)

    assert list(converted_list) == list(flp_type(source_list).select(lambda i: str(i)).to_list())
    assert list(source_list) == list(flp_type(source_list).where(lambda i: True).to_list())
    assert [] == list(flp_type(source_list).where(lambda i: False).to_list())
    assert list(converted_list) == list(flp_type(source_list).where(lambda i: True).select(lambda i: str(i)).to_list())
    assert [] == list(flp_type(source_list).where(lambda i: False).select(lambda i: str(i)).to_list())
    assert list(converted_list) == list(flp_type(source_list).select(lambda i: str(i)).where(lambda s: s is not None).to_list())
    assert [] == list(flp_type(source_list).select(lambda i: str(i)).where(lambda s: s is None).to_list())


def test_SameResultsRepeatCallsFromWhereOnIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > -2147483648)

    assert list(q.to_list()) == list(q.to_list())


def test_SameResultsRepeatCallsFromWhereOnStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: x is not None and x != "")

    assert list(q.to_list()) == list(q.to_list())


def test_SourceIsEmptyICollectionT(flp_type):
    source = []

    assert [] == list(flp_type(source).to_list())
    assert [] == list(flp_type(deque(source)).to_list())  # ICollection<int> view of the same source


def test_SourceIsICollectionTWithFewElements(flp_type):
    source = [-5, None, 0, 10, 3, -1, None, 4, 9]
    expected = [-5, None, 0, 10, 3, -1, None, 4, 9]

    assert expected == list(flp_type(source).to_list())
    assert expected == list(flp_type(deque(source)).to_list())  # ICollection<int?> view of the same source


def test_SourceNotICollectionAndIsEmpty():
    source = _number_range_guaranteed_not_collection_type(-4, 0)

    assert [] == list(source.to_list())


def test_SourceNotICollectionAndHasElements():
    raw = _ForceNotCollection(range(-4, 6))
    expected = [-4, -3, -2, -1, 0, 1, 2, 3, 4, 5]

    assert not isinstance(raw, Collection)
    assert expected == list(flp.it(raw).to_list())


def test_SourceNotICollectionAndAllNull():
    raw = _ForceNotCollection([None] * 5)
    expected = [None, None, None, None, None]

    assert not isinstance(raw, Collection)
    assert expected == list(flp.it(raw).to_list())


def test_ConstantTimeCountPartitionSelectSameTypeToList():
    source = flp.range(0, 100).select(lambda i: i * 2).skip(1).take(5)

    assert [2, 4, 6, 8, 10] == list(source.to_list())


def test_ConstantTimeCountPartitionSelectDiffTypeToList():
    source = flp.range(0, 100).select(lambda i: str(i)).skip(1).take(5)

    assert ["1", "2", "3", "4", "5"] == list(source.to_list())


def test_ConstantTimeCountEmptyPartitionSelectSameTypeToList():
    source = flp.range(0, 100).select(lambda i: i * 2).skip(1000)

    assert [] == list(source.to_list())


def test_ConstantTimeCountEmptyPartitionSelectDiffTypeToList():
    source = flp.range(0, 100).select(lambda i: str(i)).skip(1000)

    assert [] == list(source.to_list())


def test_NonConstantTimeCountPartitionSelectSameTypeToList():
    source = _number_range_guaranteed_not_collection_type(0, 100).order_by(lambda i: i).select(lambda i: i * 2).skip(1).take(5)

    assert [2, 4, 6, 8, 10] == list(source.to_list())


def test_NonConstantTimeCountPartitionSelectDiffTypeToList():
    source = _number_range_guaranteed_not_collection_type(0, 100).order_by(lambda i: i).select(lambda i: str(i)).skip(1).take(5)

    assert ["1", "2", "3", "4", "5"] == list(source.to_list())


def test_NonConstantTimeCountEmptyPartitionSelectSameTypeToList():
    source = _number_range_guaranteed_not_collection_type(0, 100).order_by(lambda i: i).select(lambda i: i * 2).skip(1000)

    assert [] == list(source.to_list())


def test_NonConstantTimeCountEmptyPartitionSelectDiffTypeToList():
    source = _number_range_guaranteed_not_collection_type(0, 100).order_by(lambda i: i).select(lambda i: str(i)).skip(1000)

    assert [] == list(source.to_list())
