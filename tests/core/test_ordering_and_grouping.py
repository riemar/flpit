import pytest
from flp import FlpIt, Grouping

class TestOrderingAndGrouping:

    def test_order_by_ascending_and_descending(self):
        data = [3, 1, 4, 1, 5, 9, 2]
        assert list(FlpIt(data).order_by(lambda x: x)) == [1, 1, 2, 3, 4, 5, 9]
        assert list(FlpIt(data).order_by_descending(lambda x: x)) == [9, 5, 4, 3, 2, 1, 1]

    def test_multi_level_ordering_then_by(self):
        items = [
            {"cat": "A", "val": 2},
            {"cat": "B", "val": 1},
            {"cat": "A", "val": 1},
            {"cat": "B", "val": 2},
        ]
        query = (
            FlpIt(items)
            .order_by(lambda x: x["cat"])
            .then_by(lambda x: x["val"])
        )
        result = list(query)
        expected = [
            {"cat": "A", "val": 1},
            {"cat": "A", "val": 2},
            {"cat": "B", "val": 1},
            {"cat": "B", "val": 2},
        ]
        assert result == expected

    def test_order_by_stability(self):
        """Validates that equal keys retain their relative initial order."""
        data = [("a", 1), ("b", 1), ("c", 1)]
        result = list(FlpIt(data).order_by(lambda x: x[1]))
        assert result == [("a", 1), ("b", 1), ("c", 1)]

    def test_group_by_keys_and_elements(self):
        words = ["apple", "apricot", "banana", "bear", "cherry"]
        groups = list(FlpIt(words).group_by(lambda s: s[0]))

        assert len(groups) == 3
        
        # Verify Grouping interface
        g1 = groups[0]
        assert isinstance(g1, Grouping)
        assert g1.key == "a"
        assert list(g1) == ["apple", "apricot"]

        g2 = groups[1]
        assert g2.key == "b"
        assert list(g2) == ["banana", "bear"]


    def test_group_by_lazy_then_count(self):
        """
        1. ensures that calling count and others doesn't consume the source
        2. ensures that mimics .NET IGrouping in shape
        """
        words = ["apple", "apricot", "banana", "bear", "cherry"]
        groups = FlpIt(words).group_by(lambda s: s[0])
        c = groups.count()
        c = groups.first()
        c = groups.first_or_default(1)

        assert list(groups.select(lambda g: g)) == [Grouping(key='a', elements=['apple', 'apricot']),
                                              Grouping(key='b', elements=['banana', 'bear']),
                                              Grouping(key='c', elements=['cherry'])]

        recreated = groups.select_many(lambda g: g).to_list()
        assert recreated == words


    def test_ordered_it_second_iteration_data_loss(self):
        """
        Verifies if OrderedIt silently drops data on the second iteration
        when wrapped around a single-pass generator expression.
        """
        data = [3, 1, 2]
        expected = [1, 2, 3]

        # 1. Create a raw, forward-only generator expression containing three items
        raw_data = (x for x in data)

        # 2. Wrap it into the Fluent Iterable pipeline and sort it
        flp_iterable = FlpIt(raw_data)
        sorted_query = flp_iterable.order_by(lambda x: x)

        # 3. First execution pass: Materialize the query into a list
        # This consumes the generator completely under the hood.
        first_pass = list(sorted_query)
        assert first_pass == expected, "The first pass should sort the data cleanly."

        # 4. Second execution pass: Loop over the EXACT same query instance again
        # Native .NET LINQ caches the sorted result internally on the first run.
        second_pass = list(sorted_query)

        # --- CRITICAL ASSERTION ---
        # This will FAIL in your current implementation because second_pass returns an empty list []
        assert second_pass == expected, (
            f"FAIL: .NET behavior broken! Data was silently lost on the second pass. "
            f"Expected {expected} but got {second_pass} instead."
        )

    def test_deferred_exception_timing_lifecycle(self):
        """
        Proves that your new OrderedIt implementation is lazy:
        Initializing the iterator allocates nothing and does not throw.
        The sorting code and its errors explode ONLY on the first item lookup.
        """
        # 1. Create a volatile generator that actively raises an error when read
        def exploding_generator():
            yield 1
            raise RuntimeError("Upstream stream completely failed!")
            yield 2

        # 2. Wrap and apply our optimized sorting logic
        query = FlpIt(exploding_generator()).order_by(lambda x: x)

        # 3. INITIALIZATION STEP (iter)
        # No query evaluation occurs.
        query_iterator = iter(query)

        # 4. EXECUTION STEP (next)
        # The moment we request the first item, the generator wakes up,
        # attempts to read/sort the source, hits the RuntimeError, and blows up.
        with pytest.raises(RuntimeError) as exc_info:
            next(query_iterator)

        assert "Upstream stream completely failed!" in str(exc_info.value)


import gc
import weakref

# Assuming your classes are defined or imported here:
# from your_module import FlpIt, OrderedIt

class LargePayload:
    """A dummy class to track memory lifecycle via weak references."""
    def __init__(self, data: str):
        self.data = data


def test_ordered_it_memory_released_when_query_goes_out_of_scope():
    """
    OrderedIt intentionally caches its result so that a single-pass source
    can be iterated multiple times.

    The cached elements must be released when the OrderedIt itself becomes
    unreachable.
    """
    payload = LargePayload("heavy_dataset_xyz")
    tracker = weakref.ref(payload)

    def run_query():
        raw_generator = (x for x in [payload])
        query = FlpIt(raw_generator).order_by(lambda x: x.data)

        consumed_list = list(query)
        assert len(consumed_list) == 1

        # query and consumed_list disappear when this function returns.

    run_query()

    del payload
    gc.collect()

    assert tracker() is None, (
        "FAIL: Cached payload is still alive after OrderedIt "
        "went out of scope."
    )

def test_ordered_it_cache_released_with_query():
    payload = LargePayload("heavy_dataset_xyz")
    tracker = weakref.ref(payload)

    def run_query():
        query = FlpIt(
            (x for x in [payload])
        ).order_by(lambda x: x.data)

        list(query)

    run_query()

    del payload
    gc.collect()

    assert tracker() is None


def test_ordered_it_stable_then_by():
    items = [
        ("b", 2),
        ("a", 2),
        ("a", 1),
        ("b", 1),
    ]

    result = list(
        FlpIt(items)
        .order_by(lambda x: x[0])
        .then_by(lambda x: x[1])
    )

    assert result == [
        ("a", 1),
        ("a", 2),
        ("b", 1),
        ("b", 2),
    ]


def test_ordered_it_descending_then_by():
    items = [
        ("a", 1),
        ("a", 3),
        ("b", 2),
        ("b", 1),
    ]

    result = list(
        FlpIt(items)
        .order_by_descending(lambda x: x[0])
        .then_by(lambda x: x[1])
    )

    assert result == [
        ("b", 1),
        ("b", 2),
        ("a", 1),
        ("a", 3),
    ]

def test_ordered_it_source_consumed_once():
    calls = 0

    def generator():
        nonlocal calls
        calls += 1
        yield from [3, 1, 2]

    q = FlpIt(generator()).order_by(lambda x: x)

    assert list(q) == [1, 2, 3]
    assert list(q) == [1, 2, 3]
    assert calls == 1


def test_ordered_it_key_selector_called_once_per_item_per_node():
    calls = 0

    def key(x):
        nonlocal calls
        calls += 1
        return x

    q = FlpIt([3, 1, 2]).order_by(key)

    assert list(q) == [1, 2, 3]
    assert calls == 3

    assert list(q) == [1, 2, 3]
    assert calls == 3


def test_ordered_it_then_by_branches_are_independent():
    data = [
        ("b", 2),
        ("a", 1),
        ("b", 1),
        ("a", 2),
    ]

    root = FlpIt(data).order_by(lambda x: x[0])

    by_value = root.then_by(lambda x: x[1])
    by_value_desc = root.then_by_descending(lambda x: x[1])

    assert list(by_value) == [
        ("a", 1),
        ("a", 2),
        ("b", 1),
        ("b", 2),
    ]

    assert list(by_value_desc) == [
        ("a", 2),
        ("a", 1),
        ("b", 2),
        ("b", 1),
    ]

    # Root remains independently valid.
    assert list(root) == [
        ("a", 1),
        ("a", 2),
        ("b", 2),
        ("b", 1),
    ]


def test_ordered_it_parent_then_child():
    data = [(2, 1), (1, 2), (1, 1)]

    parent = FlpIt((x for x in data)).order_by(lambda x: x[0])
    child = parent.then_by(lambda x: x[1])

    assert list(parent) == [(1, 2), (1, 1), (2, 1)]
    assert list(child) == [(1, 1), (1, 2), (2, 1)]


def test_ordered_it_key_selector_exception_is_not_cached():
    calls = 0

    def key(x):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return x

    q = FlpIt([1, 2, 3]).order_by(key)

    with pytest.raises(RuntimeError, match="boom"):
        list(q)


def test_ordered_it_does_not_retain_upstream_source_after_materialization():
    class TrackedSource:
        def __iter__(self):
            yield from [3, 1, 2]

    source = TrackedSource()
    tracker = weakref.ref(source)

    flp = FlpIt(source)
    query = flp.order_by(lambda x: x)

    assert list(query) == [1, 2, 3]

    del flp
    del source
    gc.collect()

    assert tracker() is None


def test_ordered_query_does_not_see_separately_created_concat_query():
    """
        verified with .NET counterpart to behave the same
    """
    original = [
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
    ]

    # Create ordered query from original sequence
    ordered = FlpIt(original).order_by(lambda x: x["group"])

    # Create separate query from original sequence
    extended = FlpIt(original).concat(
        [
            {"group": "A", "value": 1},
            {"group": "B", "value": 2},
        ]
    )

    # Add secondary ordering to existing query
    ordered_with_secondary = ordered.then_by(lambda x: x["value"])

    result = ordered_with_secondary.to_list()

    expected = [
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
    ]

    assert result == expected

    # Separately created concatenated query remains unrelated
    assert extended.to_list() == [
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
        {"group": "A", "value": 1},
        {"group": "B", "value": 2},
    ]