import pytest
from typing import List
# Replace with actual import path
from flp import FlpIt, FlpList

class TestDeferredExecution:
    """Validates laziness and deferred evaluation invariants across operators."""

    def test_where_execution_is_deferred(self, tracker):
        evaluated = False

        def predicate(x: int) -> bool:
            nonlocal evaluated
            evaluated = True
            return x > 0

        source = FlpIt([1, 2, 3])
        query = source.where(predicate)

        # Asserts no side-effects occur before iteration starts
        assert not evaluated, "Where predicate evaluated prematurely during initialization."

        iterator = iter(query)
        assert not evaluated, "Where predicate evaluated on iter() creation before next()."

        next(iterator)
        assert evaluated, "Where predicate was not executed upon consuming first element."

    def test_select_execution_is_deferred(self, tracker):
        executed_count = 0

        def selector(x: int) -> int:
            nonlocal executed_count
            executed_count += 1
            return x * 2

        query = FlpIt([10, 20, 30]).select(selector)
        assert executed_count == 0

        it = iter(query)
        assert executed_count == 0

        next(it)
        assert executed_count == 1
        next(it)
        assert executed_count == 2

    def test_select_many_defers_flattening(self):
        invoked = False

        def selector(x: int) -> List[int]:
            nonlocal invoked
            invoked = True
            return [x, x + 1]

        query = FlpIt([1, 2]).select_many(selector)
        assert not invoked
        
        list(query)
        assert invoked

    def test_take_defers_and_stops_early(self):
        yielded_items = []

        def generator():
            for i in range(1, 100):
                yielded_items.append(i)
                yield i

        query = FlpIt(generator()).take(3)
        assert len(yielded_items) == 0

        result = list(query)
        assert result == [1, 2, 3]
        # Validates short-circuiting: should not iterate beyond count
        assert yielded_items == [1, 2, 3]

    def test_order_by_defers_sort_execution(self):
        evaluated = False

        def key_selector(x: int) -> int:
            nonlocal evaluated
            evaluated = True
            return x

        query = FlpIt([3, 1, 2]).order_by(key_selector)
        assert not evaluated, "Sorting key selector executed before iteration."

        res = list(query)
        assert evaluated
        assert res == [1, 2, 3]