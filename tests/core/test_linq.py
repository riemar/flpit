from dataclasses import dataclass

import pytest
from typing import Callable


from flpit import flp, FlpIt, FlpList, ArgumentOutOfRangeError


@dataclass
class MyCustomType:
    age: int = 0
    name: str = ""

class Animal:
    """Base class for our polymorphism hierarchy."""
    pass

class Dog(Animal):
    """Subclass inheriting from Animal."""
    pass

class Cat():
    """Another valid subclass inheriting from Animal."""
    pass

class TestAdd:
    def test_whatever(self):
        lst = flp.lst([1,2,3])

    def test_linq_query_append_and_prepend_deferred_evaluation(self):
        """Test that append and prepend on FlpIt yield elements lazily without mutating the source."""
        original_data = [2, 3, 4]
        query = FlpIt(original_data)

        # Chain prepend and append
        modified_query = query.prepend(1).append(5)

        # Ensure deferred evaluation (original source remains unchanged)
        assert original_data == [2, 3, 4]

        # Iteration materializes the expected sequence
        assert list(modified_query) == [1, 2, 3, 4, 5]


    def test_linq_list_append_and_prepend_lazy_yield(self):
        """Test append and prepend called from FlpList return a lazy FlpIt."""
        numbers = FlpList([10, 20, 30])

        # Call prepend and append
        prepended_query = numbers.prepend(0)
        appended_query = numbers.append(40)

        # Verify return types are FlpIt instances
        assert isinstance(prepended_query, FlpIt)
        assert isinstance(appended_query, FlpIt)

        # Verify the underlying FlpList state is not mutated
        assert len(numbers) == 3
        assert numbers == [10, 20, 30]

        # Verify materialized sequence results
        assert prepended_query.to_list() == [0, 10, 20, 30]
        assert appended_query.to_list() == [10, 20, 30, 40]


    def test_append_and_prepend_chaining_with_linq_operators(self):
        """Test chaining append/prepend with other lazy LINQ operators like where and select."""
        query = FlpIt([2, 4, 6])

        result = (
            query.prepend(1)
            .append(7)
            .where(lambda x: x % 2 != 0)  # Filter odd numbers
            .select(lambda x: x * 10)
            .to_list()
        )

        # Expected odd numbers: 1, 7 -> multiplied by 10: 10, 70
        assert result == [10, 70]


    def test_append_and_prepend_on_empty_sequence(self):
        """Test append and prepend behavior on empty sequences."""
        empty_query: FlpIt[int] = FlpIt([])

        appended = empty_query.append(100).to_list()
        prepended = empty_query.prepend(200).to_list()

        assert appended == [100]
        assert prepended == [200]

    def test_concat_combines_sequences_in_order(self):
        result = FlpIt([1, 2, 3]).concat([4, 5, 6])

        assert result.to_list() == [1, 2, 3, 4, 5, 6]

    def test_concat_empty_first(self):
        result = FlpIt([]).concat([1, 2, 3])

        assert result.to_list() == [1, 2, 3]


    def test_concat_empty_second(self):
        result = FlpIt([1, 2, 3]).concat([])

        assert result.to_list() == [1, 2, 3]


    def test_concat_both_empty(self):
        result = FlpIt([]).concat([])

        assert result.to_list() == []


    def test_concat_preserves_order_and_duplicates(self):
        result = FlpIt([1, 2, 2]).concat([2, 3, 1])

        assert result.to_list() == [1, 2, 2, 2, 3, 1]


    def test_concat_is_lazy(self):
        consumed = []

        def source():
            consumed.append("first")
            yield 1
            consumed.append("second")
            yield 2

        query = FlpIt(source()).concat([3, 4])

        assert consumed == []

        assert query.first() == 1
        assert consumed == ["first"]

    def test_count_with_none_and_sentinel(self):
        """Test that count differentiates between no arguments and explicitly passing None."""
        list_with_nones: FlpList[int | None] = FlpList([1, None, 3, None, 5])

        # Scenario A: No arguments returns total element count
        assert list_with_nones.count() == 5


def test_count_with_predicates_and_values():
    """Test count functionality with LINQ predicates vs exact value matching."""
    numbers: FlpList[int] = FlpList([1, 2, 3, 4, 5, 6])

    # Scenario A: Matching via LINQ predicate (Callable)
    is_even: Callable[[int], bool] = lambda x: x % 2 == 0
    assert numbers.count(is_even) == 3


def test_where():
    data: FlpList[int] = FlpList[int]([1, 2, 3, 4, 5])
    res = data.where(lambda x: x % 2 == 0).select(lambda x: x).to_list()
    assert res == [2, 4]

    d2 = FlpList[int]([1, 2, 3, 4, 5])
    res = d2.where(lambda x: x % 2 == 0).select(lambda x: x).to_list()
    assert res == [2, 4]

def test_where_does_not_materialize():
    class InfiniteCounter:
        def __iter__(self):
            i = 0
            while True:
                yield i
                i += 1

    # Wenn where() intern list() aufruft, friert der Test hier ein / läuft in OOM
    query = FlpIt(InfiniteCounter()).where(lambda x: x % 2 == 0)
    it = iter(query)
    assert next(it) == 0
    assert next(it) == 2 # Exit freigegeben wurde

def test_select():
    lst = [1, 2, 3]
    data: FlpList[int] = FlpList(lst)
    res = data.select(lambda x: x * 2).to_list()
    assert res == [2, 4, 6]

def test_select_with_custom_type():

    data = FlpList([MyCustomType(2, "things"), MyCustomType(3, "stuff")])
    res = data.select(lambda x: x.age).to_list()

    assert res == [2, 3]


def test_select_many():
    data = FlpList([[1, 2], [3, 4], [5]])
    res = data.select_many(lambda x: x).to_list()
    assert res == [1, 2, 3, 4, 5]


def test_take():
    data = FlpList([1, 2, 3, 4, 5])
    assert data.take(3).to_list() == [1, 2, 3]
    assert data.take(0).to_list() == []
    assert data.take(-5).to_list() == []
    assert data.take(10).to_list() == [1, 2, 3, 4, 5]


def test_take_does_not_consume_upstream_beyond_limit():
    def tracking_stream():
        yield 10
        yield 20
        yield 30

    source = tracking_stream()

    result = FlpIt(source).take(1).to_list()

    assert result == [10]
    assert list(source) == [20, 30]


def test_take_is_deferred():
    consumed = []

    def source():
        consumed.append("started")
        yield 1
        consumed.append("second")
        yield 2

    query = FlpIt(source()).take(1)

    assert consumed == []

    assert query.to_list() == [1]
    assert consumed == ["started"]


def test_cast():
    data = FlpList([1, 2, 3])
    assert data.cast(int).to_list() == [1, 2, 3]

    invalid_data = FlpList([1, "two", 3])
    with pytest.raises(TypeError, match="Cannot cast element 'two'"):
        invalid_data.cast(int).to_list()


def test_group_by():
    data = FlpList(["apple", "banana", "apricot", "blueberry"])
    groups = data.group_by(lambda s: s[0]).to_list()

    assert len(groups) == 2
    assert groups[0].key == "a"
    assert groups[0].to_list() == ["apple", "apricot"]
    assert groups[1].key == "b"
    assert groups[1].to_list() == ["banana", "blueberry"]
    assert repr(groups[0]) == "Grouping(key='a', elements=['apple', 'apricot'])"


def test_count():
    data = FlpList([1, 2, 3, 4, 5])
    assert data.count() == 5
    assert data.count(lambda x: x > 3) == 2


def test_element_at():

    data = FlpList(["a", "b", "c"])
    assert data.element_at(0) == "a"
    assert data.element_at(2) == "c"

    with pytest.raises(ArgumentOutOfRangeError):
        data.element_at(3)

    with pytest.raises(ArgumentOutOfRangeError):
        data.element_at(-1)


def test_first_and_first_or_default():
    data = FlpList([1, 2, 3])
    assert data.first() == 1
    assert data.first(lambda x: x > 1) == 2

    with pytest.raises(ValueError, match="Sequence contains no matching elements"):
        data.first(lambda x: x > 10)

    assert data.first_or_default(99, lambda x: x > 10) == 99
    assert data.first_or_default(99, lambda x: x == 2) == 2


def test_single():
    data = FlpList([1, 2, 3])
    assert data.single(lambda x: x == 2) == 2

    with pytest.raises(ValueError, match="Sequence contains no matching elements"):
        data.single(lambda x: x == 99)

    with pytest.raises(ValueError, match="Sequence contains more than one matching element"):
        data.single(lambda x: x > 0)


# --- New Feature Tests ---

def test_distinct():
    data = FlpList([1, 2, 2, 3, 1, 4, 4, 4])
    assert data.distinct().to_list() == [1, 2, 3, 4]

    empty = FlpList([])
    assert empty.distinct().to_list() == []


def test_distinct_by():
    items = FlpList([
        {"id": 1, "val": "A"},
        {"id": 2, "val": "B"},
        {"id": 1, "val": "C"},
    ])
    res = items.distinct_by(lambda x: x["id"]).to_list()
    assert len(res) == 2
    assert res[0] == {"id": 1, "val": "A"}
    assert res[1] == {"id": 2, "val": "B"}


def test_aggregate():
    numbers = FlpList([1, 2, 3, 4])
    # Accumulation without seed
    assert numbers.aggregate(lambda acc, x: acc + x) == 10

    # Accumulation with seed
    assert numbers.aggregate(lambda acc, x: acc * x, seed=10) == 240

    # Custom accumulation type
    assert numbers.aggregate(lambda acc, x: f"{acc}-{x}", seed="start") == "start-1-2-3-4"

    empty = FlpList([])
    with pytest.raises(ValueError, match="Sequence contains no elements"):
        empty.aggregate(lambda acc, x: acc + x)

    assert empty.aggregate(lambda acc, x: acc + x, seed=42) == 42


def test_zip():
    nums = FlpList([1, 2, 3])
    strs = ["a", "b", "c", "d"]

    # Tuple projection default
    assert nums.zip(strs).to_list() == [(1, "a"), (2, "b"), (3, "c")]

    # Selector projection
    assert nums.zip(strs, lambda n, s: f"{n}:{s}").to_list() == ["1:a", "2:b", "3:c"]


def test_of_type():
    mixed = FlpList([1, "text", 2.5, True, "another", [1, 2]])
    assert mixed.of_type(str).to_list() == ["text", "another"]
    assert mixed.of_type(float).to_list() == [2.5]
    assert mixed.of_type(list).to_list() == [[1, 2]]


def test_chunk():
    data = FlpList([1, 2, 3, 4, 5, 6, 7])
    chunks = data.chunk(3).to_list()
    assert len(chunks) == 3
    assert chunks[0] == [1, 2, 3]
    assert chunks[1] == [4, 5, 6]
    assert chunks[2] == [7]

    # Verify inner structures are FlpList
    assert isinstance(chunks[0], FlpList)

    with pytest.raises(ValueError, match="Chunk size must be greater than 0"):
        data.chunk(0)

    with pytest.raises(ValueError, match="Chunk size must be greater than 0"):
        data.chunk(-1)


def test_min_and_min_by():
    numbers = FlpList([5, 2, 8, 1, 9])
    assert numbers.min() == 1

    objs = FlpList([{"name": "A", "age": 30}, {"name": "B", "age": 20}])
    assert objs.min_by(lambda x: x["age"]) == {"name": "B", "age": 20}

    empty = FlpList([])
    with pytest.raises(ValueError, match="Sequence contains no elements"):
        empty.min()
    with pytest.raises(ValueError, match="Sequence contains no elements"):
        empty.min_by(lambda x: x)


def test_max_and_max_by():
    numbers = FlpList([5, 2, 8, 1, 9])
    assert numbers.max() == 9

    objs = FlpList([{"name": "A", "age": 30}, {"name": "B", "age": 20}])
    assert objs.max_by(lambda x: x["age"]) == {"name": "A", "age": 30}

    empty = FlpList([])
    with pytest.raises(ValueError, match="Sequence contains no elements"):
        empty.max()
    with pytest.raises(ValueError, match="Sequence contains no elements"):
        empty.max_by(lambda x: x)


def test_ordering_chaining():
    data = FlpList([
        {"age": 30, "score": 90, "name": "Bob"},
        {"age": 20, "score": 80, "name": "Charlie"},
        {"age": 30, "score": 95, "name": "Alice"},
        {"age": 30, "score": 90, "name": "Aaron"},
    ])

    res = (
        data.order_by_descending(lambda x: x["age"])
        .then_by_descending(lambda x: x["score"])
        .then_by(lambda x: x["name"])
        .to_list()
    )

    assert res[0]["name"] == "Alice"  # age 30, score 95
    assert res[1]["name"] == "Aaron"  # age 30, score 90, name Aaron
    assert res[2]["name"] == "Bob"    # age 30, score 90, name Bob
    assert res[3]["name"] == "Charlie" # age 20


def test_as_type():
    data = FlpList([1, 2, 3])
    q = data.where(lambda x: x > 1)
    # Zero-cost type hint pass-through
    assert q.as_type(float) is q
    assert data.as_type(float) is data


def test_lazy_evaluation_guarantee():
    evaluated_count = 0

    def source_generator():
        nonlocal evaluated_count
        for i in range(10):
            evaluated_count += 1
            yield i

    query = (
        FlpIt(source_generator())
        .where(lambda x: x % 2 == 0)
        .distinct()
        .take(2)
    )

    # Must NOT run on query construction
    assert evaluated_count == 0

    # Iteration consumes minimum items needed
    result = query.to_list()
    assert result == [0, 2]
    assert evaluated_count == 3  # Yielded 0 (ok), 1 (filtered), 2 (ok, break)

class TestConsumableSources:
    def test_query_over_consumable_iterator_is_not_replayable(self):
        """A FlpIt over a consumable iterator does not cache or replay its source."""
        source = iter([1, 2, 3])
        query = flp.it(source)

        assert list(query) == [1, 2, 3]
        assert list(query) == []

    def test_materializing_query_consumes_consumable_source(self):
        """Materializing a FlpIt consumes the underlying consumable iterator."""
        source = iter([1, 2, 3])
        query = flp.it(source)

        assert query.to_list() == [1, 2, 3]
        assert query.to_list() == []

    def test_partial_iteration_leaves_consumable_source_at_current_position(self):
        """A partially consumed query resumes from the current position of its source."""
        source = iter([1, 2, 3, 4])
        query = flp.it(source)

        assert next(iter(query)) == 1
        assert list(query) == [2, 3, 4]

    def test_query_preserves_reusable_iterable_semantics(self):
        """Wrapping a reusable iterable does not make it artificially consumable."""
        source = [1, 2, 3]
        query = flp.it(source)

        assert list(query) == [1, 2, 3]
        assert list(query) == [1, 2, 3]

    def test_multiple_iterators_share_consumable_source(self):
        """Iterators over a query backed by a consumable source share its consumption state."""
        source = iter([1, 2, 3, 4])
        query = flp.it(source)

        first = iter(query)
        second = iter(query)

        assert next(first) == 1
        assert next(second) == 2
        assert list(first) == [3, 4]
        assert list(second) == []

from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_where_select_parity_with_python_native(data):
    # Vergleicht deine Implementierung gegen Pythons native Builtins über hunderte Zufallsdaten
    flp_res = list(FlpIt(data).where(lambda x: x % 2 == 0).select(lambda x: x * 2))
    py_res = [x * 2 for x in data if x % 2 == 0]
    assert flp_res == py_res

class TestSourdeExhaustion:
    @property
    def exhaustable(self):
        yield 1
        yield 2
        yield 3

    def test_range(self):
        it = flp.it(self.exhaustable)

        first = it.sum()
        second = it.sum()

        assert first == 6
        assert second == 0

    def test_range_native(self):
        it = self.exhaustable

        first = 0
        second = 0

        for x in it:
            first += x
        for x in it:
            second += x

        assert first == 6
        assert second == 0
