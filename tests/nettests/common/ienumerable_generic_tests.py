"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

The shared enumeration suite, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/Common/tests/System/Collections/IEnumerable.Generic.Tests.cs
(and the generic part of TestBase.Generic.cs).

Abstract (pytest does not collect it): a collection's test class subclasses it and implements
``create_t`` / ``generic_ienumerable_factory`` / ``get_modify_enumerables``. ``get_enumerator``
turns a collection into an ``Enumerator`` (override it where .NET enumerates something other
than ``iter(collection)``, e.g. a dictionary's pairs).

Not portable, skipped: the ``Reset()`` tests (Python iterators cannot rewind) and the
``Current`` before-start / after-end "undefined behavior" probes (a Python iterator has no
``Current`` outside a step). ``RepeatTest`` therefore always takes a new enumerator, as upstream
does when ``ResetImplemented`` is false.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

import pytest

from nettests.common.collection_helpers import (
    NO_CURRENT,
    NO_RESET,
    VALID_COLLECTION_SIZES,
    EnumerableOrder,
    Enumerator,
    ModifyOperation,
    not_portable,
)

type ModifyEnumerable = Callable[[Any], bool]

_ALL_MODIFICATIONS = (
    ModifyOperation.ADD | ModifyOperation.INSERT | ModifyOperation.OVERWRITE | ModifyOperation.REMOVE | ModifyOperation.CLEAR
)


class IEnumerableGenericTests[T]:
    # region IEnumerable<T> Helper Methods

    modify_enumerator_throws: ModifyOperation = _ALL_MODIFICATIONS
    modify_enumerator_allowed: ModifyOperation = ModifyOperation.NONE
    enumerator_modified_during_enumeration_throws_invalid_operation_exception = True
    enumerator_empty_uses_singleton_instance = False
    order = EnumerableOrder.SEQUENTIAL

    @property
    def enumerator_empty_modified_during_enumeration_throws_invalid_operation_exception(self) -> bool:
        return self.enumerator_modified_during_enumeration_throws_invalid_operation_exception

    def create_t(self, seed: int) -> T:
        raise NotImplementedError

    def generic_ienumerable_factory(self, count: int) -> Any:
        raise NotImplementedError

    def get_modify_enumerables(self, operations: ModifyOperation) -> list[ModifyEnumerable]:
        raise NotImplementedError

    def get_enumerator(self, enumerable: Any) -> Enumerator[T]:
        return Enumerator(iter(enumerable))

    def enumerate_items(self, enumerable: Any) -> list[T]:
        """.NET ``enumerable.ToArray()`` / ``foreach``."""
        enumerator = self.get_enumerator(enumerable)
        items: list[T] = []
        while enumerator.move_next():
            items.append(enumerator.current)
        return items

    # endregion

    # region Validation

    def _repeat_test(self, test_code: Callable[[Enumerator[T], list[T], int], None], iters: int = 3) -> None:
        enumerable = self.generic_ienumerable_factory(32)
        items = self.enumerate_items(enumerable)
        enumerator = self.get_enumerator(enumerable)
        for i in range(iters):
            test_code(enumerator, items, i)
            enumerator = self.get_enumerator(enumerable)

    def _verify_enumerator(
            self,
            enumerator: Enumerator[T],
            expected_items: list[T],
            start_index: int = 0,
            count: int | None = None,
            validate_start: bool = True,
            validate_end: bool = True,
    ) -> None:
        if count is None:
            count = len(expected_items)
        need_to_match_all_expected_items = count - start_index == len(expected_items)

        # validate_start: the upstream Current probes before the first MoveNext are not portable.

        if self.order is EnumerableOrder.UNSPECIFIED:
            items_visited = [False] * (count if need_to_match_all_expected_items else len(expected_items))
            iterations = 0
            while iterations < count and enumerator.move_next():
                current_item = enumerator.current
                item_found = False
                for i in range(len(items_visited)):
                    expected = expected_items[i + (start_index if need_to_match_all_expected_items else 0)]
                    if not items_visited[i] and current_item == expected:
                        items_visited[i] = True
                        item_found = True
                        break
                assert item_found, "itemFound"

                for _ in range(3):
                    temp_item = enumerator.current
                    assert current_item == temp_item
                iterations += 1

            if need_to_match_all_expected_items:
                assert all(items_visited)
            else:
                assert count == sum(items_visited)
        elif self.order is EnumerableOrder.SEQUENTIAL:
            iterations = 0
            while iterations < count and enumerator.move_next():
                current_item = enumerator.current
                assert expected_items[iterations] == current_item
                for _ in range(3):
                    temp_item = enumerator.current
                    assert current_item == temp_item
                iterations += 1
        else:
            raise ValueError("EnumerableOrder is invalid.")

        assert count == iterations

        if validate_end:
            for _ in range(3):
                assert not enumerator.move_next(), "enumerator.MoveNext() returned true past the expected end."

    def _for_each_modification(
            self, operations: ModifyOperation, count: int, before: Callable[[Enumerator[T]], None],
            after: Callable[[Enumerator[T]], None],
    ) -> None:
        for modify_enumerable in self.get_modify_enumerables(operations):
            enumerable = self.generic_ienumerable_factory(count)
            with self.get_enumerator(enumerable) as enumerator:
                before(enumerator)
                if modify_enumerable(enumerable):
                    after(enumerator)

    def _modified_move_next(self, count: int) -> Callable[[Enumerator[T]], None]:
        def after(enumerator: Enumerator[T]) -> None:
            throws = (
                self.enumerator_empty_modified_during_enumeration_throws_invalid_operation_exception
                if count == 0 else self.enumerator_modified_during_enumeration_throws_invalid_operation_exception
            )
            if throws:
                with pytest.raises(Exception):  # noqa: B017 - .NET InvalidOperationException
                    enumerator.move_next()
            else:
                enumerator.move_next()

        return after

    # endregion

    # region GetEnumerator()

    def test_IEnumerable_NonGeneric_GetEnumerator_EmptyCollection_UsesSingleton(self) -> None:
        enumerable = self.generic_ienumerable_factory(0)
        enumerator1 = self.get_enumerator(enumerable)
        try:
            enumerator2 = self.get_enumerator(enumerable)
            try:
                assert self.enumerator_empty_uses_singleton_instance == (enumerator1.iterator is enumerator2.iterator)
            finally:
                enumerator2.dispose()
        finally:
            enumerator1.dispose()

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_GetEnumerator_NoExceptionsWhileGetting(self, count: int) -> None:
        enumerable = self.generic_ienumerable_factory(count)
        self.get_enumerator(enumerable).dispose()

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_GetEnumerator_ReturnsUniqueEnumerator(self, count: int) -> None:
        # Tests that the enumerators returned by GetEnumerator operate independently of one another
        enumerable = self.generic_ienumerable_factory(count)
        iterations = 0
        for _ in self.enumerate_items(enumerable):
            for _ in self.enumerate_items(enumerable):
                for _ in self.enumerate_items(enumerable):
                    iterations += 1
        assert count * count * count == iterations

    # endregion

    # region Enumerator.MoveNext

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_FromStartToFinish(self, count: int) -> None:
        iterations = 0
        with self.get_enumerator(self.generic_ienumerable_factory(count)) as enumerator:
            while enumerator.move_next():
                iterations += 1
            assert count == iterations

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_Enumerator_MoveNext_AfterDisposal(self, count: int) -> None:
        enumerator = self.get_enumerator(self.generic_ienumerable_factory(count))
        for _ in range(count):
            enumerator.move_next()
        enumerator.dispose()
        assert not enumerator.move_next()

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_AfterEndOfCollection(self, count: int) -> None:
        with self.get_enumerator(self.generic_ienumerable_factory(count)) as enumerator:
            for _ in range(count):
                enumerator.move_next()
            assert not enumerator.move_next()
            assert not enumerator.move_next()

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedBeforeEnumeration_ThrowsInvalidOperationException(self, count: int) -> None:
        self._for_each_modification(self.modify_enumerator_throws, count, lambda e: None, self._modified_move_next(count))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedBeforeEnumeration_Succeeds(self, count: int) -> None:
        def after(enumerator: Enumerator[T]) -> None:
            if self.enumerator_modified_during_enumeration_throws_invalid_operation_exception:
                enumerator.move_next()

        self._for_each_modification(self.modify_enumerator_allowed, count, lambda e: None, after)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedDuringEnumeration_ThrowsInvalidOperationException(self, count: int) -> None:
        def before(enumerator: Enumerator[T]) -> None:
            for _ in range(count // 2):
                enumerator.move_next()

        self._for_each_modification(self.modify_enumerator_throws, count, before, self._modified_move_next(count))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedDuringEnumeration_Succeeds(self, count: int) -> None:
        def before(enumerator: Enumerator[T]) -> None:
            for _ in range(count // 2):
                enumerator.move_next()

        self._for_each_modification(self.modify_enumerator_allowed, count, before, lambda e: e.move_next() and None)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedAfterEnumeration_ThrowsInvalidOperationException(self, count: int) -> None:
        def before(enumerator: Enumerator[T]) -> None:
            while enumerator.move_next():
                pass

        self._for_each_modification(self.modify_enumerator_throws, count, before, self._modified_move_next(count))

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_MoveNext_ModifiedAfterEnumeration_Succeeds(self, count: int) -> None:
        def before(enumerator: Enumerator[T]) -> None:
            while enumerator.move_next():
                pass

        self._for_each_modification(self.modify_enumerator_allowed, count, before, lambda e: e.move_next() and None)

    def test_IEnumerable_Generic_Enumerator_MoveNextHitsAllItems(self) -> None:
        def test_code(enumerator: Enumerator[T], items: list[T], _: int) -> None:
            iterations = 0
            while enumerator.move_next():
                iterations += 1
            assert len(items) == iterations

        self._repeat_test(test_code)

    def test_IEnumerable_Generic_Enumerator_MoveNextFalseAfterEndOfCollection(self) -> None:
        def test_code(enumerator: Enumerator[T], items: list[T], _: int) -> None:
            while enumerator.move_next():
                pass

            assert not enumerator.move_next()

        self._repeat_test(test_code)

    # endregion

    # region Enumerator.Current

    def test_IEnumerable_Generic_Enumerator_Current(self) -> None:
        # Verify that current returns proper result.
        def test_code(enumerator: Enumerator[T], items: list[T], iteration: int) -> None:
            if iteration == 1:
                self._verify_enumerator(enumerator, items, 0, len(items) // 2, True, False)
            else:
                self._verify_enumerator(enumerator, items)

        self._repeat_test(test_code)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_Current_ReturnsSameValueOnRepeatedCalls(self, count: int) -> None:
        with self.get_enumerator(self.generic_ienumerable_factory(count)) as enumerator:
            while enumerator.move_next():
                current = enumerator.current
                assert current == enumerator.current
                assert current == enumerator.current
                assert current == enumerator.current

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_Current_ReturnsSameObjectsOnDifferentEnumerators(self, count: int) -> None:
        # Ensures that the elements returned from enumeration are exactly the same collection of
        # elements returned from a previous enumeration
        enumerable = self.generic_ienumerable_factory(count)
        first_values = Counter(self._hashable(item) for item in self.enumerate_items(enumerable))
        second_values = Counter(self._hashable(item) for item in self.enumerate_items(enumerable))
        assert len(first_values) == len(second_values)
        for key in first_values:
            assert first_values[key] == second_values[key]

    @staticmethod
    def _hashable(item: Any) -> Any:
        return item

    def test_IEnumerable_Generic_Enumerator_Current_BeforeFirstMoveNext_UndefinedBehavior(self) -> None:
        not_portable(NO_CURRENT)

    def test_IEnumerable_Generic_Enumerator_Current_AfterEndOfEnumerable_UndefinedBehavior(self) -> None:
        not_portable(NO_CURRENT)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_Current_ModifiedDuringEnumeration_UndefinedBehavior(self, count: int) -> None:
        # Upstream reads Current after the modification; with no modifications listed (the
        # concurrent collections list none) the loop is empty, as upstream.
        self._for_each_modification(self.modify_enumerator_throws, count, lambda e: None, lambda e: None)

    @pytest.mark.parametrize("count", VALID_COLLECTION_SIZES)
    def test_IEnumerable_Generic_Enumerator_Current_ModifiedDuringEnumeration_Succeeds(self, count: int) -> None:
        self._for_each_modification(self.modify_enumerator_allowed, count, lambda e: None, lambda e: None)

    # endregion

    # region Enumerator.Reset

    def test_IEnumerable_Generic_Enumerator_Reset_BeforeIteration_Support(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedBeforeEnumeration_ThrowsInvalidOperationException(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedBeforeEnumeration_Succeeds(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedDuringEnumeration_ThrowsInvalidOperationException(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedDuringEnumeration_Succeeds(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedAfterEnumeration_ThrowsInvalidOperationException(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset_ModifiedAfterEnumeration_Succeeds(self) -> None:
        not_portable(NO_RESET)

    def test_IEnumerable_Generic_Enumerator_Reset(self) -> None:
        not_portable(NO_RESET)

    # endregion


def sequence_equal(first: Iterable[Any], second: Iterable[Any]) -> bool:
    """.NET ``Enumerable.SequenceEqual``."""
    return list(first) == list(second)
