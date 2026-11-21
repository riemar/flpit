"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

The shared collection suite, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/Common/tests/System/Collections/ICollection.Generic.Tests.cs

Abstract. ``ICollection<T>`` members map to hooks the subclass implements for its collection:
``collection_add`` / ``collection_contains`` / ``collection_remove`` (bool) / ``collection_clear``
/ ``collection_copy_to``; ``Count`` is ``len()``. ``default_t`` is ``default(T)``.
"""
from __future__ import annotations

import gc
import time
import weakref
from typing import Any

import pytest

from flpit.core.comparers import EqualityComparer, IEqualityComparer
from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError, NotSupportedError

from nettests.common.collection_helpers import VALID_COLLECTION_SIZES, ModifyOperation
from nettests.common.ienumerable_generic_tests import IEnumerableGenericTests, ModifyEnumerable, sequence_equal

INT_MIN = -2**31


class ICollectionGenericTests[T](IEnumerableGenericTests[T]):
    # region ICollection<T> Helper Methods

    duplicate_values_allowed = True
    default_value_when_not_allowed_throws = True
    is_read_only = False
    add_remove_clear_throws_not_supported = False
    default_value_allowed = True
    invalid_values: tuple[T, ...] = ()
    default_t: Any = None
    t_is_value_type = False
    copy_to_index_larger_than_array_count_throw_type: type[BaseException] = ArgumentError

    @property
    def is_read_only_validity_value(self) -> bool:
        return self.is_read_only

    def generic_icollection_factory(self, count: int | None = None) -> Any:
        raise NotImplementedError

    def collection_add(self, collection: Any, item: T) -> None:
        raise NotImplementedError

    def collection_contains(self, collection: Any, item: T) -> bool:
        raise NotImplementedError

    def collection_remove(self, collection: Any, item: T) -> bool:
        raise NotImplementedError

    def collection_clear(self, collection: Any) -> None:
        collection.clear()

    def collection_copy_to(self, collection: Any, array: list[T] | None, index: int) -> None:
        collection.copy_to(array, index)

    def collection_is_read_only(self, collection: Any) -> bool:
        return False

    def get_iequality_comparer(self) -> IEqualityComparer[T]:
        return EqualityComparer.default()

    def add_to_collection(self, collection: Any, number_of_items_to_add: int) -> None:
        seed = 9600
        comparer = self.get_iequality_comparer()
        while len(collection) < number_of_items_to_add:
            to_add = self.create_t(seed)
            seed += 1
            while (
                    any(comparer.equals(item, to_add) for item in self.enumerate_items(collection))
                    or any(comparer.equals(item, to_add) for item in self.invalid_values)
            ):
                to_add = self.create_t(seed)
                seed += 1
            self.collection_add(collection, to_add)

    # endregion

    # region IEnumerable<T> Helper Methods

    def generic_ienumerable_factory(self, count: int) -> Any:
        return self.generic_icollection_factory(count)

    def get_modify_enumerables(self, operations: ModifyOperation) -> list[ModifyEnumerable]:
        modifications: list[ModifyEnumerable] = []
        if not self.add_remove_clear_throws_not_supported and operations & ModifyOperation.ADD:
            def add(enumerable: Any) -> bool:
                self.collection_add(enumerable, self.create_t(2344))
                return True
            modifications.append(add)
        if not self.add_remove_clear_throws_not_supported and operations & ModifyOperation.REMOVE:
            def remove(enumerable: Any) -> bool:
                items = self.enumerate_items(enumerable)
                if items:
                    self.collection_remove(enumerable, items[0])
                    return True
                return False
            modifications.append(remove)
        if not self.add_remove_clear_throws_not_supported and operations & ModifyOperation.CLEAR:
            def clear(enumerable: Any) -> bool:
                if len(enumerable) > 0:
                    self.collection_clear(enumerable)
                    return True
                return False
            modifications.append(clear)
        return modifications

    # endregion

    @property
    def _can_modify(self) -> bool:
        return not self.is_read_only and not self.add_remove_clear_throws_not_supported

    # region IsReadOnly

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_IsReadOnly_Validity(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        assert self.is_read_only_validity_value == self.collection_is_read_only(collection)

    # endregion

    # region Count

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Count_Validity(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        assert count == len(collection)

    # endregion

    # region Add

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_DefaultValue(self, count: int) -> None:
        if self.default_value_allowed and self._can_modify:
            collection = self.generic_icollection_factory(count)
            self.collection_add(collection, self.default_t)
            assert count + 1 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_InvalidValueToMiddleOfCollection(self, count: int) -> None:
        if self._can_modify:
            for invalid_value in self.invalid_values:
                collection = self.generic_icollection_factory(count)
                self.collection_add(collection, invalid_value)
                for i in range(count):
                    self.collection_add(collection, self.create_t(i))
                assert count * 2 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_InvalidValueToBeginningOfCollection(self, count: int) -> None:
        if self._can_modify:
            for invalid_value in self.invalid_values:
                collection = self.generic_icollection_factory(0)
                self.collection_add(collection, invalid_value)
                for i in range(count):
                    self.collection_add(collection, self.create_t(i))
                assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_InvalidValueToEndOfCollection(self, count: int) -> None:
        if self._can_modify:
            for invalid_value in self.invalid_values:
                collection = self.generic_icollection_factory(count)
                self.collection_add(collection, invalid_value)
                assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_DuplicateValue(self, count: int) -> None:
        if self._can_modify and self.duplicate_values_allowed:
            collection = self.generic_icollection_factory(count)
            duplicate_value = self.create_t(700)
            self.collection_add(collection, duplicate_value)
            self.collection_add(collection, duplicate_value)
            assert count + 2 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_AfterCallingClear(self, count: int) -> None:
        if self._can_modify:
            collection = self.generic_icollection_factory(count)
            self.collection_clear(collection)
            self.add_to_collection(collection, 5)
            assert 5 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_AfterRemovingAnyValue(self, count: int) -> None:
        if self._can_modify:
            seed = 840
            collection = self.generic_icollection_factory(count)
            items = self.enumerate_items(collection)
            to_add = self.create_t(seed)
            seed += 1
            while self.collection_contains(collection, to_add):
                to_add = self.create_t(seed)
                seed += 1
            self.collection_add(collection, to_add)
            self.collection_remove(collection, to_add)

            to_add = self.create_t(seed)
            seed += 1
            while self.collection_contains(collection, to_add):
                to_add = self.create_t(seed)
                seed += 1

            self.collection_add(collection, to_add)
            items.append(to_add)
            # CollectionAsserts.EqualUnordered
            assert sorted(map(repr, items)) == sorted(map(repr, self.enumerate_items(collection)))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_AfterRemovingAllItems(self, count: int) -> None:
        if self._can_modify:
            collection = self.generic_icollection_factory(count)
            for _ in range(count):
                self.collection_remove(collection, self.enumerate_items(collection)[0])
            self.collection_add(collection, self.create_t(254))
            assert 1 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_ToReadOnlyCollection(self, count: int) -> None:
        if self.is_read_only or self.add_remove_clear_throws_not_supported:
            collection = self.generic_icollection_factory(count)
            with pytest.raises(NotSupportedError):
                self.collection_add(collection, self.create_t(0))
            assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Add_AfterRemoving(self, count: int) -> None:
        if self._can_modify:
            seed = 840
            collection = self.generic_icollection_factory(count)
            to_add = self.create_t(seed)
            seed += 1
            while self.collection_contains(collection, to_add):
                to_add = self.create_t(seed)
                seed += 1
            self.collection_add(collection, to_add)
            self.collection_remove(collection, to_add)
            self.collection_add(collection, to_add)

    # endregion

    # region Clear

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Clear(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        if self.is_read_only or self.add_remove_clear_throws_not_supported:
            with pytest.raises(NotSupportedError):
                self.collection_clear(collection)
            assert count == len(collection)
        else:
            self.collection_clear(collection)
            assert 0 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Clear_Repeatedly(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        if self.is_read_only or self.add_remove_clear_throws_not_supported:
            for _ in range(3):
                with pytest.raises(NotSupportedError):
                    self.collection_clear(collection)
            assert count == len(collection)
        else:
            for _ in range(3):
                self.collection_clear(collection)
            assert 0 == len(collection)

    @pytest.mark.parametrize("use_remove", [False, True])
    def test_ICollection_Generic_Remove_ReferenceRemovedFromCollection(self, use_remove: bool) -> None:
        if self.t_is_value_type or not self._can_modify:
            return

        collection = self.generic_icollection_factory()

        def populate_and_remove() -> weakref.ref[Any]:
            self.add_to_collection(collection, 1)
            value = self.enumerate_items(collection)[0]
            if use_remove:
                assert self.collection_remove(collection, value)
            else:
                self.collection_clear(collection)
                assert 0 == len(collection)
            return weakref.ref(value)

        wr = populate_and_remove()
        deadline = time.monotonic() + 30
        while wr() is not None and time.monotonic() < deadline:
            gc.collect()
        assert wr() is None

    # endregion

    # region Contains

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_ValidValueOnCollectionNotContainingThatValue(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        seed = 4315
        item = self.create_t(seed)
        seed += 1
        while self.collection_contains(collection, item):
            item = self.create_t(seed)
            seed += 1
        assert not self.collection_contains(collection, item)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_ValidValueOnCollectionContainingThatValue(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        for item in self.enumerate_items(collection):
            assert self.collection_contains(collection, item)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_DefaultValueOnCollectionNotContainingDefaultValue(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        if self.default_value_allowed and self.default_t is None:  # only reference types
            assert not self.collection_contains(collection, self.default_t)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_DefaultValueOnCollectionContainingDefaultValue(self, count: int) -> None:
        if self.default_value_allowed and self._can_modify:
            collection = self.generic_icollection_factory(count)
            self.collection_add(collection, self.default_t)
            assert self.collection_contains(collection, self.default_t)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_ValidValueThatExistsTwiceInTheCollection(self, count: int) -> None:
        if self.duplicate_values_allowed and self._can_modify:
            collection = self.generic_icollection_factory(count)
            item = self.create_t(12)
            self.collection_add(collection, item)
            self.collection_add(collection, item)
            assert count + 2 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_InvalidValue_ThrowsArgumentException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        for invalid_value in self.invalid_values:
            with pytest.raises(ArgumentError):
                self.collection_contains(collection, invalid_value)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_DefaultValueWhenNotAllowed(self, count: int) -> None:
        if not self.default_value_allowed and not self.is_read_only:
            collection = self.generic_icollection_factory(count)
            if self.default_value_when_not_allowed_throws:
                with pytest.raises(ArgumentNullError, match="'item'"):
                    self.collection_contains(collection, self.default_t)
            else:
                assert not self.collection_contains(collection, self.default_t)

    # endregion

    # region CopyTo

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_NullArray_ThrowsArgumentNullException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        with pytest.raises(ArgumentNullError):
            self.collection_copy_to(collection, None, 0)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_NegativeIndex_ThrowsArgumentOutOfRangeException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        array: list[Any] = [self.default_t] * count
        with pytest.raises(ArgumentOutOfRangeError):
            self.collection_copy_to(collection, array, -1)
        with pytest.raises(ArgumentOutOfRangeError):
            self.collection_copy_to(collection, array, INT_MIN)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_IndexEqualToArrayCount_ThrowsArgumentException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        array: list[Any] = [self.default_t] * count
        if count > 0:
            with pytest.raises(ArgumentError):
                self.collection_copy_to(collection, array, count)
        else:
            self.collection_copy_to(collection, array, count)  # does nothing since the array is empty

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_IndexLargerThanArrayCount_ThrowsAnyArgumentException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        array: list[Any] = [self.default_t] * count
        with pytest.raises(self.copy_to_index_larger_than_array_count_throw_type):
            self.collection_copy_to(collection, array, count + 1)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_NotEnoughSpaceInOffsettedArray_ThrowsArgumentException(self, count: int) -> None:
        if count > 0:  # Want the T array to have at least 1 element
            collection = self.generic_icollection_factory(count)
            array: list[Any] = [self.default_t] * count
            with pytest.raises(ArgumentError):
                self.collection_copy_to(collection, array, 1)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_ExactlyEnoughSpaceInArray(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        array: list[Any] = [self.default_t] * count
        self.collection_copy_to(collection, array, 0)
        assert sequence_equal(self.enumerate_items(collection), array)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_CopyTo_ArrayIsLargerThanCollection(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        array: list[Any] = [self.default_t] * (count * 3 // 2)
        self.collection_copy_to(collection, array, 0)
        assert sequence_equal(self.enumerate_items(collection), array[:count])

    # endregion

    # region Remove

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_OnReadOnlyCollection_ThrowsNotSupportedException(self, count: int) -> None:
        if self.is_read_only or self.add_remove_clear_throws_not_supported:
            collection = self.generic_icollection_factory(count)
            with pytest.raises(NotSupportedError):
                self.collection_remove(collection, self.create_t(34543))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_DefaultValueNotContainedInCollection(self, count: int) -> None:
        if self._can_modify and self.default_value_allowed and self.default_t not in self.invalid_values:
            collection = self.generic_icollection_factory(count)
            value = self.default_t
            while self.collection_contains(collection, value):
                self.collection_remove(collection, value)
                count -= 1
            assert not self.collection_remove(collection, value)
            assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_NonDefaultValueNotContainedInCollection(self, count: int) -> None:
        if self._can_modify:
            seed = count * 251
            collection = self.generic_icollection_factory(count)
            value = self.create_t(seed)
            seed += 1
            while self.collection_contains(collection, value) or value in self.invalid_values:
                value = self.create_t(seed)
                seed += 1
            assert not self.collection_remove(collection, value)
            assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_DefaultValueContainedInCollection(self, count: int) -> None:
        if self._can_modify and self.default_value_allowed and self.default_t not in self.invalid_values:
            collection = self.generic_icollection_factory(count)
            value = self.default_t
            if not self.collection_contains(collection, value):
                self.collection_add(collection, value)
                count += 1
            assert self.collection_remove(collection, value)
            assert count - 1 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_NonDefaultValueContainedInCollection(self, count: int) -> None:
        if self._can_modify:
            seed = count * 251
            collection = self.generic_icollection_factory(count)
            value = self.create_t(seed)
            if not self.collection_contains(collection, value):
                self.collection_add(collection, value)
                count += 1
            assert self.collection_remove(collection, value)
            assert count - 1 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_ValueThatExistsTwiceInCollection(self, count: int) -> None:
        if self._can_modify and self.duplicate_values_allowed:
            seed = count * 90
            collection = self.generic_icollection_factory(count)
            value = self.create_t(seed)
            self.collection_add(collection, value)
            self.collection_add(collection, value)
            count += 2
            assert self.collection_remove(collection, value)
            assert self.collection_contains(collection, value)
            assert count - 1 == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_EveryValue(self, count: int) -> None:
        if self._can_modify:
            collection = self.generic_icollection_factory(count)
            for value in self.enumerate_items(collection):
                assert self.collection_remove(collection, value)
            assert not self.enumerate_items(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_InvalidValue_ThrowsArgumentException(self, count: int) -> None:
        collection = self.generic_icollection_factory(count)
        for value in self.invalid_values:
            with pytest.raises(ArgumentError):
                self.collection_remove(collection, value)
        assert count == len(collection)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_DefaultValueWhenNotAllowed(self, count: int) -> None:
        if not self.default_value_allowed and self._can_modify:
            collection = self.generic_icollection_factory(count)
            if self.default_value_when_not_allowed_throws:
                with pytest.raises(ArgumentNullError):
                    self.collection_remove(collection, self.default_t)
            else:
                assert not self.collection_remove(collection, self.default_t)

    # endregion
