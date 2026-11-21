"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ConcurrentDictionary through the shared IDictionary / ICollection / IEnumerable suites, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentDictionary/ConcurrentDictionary.Generic.Tests.cs

One class per upstream key/value type: SimpleEnum, string, ulong, int.
"""
from __future__ import annotations

import random
from typing import Any, override

import pytest

from flpit.concurrent import ConcurrentDictionary
from flpit.core.comparers import IEqualityComparer

from nettests.common.collection_helpers import (
    VALID_COLLECTION_SIZES,
    EnumerableOrder,
    ModifyOperation,
    SimpleEnum,
    next_int,
    not_portable,
    random_base64,
)
from nettests.common.idictionary_generic_tests import IDictionaryGenericTests
from nettests.common.ienumerable_generic_tests import ModifyEnumerable, sequence_equal


class ConcurrentDictionaryGenericTests(IDictionaryGenericTests):
    # region IDictionary<TKey, TValue> Helper Methods

    enumerator_modified_during_enumeration_throws_invalid_operation_exception = False
    idictionary_generic_keys_values_enumeration_throws_invalid_operation_when_parent_modified = False
    idictionary_generic_keys_values_modifying_the_dictionary_updates_the_collection = False
    order = EnumerableOrder.UNSPECIFIED

    @override
    def generic_idictionary_factory(self, count: int | None = None) -> ConcurrentDictionary[Any, Any]:
        dictionary = ConcurrentDictionary[Any, Any]()
        if count is not None:
            self.add_to_collection(dictionary, count)
        return dictionary

    @override
    def generic_idictionary_factory_with_comparer(self, comparer: IEqualityComparer[Any]) -> ConcurrentDictionary[Any, Any]:
        return ConcurrentDictionary[Any, Any](comparer=comparer)

    @override
    def get_modify_enumerables(self, operations: ModifyOperation) -> list[ModifyEnumerable]:
        return []

    # endregion

    # region Constructors

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_Ctor_IDictionary(self, count: int) -> None:
        source = self.generic_idictionary_factory(count)
        copied = ConcurrentDictionary[Any, Any](source)
        assert sequence_equal(source.items(), copied.items())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_Ctor_IDictionary_IEqualityComparer(self, count: int) -> None:
        comparer = self.get_key_iequality_comparer()
        source = self.generic_idictionary_factory(count)
        copied = ConcurrentDictionary[Any, Any](source, comparer)
        assert sequence_equal(source.items(), copied.items())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_Ctor_IEqualityComparer(self, count: int) -> None:
        comparer = self.get_key_iequality_comparer()
        source = self.generic_idictionary_factory(count)
        copied = ConcurrentDictionary[Any, Any](source, comparer)
        assert sequence_equal(source.items(), copied.items())

    # endregion

    # region IReadOnlyDictionary<TKey, TValue>.Keys

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IReadOnlyDictionary_Generic_Keys_ContainsAllCorrectKeys(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        expected = [key for key, _ in dictionary.items()]
        assert sequence_equal(expected, dictionary.keys())

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IReadOnlyDictionary_Generic_Values_ContainsAllCorrectValues(self, count: int) -> None:
        dictionary = self.generic_idictionary_factory(count)
        expected = [value for _, value in dictionary.items()]
        assert sequence_equal(expected, dictionary.values())

    # endregion


class TestConcurrentDictionary_Generic_Tests_enum_enum(ConcurrentDictionaryGenericTests):
    default_value_allowed = True
    default_tkey = SimpleEnum(0)
    default_tvalue = SimpleEnum(0)

    @override
    def create_t(self, seed: int) -> tuple[SimpleEnum, SimpleEnum]:
        return self.create_tkey(seed), self.create_tvalue(seed)

    @override
    def create_tkey(self, seed: int) -> SimpleEnum:
        return SimpleEnum(next_int(seed))

    @override
    def create_tvalue(self, seed: int) -> SimpleEnum:
        return self.create_tkey(seed)


class TestConcurrentDictionary_Generic_Tests_string_string(ConcurrentDictionaryGenericTests):
    @override
    def create_t(self, seed: int) -> tuple[str, str]:
        return self.create_tkey(seed), self.create_tkey(seed + 500)

    @override
    def create_tkey(self, seed: int) -> str:
        return random_base64(seed)

    @override
    def create_tvalue(self, seed: int) -> str:
        return self.create_tkey(seed)

    @pytest.mark.parametrize("ignore_case", [False, True])
    def test_NonRandomizedToRandomizedUpgrade_FunctionsCorrectly(self, ignore_case: bool) -> None:
        not_portable("generates strings colliding in .NET's non-randomized string hash, read through reflection")


class TestConcurrentDictionary_Generic_Tests_ulong_ulong(ConcurrentDictionaryGenericTests):
    default_value_allowed = True
    default_tkey = 0
    default_tvalue = 0

    @override
    def create_t(self, seed: int) -> tuple[int, int]:
        key = self.create_tkey(seed)
        value = self.create_tkey(~seed)
        return key, value

    @override
    def create_tkey(self, seed: int) -> int:
        rand = random.Random(seed)
        hi = rand.randrange(2**31 - 1)
        lo = rand.randrange(2**31 - 1)
        return (hi << 32) | lo

    @override
    def create_tvalue(self, seed: int) -> int:
        return self.create_tkey(seed)


class TestConcurrentDictionary_Generic_Tests_int_int(ConcurrentDictionaryGenericTests):
    default_value_allowed = True
    default_tkey = 0
    default_tvalue = 0

    @override
    def create_t(self, seed: int) -> tuple[int, int]:
        rand = random.Random(seed)
        return rand.randrange(2**31 - 1), rand.randrange(2**31 - 1)

    @override
    def create_tkey(self, seed: int) -> int:
        return next_int(seed)

    @override
    def create_tvalue(self, seed: int) -> int:
        return self.create_tkey(seed)
