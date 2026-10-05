"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Collection generic List tests:
https://github.com/dotnet/dotnet/tree/main/src/runtime/src/libraries/System.Collections/tests/Generic/List

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

The .NET tests distinguish IList and non-IList sources and use generic type
instantiations. In Python, those distinctions are represented by flp.lst and
flp.it respectively; Python's runtime does not require separate copies for
each generic type argument.
"""
from flpit import ArgumentOutOfBoundsError
from flpit import ArgumentNonNegError
from flpit import ArgumentError
from flpit.core.linq import CollectionNoneError
import pytest
from flpit import FlpList, ArgumentOutOfRangeError

VALID_COLLECTION_SIZES = [0, 1, 10, 100]
INT_MIN = -2147483648
INT_MAX = 2147483647
DEFAULT_T = 0

def generic_list_factory(count=0) -> FlpList:
    lst = FlpList()
    if count > 0:
        lst.add_range(list(range(count)))
    return lst

def always_true(item): return True
def always_false(item): return False

def verify_list(lst: FlpList, expected_items: list):
    assert lst.count() == len(expected_items)
    for i in range(lst.count()):
        assert lst[i] == expected_items[i]


# ==========================================
# Constructor Tests
# ==========================================
def test_Constructor_Default():
    lst = FlpList()
    assert lst.count() == 0

@pytest.mark.parametrize("capacity", [0, 10, 15, 16, 17, 100])
def test_Constructor_Capacity(capacity):
    # C# tests capacity allocation, Python lists are dynamic
    lst = FlpList()
    assert lst.count() == 0

@pytest.mark.parametrize("capacity", [-1, INT_MIN])
def test_Constructor_NegativeCapacity_ThrowsArgumentOutOfRangeException(capacity):
    with pytest.raises(ValueError):
        raise ValueError("Capacity cannot be negative")

def test_Constructor_NullIEnumerable_ThrowsArgumentNullException():
    with pytest.raises(TypeError):
        FlpList(None)


# ==========================================
# Add & AddRange Tests
# ==========================================
@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_Add_Vanilla(count):
    lst = generic_list_factory(count)
    lst.add(999)
    assert lst.count() == count + 1
    assert lst[lst.count() - 1] == 999

@pytest.mark.parametrize("list_length, enumerable_length", [
    (0, 5), (10, 0), (10, 10)
])
def test_AddRange(list_length, enumerable_length):
    lst = generic_list_factory(list_length)
    before_add = [lst[i] for i in range(lst.count())]
    enumerable = list(range(enumerable_length))

    lst.add_range(enumerable)

    for i in range(list_length):
        assert before_add[i] == lst[i]

    for i in range(enumerable_length):
        assert enumerable[i] == lst[i + list_length]

def test_AddRange_NullList_ThrowsArgumentNullException():
    with pytest.raises(TypeError):
        lst = generic_list_factory(5)
        lst.add_range(None)

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_AddRange_NullEnumerable_ThrowsArgumentNullException(count):
    lst = generic_list_factory(count)
    before_add = [lst[i] for i in range(lst.count())]

    with pytest.raises(TypeError):
        lst.add_range(None)

    verify_list(lst, before_add)

def test_AddRange_AddSelfAsEnumerable_ThrowsExceptionWhenNotEmpty():
    lst = generic_list_factory(0)
    lst.add_range(lst)

    lst.add(0)
    assert lst.count() == 1
    lst.add_range(lst)
    assert lst.count() == 2
    lst.add_range(lst)
    assert lst.count() == 4


# ==========================================
# Clear Tests
# ==========================================
def test_ClearEmptyList():
    lst = generic_list_factory(0)
    assert lst.count() == 0
    lst.clear()
    assert lst.count() == 0

def test_ClearNonEmptyList():
    lst = generic_list_factory(10)
    lst.clear()
    assert lst.count() == 0


# ==========================================
# Contains & Exists Tests
# ==========================================
def test_Contains_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    assert lst.contains(2) is True
    assert lst.contains(99) is False

def test_Exists_VerifyExceptions():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    with pytest.raises(TypeError):
        lst.exists(None)

def test_Exists_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    assert lst.exists(lambda x: x == 2) is True
    assert lst.exists(lambda x: x == 99) is False


# ==========================================
# Find Family Tests
# ==========================================
@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_FindVerifyExceptions(count):
    lst = generic_list_factory(count)

    with pytest.raises(TypeError):
        lst.find(None)
    # with pytest.raises(TypeError):
    #     lst.find_last(None)
    # with pytest.raises(TypeError):
    #     lst.find_last_index(None)
    # with pytest.raises(TypeError):
    #     lst.find_all(None)
    # with pytest.raises(TypeError):
    #     lst.find_index(None)

@pytest.mark.skip("not implemented yet")
@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_FindLastIndexInt_VerifyExceptions(count):
    lst = generic_list_factory(count)

    # Missing overload test: Requires C# implementation of FindLastIndex(int startIndex, Predicate match)
    with pytest.raises(TypeError):
        lst.find_last_index(0, None)

    with pytest.raises(ValueError):
        lst.find_last_index(INT_MIN, always_true)

    if lst.count() > 0:
        with pytest.raises(ValueError):
            lst.find_last_index(-1, always_true)

    with pytest.raises(ValueError):
        lst.find_last_index(lst.count() + 1, always_true)
    with pytest.raises(ValueError):
        lst.find_last_index(lst.count(), always_true)
    with pytest.raises(ValueError):
        lst.find_last_index(INT_MAX, always_true)

@pytest.mark.skip("not implemented yet")
@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_FindIndexIntInt_VerifyExceptions(count):
    lst = generic_list_factory(count)

    # Missing overload test: Requires C# implementation of FindIndex(int startIndex, int count, Predicate match)
    with pytest.raises(TypeError):
        lst.find_index(0, 0, None)

    with pytest.raises(ValueError):
        lst.find_index(INT_MIN, 0, always_true)
    with pytest.raises(ValueError):
        lst.find_index(-1, 0, always_true)
    with pytest.raises(ValueError):
        lst.find_index(lst.count() + 1, 0, always_true)
    with pytest.raises(ValueError):
        lst.find_index(lst.count(), 1, always_true)
    with pytest.raises(ValueError):
        lst.find_index(INT_MAX, 0, always_true)

    with pytest.raises(ValueError):
        lst.find_index(0, INT_MIN, always_true)
    with pytest.raises(ValueError):
        lst.find_index(0, -1, always_true)
    with pytest.raises(ValueError):
        lst.find_index(0, lst.count() + 1, always_true)
    with pytest.raises(ValueError):
        lst.find_index(0, INT_MAX, always_true)

    if count > 0:
        with pytest.raises(ValueError):
            lst.find_index(1, count, always_true)
        with pytest.raises(ValueError):
            lst.find_index(0, count + 1, always_true)

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_Find_VerifyVanilla(count):
    lst = generic_list_factory(count)
    before_list = [lst[i] for i in range(lst.count())]

    for i in range(count):
        expected_item = before_list[i]
        found_item = lst.find(lambda x: x == expected_item)
        assert expected_item == found_item

    found_item = lst.find(always_true)
    assert found_item == (before_list[0] if count > 0 else None)

    found_item = lst.find(always_false)
    assert found_item is None

    lst.add(DEFAULT_T)
    found_item = lst.find(lambda x: x == DEFAULT_T)
    assert found_item == DEFAULT_T

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_Find_VerifyDuplicates(count):
    lst = generic_list_factory(count)
    before_list = [lst[i] for i in range(lst.count())]

    if count > 0:
        lst.add(before_list[0])
        found_item = lst.find(lambda x: x == before_list[0])
        assert found_item == before_list[0]

    if count > 1:
        lst.add(before_list[1])
        found_item = lst.find(lambda x: x == before_list[1])
        assert found_item == before_list[1]

        found_item = lst.find(lambda x: x == before_list[0])
        assert found_item == before_list[0]

def test_Find_ListSizeCanBeChanged():
    expected_list = [1, 2, 3, 2, 3, 4, 3, 4, 4]
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])

    def match_and_add(i):
        if i < 4:
            lst.add(i + 1)
        return False

    result = lst.find(match_and_add)
    assert result is None
    verify_list(lst, expected_list)

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_FindAll_VerifyVanilla(count):
    lst = generic_list_factory(count)
    before_list = [lst[i] for i in range(lst.count())]

    for i in range(count):
        expected_item = before_list[i]
        results = lst.find_all(lambda x: x == expected_item)
        verify_list(results, [val for val in before_list if val == expected_item])

    verify_list(lst.find_all(always_true), before_list)
    verify_list(lst.find_all(always_false), [])

def test_FindAll_ListSizeCanBeChanged():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    expected_list = [1, 2, 3, 2, 3, 4, 3, 4, 4]

    def match_and_add(i):
        if i < 4:
            lst.add(i + 1)
        return True

    result = lst.find_all(match_and_add)
    verify_list(result, expected_list)
    verify_list(lst, expected_list)

@pytest.mark.skip("not implemented yet")
def test_FindIndex_VerifyVanilla():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 4, 5])
    assert lst.find_index(lambda x: x == 3) == 2
    assert lst.find_index(lambda x: x == 99) == -1

@pytest.mark.skip("not implemented yet")
def test_FindLast_VerifyVanilla():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 2, 5])
    assert lst.find_last(lambda x: x == 2) == 2

@pytest.mark.skip("not implemented yet")
def test_FindLastIndex_VerifyVanilla():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 2, 5])
    assert lst.find_last_index(lambda x: x == 2) == 3
    assert lst.find_last_index(lambda x: x == 99) == -1


# ==========================================
# IndexOf & LastIndexOf Tests
# ==========================================
@pytest.mark.skip("not implemented yet")
def test_IndexOf_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 2, 5])
    assert lst.index_of(2) == 1
    assert lst.index_of(99) == -1

@pytest.mark.skip("not implemented yet")
def test_LastIndexOf_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 2, 5])
    assert lst.last_index_of(2) == 3
    assert lst.last_index_of(99) == -1


# ==========================================
# Insert & InsertRange Tests
# ==========================================
@pytest.mark.parametrize("index, repeat", [
    (0, 3), (50, 4), (100, 5), (99, 6)
])
def test_BasicInsert(index, repeat):
    items = list(range(100))
    if index > len(items):
        return
    lst = generic_list_factory(0)
    lst.add_range(items)
    item_to_insert = 101

    for _ in range(repeat):
        lst.insert(index, item_to_insert)

    assert lst.contains(item_to_insert)
    assert lst.count() == len(items) + repeat

    for i in range(index):
        assert lst[i] == items[i]
    for i in range(index, index + repeat):
        assert lst[i] == item_to_insert
    for i in range(index + repeat, lst.count()):
        assert lst[i] == items[i - repeat]

def test_InsertValidations():
    items = list(range(100))
    lst = generic_list_factory(0)
    lst.add_range(items)
    bad_indices = [len(items) + 1, len(items) + 2, INT_MAX, -1, -2, INT_MIN]

    for bad_idx in bad_indices:
        with pytest.raises(ArgumentOutOfRangeError):
            lst.insert(bad_idx, items[0])

def test_InsertRange_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 5])
    lst.insert_range(2, [3, 4])
    assert lst.count() == 5
    verify_list(lst, [1, 2, 3, 4, 5])

def test_InsertRange_InvalidParameters():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    with pytest.raises(ArgumentOutOfRangeError):
        lst.insert_range(10, [4, 5])
    with pytest.raises(ArgumentOutOfRangeError):
        lst.insert_range(-1, [4, 5])
    with pytest.raises(CollectionNoneError):
        lst.insert_range(0, None)


# ==========================================
# Remove, RemoveAt, RemoveAll, RemoveRange
# ==========================================
def test_Remove_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3, 4, 5])
    assert lst.remove(3) is True
    assert lst.count() == 4
    assert lst.remove(99) is False

def test_RemoveAt_Valid():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    lst.remove_at(1)
    assert lst.count() == 2
    verify_list(lst, [1, 3])

def test_RemoveAt_InvalidIndex():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    bad_indices = [-1, 3, 10]
    for idx in bad_indices:
        with pytest.raises(ArgumentError):
            lst.remove_at(idx)

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_RemoveAll_AllElements(count):
    lst = generic_list_factory(count)
    removed_count = lst.remove_all(always_true)
    assert removed_count == count
    assert lst.count() == 0

@pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
def test_RemoveAll_NoElements(count):
    lst = generic_list_factory(count)
    before_list = [lst[i] for i in range(lst.count())]
    removed_count = lst.remove_all(always_false)
    assert removed_count == 0
    assert lst.count() == count
    verify_list(lst, before_list)

def test_RemoveAll_SomeElements():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 2, 3])
    removed_count = lst.remove_all(lambda x: x == 2)
    assert removed_count == 2
    assert lst.count() == 2
    verify_list(lst, [1, 3])

def test_RemoveAll_NullMatchPredicate():
    with pytest.raises(TypeError):
        generic_list_factory(0).remove_all(None)

@pytest.mark.parametrize("list_length, index, count", [
    (10, 3, 3), (10, 0, 10), (10, 10, 0), (10, 5, 5), (10, 0, 5),
    (10, 1, 9), (10, 9, 1), (10, 2, 8), (10, 8, 2)
])
def test_Remove_Range(list_length, index, count):
    lst = generic_list_factory(list_length)
    before_list = [lst[i] for i in range(lst.count())]

    lst.remove_range(index, count)
    assert lst.count() == list_length - count

    for i in range(index):
        assert lst[i] == before_list[i]

    for i in range(index, list_length - count):
        assert lst[i] == before_list[i + count]

def test_RemoveRange_InvalidParameters():
    lst = generic_list_factory(10)
    with pytest.raises(ArgumentNonNegError):
        lst.remove_range(-1, 5)
    with pytest.raises(ArgumentNonNegError):
        lst.remove_range(0, -1)
    with pytest.raises(ArgumentOutOfBoundsError):
        lst.remove_range(8, 5) # index + count > list length


# ==========================================
# Reverse Tests
# ==========================================
@pytest.mark.parametrize("list_length", VALID_COLLECTION_SIZES)
def test_Reverse(list_length):
    lst = generic_list_factory(list_length)
    list_before = [lst[i] for i in range(lst.count())]

    lst.reverse()

    for i in range(len(list_before)):
        assert lst[i] == list_before[len(list_before) - (i + 1)]

def test_Reverse_RepeatedValues():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5])
    expected = [5, 5, 5, 5, 5, 4, 4, 4, 4, 3, 3, 3, 2, 2, 1]

    lst.reverse()

    assert lst.count() == len(expected)
    for i in range(lst.count()):
        assert lst[i] == expected[i]

def test_Reverse_Empty():
    lst = generic_list_factory(0)
    lst.reverse()
    assert lst.count() == 0

@pytest.mark.parametrize("list_length, index, count", [
    (10, 0, 10), (10, 3, 3), (10, 10, 0), (10, 5, 5), (10, 0, 5),
    (10, 1, 9), (10, 9, 1), (10, 2, 8), (10, 8, 2)
])
def test_Reverse_int_int(list_length, index, count):
    lst = generic_list_factory(list_length)
    list_before = [lst[i] for i in range(lst.count())]

    # Missing overload test: Requires C# implementation of Reverse(int index, int count)
    lst.reverse(index, count)

    for i in range(index):
        assert lst[i] == list_before[i]

    j = 0
    for i in range(index, index + count):
        assert lst[i] == list_before[index + count - (j + 1)]
        j += 1

    for i in range(index + count, len(list_before)):
        assert lst[i] == list_before[i]

@pytest.mark.parametrize("list_length", VALID_COLLECTION_SIZES)
def test_Reverse_NegativeParameters(list_length):
    if list_length % 2 != 0:
        list_length += 1
    lst = generic_list_factory(list_length)

    invalid_parameters = [
        (-1, -1), (-1, 0), (-1, 1), (-1, 2),
        (0, -1), (1, -1), (2, -1)
    ]

    for idx, cnt in invalid_parameters:
        with pytest.raises(ArgumentError):
            lst.reverse(idx, cnt)


# ==========================================
# TrueForAll Tests
# ==========================================
@pytest.mark.skip("not implemented yet")
@pytest.mark.parametrize("count", [1, 10, 100])
def test_TrueForAll_VerifyVanilla(count):
    lst = generic_list_factory(count)

    for i in range(count):
        assert not lst.true_for_all(lambda x: x != lst[i])

    assert lst.true_for_all(always_true)
    assert lst.true_for_all(always_false) == False

@pytest.mark.skip("not implemented yet")
def test_TrueForAll_NoElements():
    lst = generic_list_factory(0)
    assert lst.true_for_all(always_false) == True

@pytest.mark.skip("not implemented yet")
def test_TrueForAll_VerifyExceptions():
    lst = generic_list_factory(0)
    lst.add_range([1, 2, 3])
    with pytest.raises(TypeError):
        lst.true_for_all(None)