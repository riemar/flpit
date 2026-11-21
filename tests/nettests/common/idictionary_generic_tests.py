"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

The shared dictionary suite, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/Common/tests/System/Collections/IDictionary.Generic.Tests.cs
https://github.com/dotnet/runtime/blob/main/src/libraries/Common/tests/System/Collections/IDictionary.Generic.Tests.netcoreapp.cs

Abstract. Runs against flpit's .NET-shaped dictionary API: ``d[key]``, ``add``, ``try_add``,
``contains_key``, ``try_get_value``, ``try_remove`` (``IDictionary.Remove(key)`` is
``try_remove(key)[0]``), ``keys()`` / ``values()`` / ``items()``, and for
``ICollection<KeyValuePair>``: ``add(*pair)``, ``contains_item``, ``try_remove_item``, ``copy_to``.
Items are ``(key, value)`` tuples; the dictionary enumerates them through ``items()``.

Not portable, skipped: the ``Keys`` / ``Values`` enumerator ``Reset()`` tests and
``IDictionary_Generic_Remove_ReferenceRemovedFromCollection`` (weak references to int / str keys).
"""
from __future__ import annotations

from typing import Any

import pytest

from flpit.core.comparers import EqualityComparer, IEqualityComparer
from flpit.core.linq import ArgumentError, ArgumentNullError, KeyNotFoundError

from nettests.common.collection_helpers import (
    NO_RESET,
    NO_WEAKREF,
    VALID_COLLECTION_SIZES,
    EqualityComparerConstantHashCode,
    Enumerator,
    ModifyOperation,
    not_portable,
)
from nettests.common.icollection_generic_tests import ICollectionGenericTests
from nettests.common.ienumerable_generic_tests import ModifyEnumerable, sequence_equal

type Pair = tuple[Any, Any]


class KVPComparer(EqualityComparer[Pair]):
    """Compares pairs by key."""

    def __init__(self, equality_comparer: IEqualityComparer[Any]) -> None:
        self._equality_comparer = equality_comparer

    def equals(self, x: Pair, y: Pair) -> bool:
        return self._equality_comparer.equals(x[0], y[0])

    def get_hash_code(self, obj: Pair) -> int:
        return self._equality_comparer.get_hash_code(obj[0])


class IDictionaryGenericTests(ICollectionGenericTests[Pair]):
    # region IDictionary<TKey, TValue> Helper Methods

    default_tkey: Any = None
    default_tvalue: Any = None

    idictionary_generic_keys_values_enumeration_throws_invalid_operation_when_parent_modified = True
    idictionary_generic_keys_values_modifying_the_dictionary_updates_the_collection = True

    def generic_idictionary_factory(self, count: int | None = None) -> Any:
        raise NotImplementedError

    def generic_idictionary_factory_with_comparer(self, comparer: IEqualityComparer[Any]) -> Any:
        return None

    def create_tkey(self, seed: int) -> Any:
        raise NotImplementedError

    def create_tvalue(self, seed: int) -> Any:
        raise NotImplementedError

    def get_new_key(self, dictionary: Any) -> Any:
        seed = 840
        missing_key = self.create_tkey(seed)
        seed += 1
        while dictionary.contains_key(missing_key) or missing_key == self.default_tkey:
            missing_key = self.create_tkey(seed)
            seed += 1
        return missing_key

    def get_key_iequality_comparer(self) -> IEqualityComparer[Any]:
        return EqualityComparer.default()

    # endregion

    # region ICollection<KeyValuePair<TKey, TValue>> Helper Methods

    default_value_allowed = False
    duplicate_values_allowed = False
    t_is_value_type = True  # KeyValuePair is a struct

    @property
    def default_t(self) -> Pair:  # type: ignore[override]
        return self.default_tkey, self.default_tvalue

    def generic_icollection_factory(self, count: int | None = None) -> Any:
        return self.generic_idictionary_factory(count)

    def get_enumerator(self, enumerable: Any) -> Enumerator[Pair]:
        return Enumerator(iter(enumerable.items()))

    def collection_add(self, collection: Any, item: Pair) -> None:
        collection.add(*item)

    def collection_contains(self, collection: Any, item: Pair) -> bool:
        return bool(collection.contains_item(item))

    def collection_remove(self, collection: Any, item: Pair) -> bool:
        return bool(collection.try_remove_item(item))

    def add_to_collection(self, collection: Any, number_of_items_to_add: int) -> None:
        assert not self.is_read_only
        seed = 12353
        initial_count = len(collection)
        while len(collection) - initial_count < number_of_items_to_add:
            to_add = self.create_t(seed)
            seed += 1
            while collection.contains_key(to_add[0]) or to_add in self.invalid_values:
                to_add = self.create_t(seed)
                seed += 1
            self.collection_add(collection, to_add)

    def get_iequality_comparer(self) -> IEqualityComparer[Pair]:
        return KVPComparer(self.get_key_iequality_comparer())

    def get_modify_enumerables(self, operations: ModifyOperation) -> list[ModifyEnumerable]:
        modifications: list[ModifyEnumerable] = []
        if operations & ModifyOperation.ADD:
            def add(enumerable: Any) -> bool:
                enumerable.add(self.create_tkey(12), self.create_tvalue(5123))
                return True
            modifications.append(add)
        if operations & ModifyOperation.INSERT:
            def insert(enumerable: Any) -> bool:
                enumerable[self.create_tkey(541)] = self.create_tvalue(12)
                return True
            modifications.append(insert)
        if operations & ModifyOperation.OVERWRITE:
            def overwrite(enumerable: Any) -> bool:
                if len(enumerable) > 0:
                    enumerable[enumerable.keys()[0]] = self.create_tvalue(12)
                    return True
                return False
            modifications.append(overwrite)
        if operations & ModifyOperation.REMOVE:
            def remove(enumerable: Any) -> bool:
                if len(enumerable) > 0:
                    enumerable.try_remove(enumerable.keys()[0])
                    return True
                return False
            modifications.append(remove)
        if operations & ModifyOperation.CLEAR:
            def clear(enumerable: Any) -> bool:
                if len(enumerable) > 0:
                    enumerable.clear()
                    return True
                return False
            modifications.append(clear)
        return modifications

    # endregion

    # region Item Getter

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemGet_DefaultKey(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            if not self.default_value_allowed:
                with pytest.raises(ArgumentNullError):
                    _ = dictionary[self.default_tkey]
            else:
                value = self.create_tvalue(3452)
                dictionary[self.default_tkey] = value
                assert value == dictionary[self.default_tkey]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemGet_MissingNonDefaultKey_ThrowsKeyNotFoundException(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        missing_key = self.get_new_key(dictionary)
        with pytest.raises(KeyNotFoundError):
            _ = dictionary[missing_key]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemGet_MissingDefaultKey_ThrowsKeyNotFoundException(self, count: int) -> None:
        if self.default_value_allowed and not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.default_tkey
            while dictionary.contains_key(missing_key):
                dictionary.try_remove(missing_key)
            with pytest.raises(KeyNotFoundError):
                _ = dictionary[missing_key]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemGet_PresentKeyReturnsCorrectValue(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        for key, value in self.enumerate_items(dictionary):
            assert value == dictionary[key]

    # endregion

    # region Item Setter

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemSet_DefaultKey(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            if not self.default_value_allowed:
                with pytest.raises(ArgumentNullError):
                    dictionary[self.default_tkey] = self.create_tvalue(3)
            else:
                value = self.create_tvalue(3452)
                dictionary[self.default_tkey] = value
                assert value == dictionary[self.default_tkey]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemSet_OnReadOnlyDictionary_ThrowsNotSupportedException(self, count: int) -> None:
        if self.is_read_only:
            raise AssertionError("no read-only dictionaries are tested")

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemSet_AddsNewValueWhenNotPresent(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            dictionary[missing_key] = self.create_tvalue(543)
            assert count + 1 == len(dictionary)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ItemSet_ReplacesExistingValueWhenPresent(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            existing_key = self.get_new_key(dictionary)
            dictionary.add(existing_key, self.create_tvalue(5342))
            new_value = self.create_tvalue(1234)
            dictionary[existing_key] = new_value
            assert count + 1 == len(dictionary)
            assert new_value == dictionary[existing_key]

    # endregion

    # region Keys

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Keys_ContainsAllCorrectKeys(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        expected = [key for key, _ in self.enumerate_items(dictionary)]
        assert sequence_equal(expected, dictionary.keys())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Keys_ModifyingTheDictionaryUpdatesTheCollection(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            keys = dictionary.keys()
            previous_count = len(keys)
            if count > 0:
                assert keys
            dictionary.clear()
            if self.idictionary_generic_keys_values_modifying_the_dictionary_updates_the_collection:
                assert not keys
            else:
                assert previous_count == len(keys)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Keys_Enumeration_ParentDictionaryModifiedInvalidates(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            keys = dictionary.keys()
            keys_enum = Enumerator(iter(keys))
            dictionary.add(self.get_new_key(dictionary), self.create_tvalue(3432))
            throws = (
                self.enumerator_empty_modified_during_enumeration_throws_invalid_operation_exception if count == 0
                else self.idictionary_generic_keys_values_enumeration_throws_invalid_operation_when_parent_modified
            )
            if throws:
                with pytest.raises(Exception):  # noqa: B017 - .NET InvalidOperationException
                    keys_enum.move_next()
            else:
                if keys_enum.move_next():
                    _ = keys_enum.current
                # keysEnum.Reset(): not portable

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Keys_IsReadOnly(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        keys = dictionary.keys()
        # A tuple: read-only, like .NET's ReadOnlyCollection (NotSupportedException there).
        assert isinstance(keys, tuple)
        with pytest.raises(AttributeError):
            keys.append(self.create_tkey(11))  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            keys.clear()  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            keys.remove(self.create_tkey(11))  # type: ignore[attr-defined]

    def test_IDictionary_Generic_Keys_Enumeration_Reset(self) -> None:
        not_portable(NO_RESET)

    # endregion

    # region Values

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Values_ContainsAllCorrectValues(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        expected = [value for _, value in self.enumerate_items(dictionary)]
        assert sequence_equal(expected, dictionary.values())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Values_IncludeDuplicatesMultipleTimes(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            seed = 431
            for _, value in list(self.enumerate_items(dictionary)):
                missing_key = self.create_tkey(seed)
                seed += 1
                while dictionary.contains_key(missing_key):
                    missing_key = self.create_tkey(seed)
                    seed += 1
                dictionary.add(missing_key, value)
            assert count * 2 == len(dictionary.values())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Values_ModifyingTheDictionaryUpdatesTheCollection(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        values = dictionary.values()
        previous_count = len(values)
        if count > 0:
            assert values

        if not self.is_read_only:
            dictionary.clear()
            if self.idictionary_generic_keys_values_modifying_the_dictionary_updates_the_collection:
                assert not values
            else:
                assert previous_count == len(values)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Values_Enumeration_ParentDictionaryModifiedInvalidates(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            values = dictionary.values()
            values_enum = Enumerator(iter(values))
            dictionary.add(self.get_new_key(dictionary), self.create_tvalue(3432))
            throws = (
                self.enumerator_empty_modified_during_enumeration_throws_invalid_operation_exception if count == 0
                else self.idictionary_generic_keys_values_enumeration_throws_invalid_operation_when_parent_modified
            )
            if throws:
                with pytest.raises(Exception):  # noqa: B017 - .NET InvalidOperationException
                    values_enum.move_next()
            else:
                if values_enum.move_next():
                    _ = values_enum.current
                # valuesEnum.Reset(): not portable

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Values_IsReadOnly(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        values = dictionary.values()
        assert isinstance(values, tuple)
        with pytest.raises(AttributeError):
            values.append(self.create_tvalue(11))  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            values.clear()  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            values.remove(self.create_tvalue(11))  # type: ignore[attr-defined]

    def test_IDictionary_Generic_Values_Enumeration_Reset(self) -> None:
        not_portable(NO_RESET)

    # endregion

    # region Add(TKey, TValue)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_OnReadOnlyDictionary_ThrowsNotSupportedException(self, count: int) -> None:
        if self.is_read_only:
            raise AssertionError("no read-only dictionaries are tested")

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_DefaultKey_DefaultValue(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        missing_key = self.default_tkey
        value = self.default_tvalue
        if self.default_value_allowed and not self.is_read_only:
            dictionary.add(missing_key, value)
            assert count + 1 == len(dictionary)
            assert value == dictionary[missing_key]
        elif not self.is_read_only:
            with pytest.raises(ArgumentNullError):
                dictionary.add(missing_key, value)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_DefaultKey_NonDefaultValue(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        missing_key = self.default_tkey
        value = self.create_tvalue(1456)
        if self.default_value_allowed and not self.is_read_only:
            dictionary.add(missing_key, value)
            assert count + 1 == len(dictionary)
            assert value == dictionary[missing_key]
        elif not self.is_read_only:
            with pytest.raises(ArgumentNullError):
                dictionary.add(missing_key, value)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_NonDefaultKey_DefaultValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            value = self.default_tvalue
            dictionary.add(missing_key, value)
            assert count + 1 == len(dictionary)
            assert value == dictionary[missing_key]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_NonDefaultKey_NonDefaultValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            value = self.create_tvalue(1342)
            dictionary.add(missing_key, value)
            assert count + 1 == len(dictionary)
            assert value == dictionary[missing_key]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_DuplicateValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            seed = 321
            duplicate = self.create_tvalue(seed)
            seed += 1
            while duplicate in dictionary.values():
                duplicate = self.create_tvalue(seed)
                seed += 1
            dictionary.add(self.get_new_key(dictionary), duplicate)
            dictionary.add(self.get_new_key(dictionary), duplicate)
            assert 2 == sum(1 for value in dictionary.values() if value == duplicate)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_DuplicateKey(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            dictionary.add(missing_key, self.create_tvalue(34251))
            with pytest.raises(ArgumentError):
                dictionary.add(missing_key, self.create_tvalue(134))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_Add_DistinctValuesWithHashCollisions(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory_with_comparer(
                EqualityComparerConstantHashCode(EqualityComparer.default())
            )
            if dictionary is not None:
                self.add_to_collection(dictionary, count)
                assert count == len(dictionary)

    # endregion

    # region ContainsKey

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ContainsKey_ValidKeyNotContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            assert not dictionary.contains_key(missing_key)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ContainsKey_ValidKeyContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            dictionary.add(missing_key, self.create_tvalue(34251))
            assert dictionary.contains_key(missing_key)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ContainsKey_DefaultKeyNotContainedInDictionary(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        if self.default_value_allowed:
            if not self.is_read_only:
                missing_key = self.default_tkey
                while dictionary.contains_key(missing_key):
                    dictionary.try_remove(missing_key)
                assert not dictionary.contains_key(missing_key)
        else:
            with pytest.raises(ArgumentNullError):
                dictionary.contains_key(self.default_tkey)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_ContainsKey_DefaultKeyContainedInDictionary(self, count: int) -> None:
        if self.default_value_allowed and not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.default_tkey
            if not dictionary.contains_key(missing_key):
                dictionary.add(missing_key, self.create_tvalue(5341))
            assert dictionary.contains_key(missing_key)

    # endregion

    # region Remove(TKey)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_OnReadOnlyDictionary_ThrowsNotSupportedException(self, count: int) -> None:
        if self.is_read_only:
            raise AssertionError("no read-only dictionaries are tested")

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_EveryKey(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            for key in list(dictionary.keys()):
                assert dictionary.try_remove(key)[0]
            assert not self.enumerate_items(dictionary)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_ValidKeyNotContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            assert not dictionary.try_remove(missing_key)[0]
            assert count == len(dictionary)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_ValidKeyContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            dictionary.add(missing_key, self.create_tvalue(34251))
            assert dictionary.try_remove(missing_key)[0]
            assert count == len(dictionary)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_DefaultKeyNotContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            if self.default_value_allowed:
                missing_key = self.default_tkey
                while dictionary.contains_key(missing_key):
                    dictionary.try_remove(missing_key)
                assert not dictionary.try_remove(missing_key)[0]
            else:
                with pytest.raises(ArgumentNullError):
                    dictionary.try_remove(self.default_tkey)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_RemoveKey_DefaultKeyContainedInDictionary(self, count: int) -> None:
        if self.default_value_allowed and not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.default_tkey
            dictionary.try_add(missing_key, self.create_tvalue(5341))
            assert dictionary.try_remove(missing_key)[0]

    def test_IDictionary_Generic_Remove_ReferenceRemovedFromCollection(self) -> None:
        not_portable(NO_WEAKREF)

    # endregion

    # region TryGetValue

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_TryGetValue_ValidKeyNotContainedInDictionary(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        missing_key = self.get_new_key(dictionary)
        ok, _ = dictionary.try_get_value(missing_key)
        assert not ok

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_TryGetValue_ValidKeyContainedInDictionary(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            value = self.create_tvalue(5123)
            dictionary.try_add(missing_key, value)
            ok, out_value = dictionary.try_get_value(missing_key)
            assert ok
            assert value == out_value

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_TryGetValue_DefaultKeyNotContainedInDictionary(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        if self.default_value_allowed:
            if not self.is_read_only:
                missing_key = self.default_tkey
                while dictionary.contains_key(missing_key):
                    dictionary.try_remove(missing_key)
                ok, _ = dictionary.try_get_value(missing_key)
                assert not ok
        else:
            with pytest.raises(ArgumentNullError):
                dictionary.try_get_value(self.default_tkey)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IDictionary_Generic_TryGetValue_DefaultKeyContainedInDictionary(self, count: int) -> None:
        if self.default_value_allowed and not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.default_tkey
            value = self.create_tvalue(5123)
            dictionary.try_add(missing_key, value)
            ok, out_value = dictionary.try_get_value(missing_key)
            assert ok
            assert value == out_value

    # endregion

    # region ICollection<KeyValuePair<TKey, TValue>>

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_ValidPresentKeyWithDefaultValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            dictionary.add(missing_key, self.default_tvalue)
            assert dictionary.contains_item((missing_key, self.default_tvalue))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Remove_ValidPresentKeyWithDifferentValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            present = self.create_tvalue(324)
            missing = self.create_tvalue(5612)
            while present == missing:
                missing = self.create_tvalue(5612)
            dictionary.add(missing_key, present)
            assert not dictionary.try_remove_item((missing_key, missing))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_ValidPresentKeyWithDifferentValue(self, count: int) -> None:
        if not self.is_read_only:
            dictionary = self.generic_idictionary_factory(count)
            missing_key = self.get_new_key(dictionary)
            present = self.create_tvalue(324)
            missing = self.create_tvalue(5612)
            while present == missing:
                missing = self.create_tvalue(5612)
            dictionary.add(missing_key, present)
            assert not dictionary.contains_item((missing_key, missing))

    # endregion

    # region ICollection

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_NonGeneric_CopyTo(self, count: int) -> None:
        # Python has one list type: the generic and the object[] copies are the same call.
        dictionary = self.generic_idictionary_factory(count)
        array: list[Any] = [None] * count
        objarray: list[Any] = [None] * count
        dictionary.copy_to(array, 0)
        dictionary.copy_to(objarray, 0)
        for i in range(count):
            assert array[i] == objarray[i]

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_ICollection_Generic_Contains_DefaultValueWhenNotAllowed(self, count: int) -> None:
        collection = self.generic_idictionary_factory(count)
        if not self.default_value_allowed and not self.is_read_only:
            if self.default_value_when_not_allowed_throws:
                with pytest.raises(ArgumentNullError):
                    collection.contains_item(self.default_t)
            else:
                assert not collection.try_remove_item(self.default_t)

    # endregion

    # region KeyValuePair (netcoreapp)

    @pytest.mark.parametrize("size", VALID_COLLECTION_SIZES)
    def test_KeyValuePair_Deconstruct(self, size: int) -> None:
        dictionary = self.generic_idictionary_factory(size)
        for entry in self.enumerate_items(dictionary):
            key, value = entry
            assert entry[0] == key
            assert entry[1] == value

    # endregion
