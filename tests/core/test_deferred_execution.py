from typing import List, TypeGuard
import flp
from flp import FlpIt

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


    def test_mutation_before_materialization(self):
        data = [1, 2, 3]
        query = flp.it(data).where(lambda x: x > 1)

        data.append(4)  # Mutating the original data source

        # Strict LINQ behavior dictates this should evaluate the mutated list!
        assert list(query) == [2, 3, 4]

    def test_the_chained_mutation_trap(self):
        data = [1, 2, 3]

        # What happens if the chain switches from Lazy to Eager, then back to Lazy?
        query = (
            flp.it(data)
            .where(lambda x: x > 1)      # Lazy (FlpIt)
            .to_list()                   # Eager Materialization (FlpList) -> Copies data?
            .where(lambda x: x < 4)      # Lazy again (FlpIt)
        )

        data.append(4)  # Mutating the root source after an eager step

        # Because 'to_list()' materialized the data mid-chain,
        # the new element '4' should NOT affect the final output!
        assert list(query) == [2, 3]


    def test_multiple_materialization_side_effects(self):
        data = [1, 2, 3]
        query = flp.it(data).where(lambda x: x > 1)

        # First materialization
        res1 = query.to_list()
        assert list(res1) == [2, 3]

        # Second materialization of the EXACT same query
        res2 = query.to_list()
        # If the internal state or generator isn't safely re-instantiated,
        # this will return an empty list [].
        assert list(res2) == [2, 3]

    def test_infinite_generator_handling(self):
        import itertools

        # An infinite generator: 1, 2, 3, 4, 5... infinitely
        infinite_counter = itertools.count(1)

        # If flp.it() or .where() triggers early evaluation, the runtime hangs/freezes
        query = flp.it(infinite_counter).where(lambda x: x % 2 == 0).take(3)

        # It must only evaluate up to the 3rd matching element right here
        assert list(query) == [2, 4, 6]


    def test_empty_sequence_terminal_guards(self):
        empty_query = flp.it([]).where(lambda x: x > 1)

        # Assure that your terminal guards raise clear, predictable errors
        # or follow .NET defaults (like returning None/raising ValueError)
        try:
            empty_query.min()
            assert False, "Should have raised an empty sequence exception"
        except Exception as e:
            # Assert your custom guard behavior handles the empty case safely
            assert isinstance(e, ValueError) or "empty" in str(e).lower()


    def test_type_narrowing_inference(self):
        from typing import Optional
        def is_not_none(x: Optional[str]) -> TypeGuard[str]:
            return x is not None

        data = ["target", None, "match"]
        query = flp.it(data).where(is_not_none)

        # Check your LSP insight inside this lambda!
        # Does 'x' show up as 'str' or still 'str | None'?
        final_query = query.select(lambda x: x.upper())

        assert list(final_query) == ["TARGET", "MATCH"]
