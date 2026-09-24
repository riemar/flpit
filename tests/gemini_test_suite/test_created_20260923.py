from __future__ import annotations

import itertools
import pytest
from pytest import param as pp

from typing import Any, Callable, Iterable, Iterator, Type

# noinspection protected-member
from flp.core.linq import (
    EmptySequenceError,
    NoMatchError,
    MultipleMatchesError,
    FlpIt,
    FlpList,
    Grouping,
    _FactoryIterable,
)


# ==============================================================================
# Domain Types & Test Helpers
# ==============================================================================

class DummyParent:
    pass


class DummyChild(DummyParent):
    pass


class Unsortable:
    def __init__(self, val: int):
        self.val = val


class Person:
    def __init__(self, name: str, age: int, dept: str):
        self.name = name
        self.age = age
        self.dept = dept

    def __eq__(self, other: Any) -> bool:
        return (
                isinstance(other, Person)
                and self.name == other.name
                and self.age == other.age
                and self.dept == other.dept
        )

    def __repr__(self) -> str:
        return f"Person({self.name!r}, {self.age}, {self.dept!r})"


def volatile_gen(data: Iterable[Any]) -> Iterator[Any]:
    """Generates a one-shot iterator to test generator consumption behavior."""
    yield from data


# ==============================================================================
# 1. Internal Infrastructure & Error Hierarchy
# ==============================================================================

class TestInfrastructure:
    def test_factory_iterable_produces_fresh_iterators(self):
        call_count = 0

        def factory() -> Iterator[int]:
            nonlocal call_count
            call_count += 1
            yield from [1, 2, 3]

        factory_it = _FactoryIterable(factory)
        assert list(factory_it) == [1, 2, 3]
        assert list(factory_it) == [1, 2, 3]
        assert call_count == 2


# ==============================================================================
# 2. FlpIt - Deferred Operations Matrix
# ==============================================================================

class TestFlpItDeferredOperations:

    @pytest.mark.parametrize(
        "initial, append_item, expected",
        [
            ([], 1, [1]),
            ([1, 2], 3, [1, 2, 3]),
            (["a"], "b", ["a", "b"]),
            ([None], None, [None, None]),
            ([1], [2], [1, [2]]),
        ],
    )
    def test_append(self, initial: list, append_item: Any, expected: list):
        assert FlpIt(initial).append(append_item).to_list() == expected

    @pytest.mark.parametrize(
        "initial, prepend_item, expected",
        [
            ([], 1, [1]),
            ([2, 3], 1, [1, 2, 3]),
            (["b"], "a", ["a", "b"]),
            ([None], None, [None, None]),
        ],
    )
    def test_prepend(self, initial: list, prepend_item: Any, expected: list):
        assert FlpIt(initial).prepend(prepend_item).to_list() == expected

    @pytest.mark.parametrize(
        "first, second, expected",
        [
            ([], [], []),
            ([1, 2], [], [1, 2]),
            ([], [3, 4], [3, 4]),
            ([1, 2], [3, 4], [1, 2, 3, 4]),
            (range(2), (2, 3), [0, 1, 2, 3]),
        ],
    )
    def test_concat(self, first: Iterable, second: Iterable, expected: list):
        assert FlpIt(first).concat(second).to_list() == expected

    @pytest.mark.parametrize(
        "data, predicate, expected",
        [
            ([], lambda x: True, []),
            ([1, 2, 3, 4, 5], lambda x: x % 2 == 0, [2, 4]),
            ([1, 2, 3, 4, 5], lambda x: x > 10, []),
            (["apple", "banana", "avocado"], lambda x: x.startswith("a"), ["apple", "avocado"]),
            ([True, False, True], lambda x: x, [True, True]),
        ],
    )
    def test_where(self, data: list, predicate: Callable[[Any], bool], expected: list):
        assert FlpIt(data).where(predicate).to_list() == expected

    @pytest.mark.parametrize(
        "data, selector, expected",
        [
            ([], lambda x: x, []),
            ([1, 2, 3], lambda x: str(x), ["1", "2", "3"]),
            (["a", "bb", "ccc"], len, [1, 2, 3]),
            ([{"k": 1}, {"k": 2}], lambda x: x["k"], [1, 2]),
        ],
    )
    def test_select(self, data: list, selector: Callable[[Any], Any], expected: list):
        assert FlpIt(data).select(selector).to_list() == expected

    @pytest.mark.parametrize(
        "data, selector, expected",
        [
            ([], lambda x: x, []),
            ([[1, 2], [3, 4]], lambda x: x, [1, 2, 3, 4]),
            (["hi", "bye"], lambda x: list(x), ["h", "i", "b", "y", "e"]),
            ([1, 2], lambda x: range(x), [0, 0, 1]),
            ([[], [1], []], lambda x: x, [1]),
        ],
    )
    def test_select_many(self, data: list, selector: Callable[[Any], Iterable], expected: list):
        assert FlpIt(data).select_many(selector).to_list() == expected

    @pytest.mark.parametrize(
        "data, count, expected",
        [
            ([1, 2, 3], -5, []),
            ([1, 2, 3], 0, []),
            ([1, 2, 3], 2, [1, 2]),
            ([1, 2, 3], 5, [1, 2, 3]),
            ([], 3, []),
        ],
    )
    def test_take(self, data: list, count: int, expected: list):
        assert FlpIt(data).take(count).to_list() == expected

    def test_take_infinite_generator(self):
        counter = itertools.count(1)
        assert FlpIt(counter).take(3).to_list() == [1, 2, 3]

    @pytest.mark.parametrize(
        "data, target_type, expected",
        [
            ([1, 2, 3], int, [1, 2, 3]),
            (["a", "b"], str, ["a", "b"]),
            ([DummyChild(), DummyChild()], DummyParent, None),
        ],
    )
    def test_cast_success(self, data: list, target_type: Type, expected: Any):
        if expected is None:
            expected = data
        assert FlpIt(data).cast(target_type).to_list() == expected

    def test_cast_failure_raises_type_error(self):
        with pytest.raises(TypeError, match="Cannot cast element 'str_val' of type str to int"):
            FlpIt([1, "str_val", 3]).cast(int).to_list()

    @pytest.mark.parametrize(
        "data, target_type, expected",
        [
            ([1, "a", 2, "b", 3.0], int, [1, 2]),
            ([1, "a", 2, "b", 3.0], str, ["a", "b"]),
            ([1, "a", 2, "b", 3.0], float, [3.0]),
            ([DummyParent(), DummyChild()], DummyChild, None),
            ([1, 2, 3], dict, []),
        ],
    )
    def test_of_type(self, data: list, target_type: Type, expected: Any):
        if expected is None:
            expected = [data[1]]
        assert FlpIt(data).of_type(target_type).to_list() == expected

    @pytest.mark.parametrize(
        "data, expected",
        [
            ([], []),
            ([1, 2, 2, 3, 1, 4], [1, 2, 3, 4]),
            (["a", "b", "a", "c"], ["a", "b", "c"]),
            ([None, 1, None, 2], [None, 1, 2]),
        ],
    )
    def test_distinct(self, data: list, expected: list):
        assert FlpIt(data).distinct().to_list() == expected

    @pytest.mark.parametrize(
        "data, key_selector, expected",
        [
            ([], lambda x: x, []),
            (["apple", "apricot", "banana"], lambda x: x[0], ["apple", "banana"]),
            ([{"id": 1, "v": "a"}, {"id": 1, "v": "b"}, {"id": 2, "v": "c"}], lambda x: x["id"], [{"id": 1, "v": "a"}, {"id": 2, "v": "c"}]),
        ],
    )
    def test_distinct_by(self, data: list, key_selector: Callable, expected: list):
        assert FlpIt(data).distinct_by(key_selector).to_list() == expected

    @pytest.mark.parametrize(
        "first, second, selector, expected",
        [
            ([1, 2, 3], ["a", "b"], None, [(1, "a"), (2, "b")]),
            ([1, 2], ["a", "b", "c"], None, [(1, "a"), (2, "b")]),
            ([1, 2], [10, 20], lambda a, b: a + b, [11, 22]),
            ([], [1, 2], None, []),
        ],
    )
    def test_zip(self, first: list, second: list, selector: Any, expected: list):
        assert FlpIt(first).zip(second, result_selector=selector).to_list() == expected

    @pytest.mark.parametrize(
        "data, size, expected",
        [
            ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]]),
            ([1, 2, 3, 4], 2, [[1, 2], [3, 4]]),
            ([1], 3, [[1]]),
            ([], 2, []),
        ],
    )
    def test_chunk(self, data: list, size: int, expected: list):
        chunks = FlpIt(data).chunk(size).to_list()
        assert [c.to_list() for c in chunks] == expected

    @pytest.mark.parametrize("invalid_size", [0, -1, -100])
    def test_chunk_invalid_size_raises_value_error(self, invalid_size: int):
        with pytest.raises(ValueError, match="Chunk size must be greater than 0."):
            FlpIt([1, 2, 3]).chunk(invalid_size)

    def test_as_type_identity(self):
        it = FlpIt([1, 2, 3])
        assert it.as_type(str) is it


# ==============================================================================
# 3. FlpIt - Aggregations & Terminal Operations
# ==============================================================================

class TestFlpItAggregations:

    def test_aggregate_without_seed(self):
        assert FlpIt([1, 2, 3, 4]).aggregate(lambda acc, x: acc + x) == 10
        assert FlpIt(["a", "b", "c"]).aggregate(lambda acc, x: acc + "," + x) == "a,b,c"

    def test_aggregate_with_seed(self):
        assert FlpIt([1, 2, 3]).aggregate(lambda acc, x: acc + x, seed=10) == 16
        assert FlpIt([]).aggregate(lambda acc, x: acc + x, seed=100) == 100

    def test_aggregate_empty_no_seed_raises(self):
        with pytest.raises(EmptySequenceError):
            FlpIt([]).aggregate(lambda acc, x: acc + x)

    @pytest.mark.parametrize(
        "data, expected_min, expected_max",
        [
            ([3, 1, 4, 2], 1, 4),
            (["c", "a", "z"], "a", "z"),
            ([-10, 0, 10], -10, 10),
            ([5], 5, 5),
        ],
    )
    def test_min_max(self, data: list, expected_min: Any, expected_max: Any):
        it = FlpIt(data)
        assert it.min() == expected_min
        assert it.max() == expected_max

    def test_min_max_empty_raises(self):
        with pytest.raises(EmptySequenceError):
            FlpIt([]).min()
        with pytest.raises(EmptySequenceError):
            FlpIt([]).max()

    def test_min_by_max_by(self):
        people = [
            Person("Alice", 30, "IT"),
            Person("Bob", 20, "HR"),
            Person("Charlie", 40, "IT"),
        ]
        it = FlpIt(people)
        assert it.min_by(lambda p: p.age) == Person("Bob", 20, "HR")
        assert it.max_by(lambda p: p.age) == Person("Charlie", 40, "IT")

    def test_min_by_max_by_empty_raises(self):
        with pytest.raises(EmptySequenceError):
            FlpIt([]).min_by(lambda x: x)
        with pytest.raises(EmptySequenceError):
            FlpIt([]).max_by(lambda x: x)

    @pytest.mark.parametrize(
        "data, selector, expected",
        [
            ([1, 2, 3, 4], None, 2.5),
            ([10, 20], None, 15.0),
            ([{"v": 10}, {"v": 30}], lambda x: x["v"], 20.0),
        ],
    )
    def test_average_and_aliases(self, data: list, selector: Any, expected: float):
        it = FlpIt(data)
        assert it.average(selector) == expected
        assert it.avg(selector) == expected
        if selector:
            assert it.average_by(selector) == expected
            assert it.avg_by(selector) == expected

    def test_average_empty_raises(self):
        with pytest.raises(EmptySequenceError):
            FlpIt([]).average()
        with pytest.raises(EmptySequenceError):
            FlpIt([]).average_by(lambda x: x)

    @pytest.mark.parametrize(
        "data, selector, expected",
        [
            ([], None, 0),
            ([1, 2, 3], None, 6),
            ([1.5, 2.5], None, 4.0),
            ([{"a": 5}, {"a": 15}], lambda x: x["a"], 20),
        ],
    )
    def test_sum(self, data: list, selector: Any, expected: Any):
        assert FlpIt(data).sum(selector) == expected

    @pytest.mark.parametrize(
        "data, predicate, expected",
        [
            ([], None, 0),
            ([1, 2, 3, 4], None, 4),
            ([1, 2, 3, 4], lambda x: x > 2, 2),
            ([1, 2, 3, 4], lambda x: x > 10, 0),
        ],
    )
    def test_count(self, data: list, predicate: Any, expected: int):
        assert FlpIt(data).count(predicate) == expected

    @pytest.mark.parametrize(
        "data, index, expected",
        [
            ([10, 20, 30], 0, 10),
            ([10, 20, 30], 2, 30),
        ],
    )
    def test_element_at_success(self, data: list, index: int, expected: Any):
        assert FlpIt(data).element_at(index) == expected

    @pytest.mark.parametrize(
        "data, index",
        [
            ([10, 20], -1),
            ([10, 20], 2),
            ([], 0),
        ],
    )
    def test_element_at_failure_raises_index_error(self, data: list, index: int):
        with pytest.raises(IndexError, match="Index out of range"):
            FlpIt(data).element_at(index)

    @pytest.mark.parametrize(
        "data, predicate, expected",
        [
            ([10, 20, 30], None, 10),
            ([1, 2, 3, 4], lambda x: x % 2 == 0, 2),
        ],
    )
    def test_first_success(self, data: list, predicate: Any, expected: Any):
        assert FlpIt(data).first(predicate) == expected

    def test_first_no_match_raises_value_error(self):
        with pytest.raises(NoMatchError):
            FlpIt([1, 3, 5]).first(lambda x: x % 2 == 0)
        with pytest.raises(EmptySequenceError):
            FlpIt([]).first()

    @pytest.mark.parametrize(
        "data, default, predicate, expected",
        [
            ([10, 20], -1, None, 10),
            ([1, 3, 5], 99, lambda x: x % 2 == 0, 99),
            ([], "default", None, "default"),
        ],
    )
    def test_first_or_default(self, data: list, default: Any, predicate: Any, expected: Any):
        assert FlpIt(data).first_or_default(default, predicate) == expected

    @pytest.mark.parametrize(
        "data, predicate, expected",
        [
            ([42], None, 42),
            ([1, 2, 3], lambda x: x == 2, 2),
        ],
    )
    def test_single_success(self, data: list, predicate: Any, expected: Any):
        if predicate is None:
            assert FlpIt(data).single() == expected
        else:
            assert FlpIt(data).single(predicate) == expected

@pytest.mark.parametrize(
    "data, predicate, exception",
    [
        # ([], None, EmptySequenceError), # doesn't seam feasible as no proper overload exists
        ([1, 2, 3], lambda x: x == 99, NoMatchError),
        ([1, 2, 3], None, TypeError),
        ([2, 4, 6], lambda x: x % 2 == 0, MultipleMatchesError),
    ],
)
def test_single_failures(
        data: list,
        predicate: Any,
        exception: type[ValueError],
):
    with pytest.raises(exception):
        FlpIt(data).single(predicate)


# ==============================================================================
# 4. Ordering & Chaining (OrderedIt)
# ==============================================================================

class TestOrderedItOperations:

    def test_order_by_and_descending_basic(self):
        data = [3, 1, 4, 1, 5, 9]
        assert FlpIt(data).order_by(lambda x: x).to_list() == [1, 1, 3, 4, 5, 9]
        assert FlpIt(data).order_by_descending(lambda x: x).to_list() == [9, 5, 4, 3, 1, 1]

    def test_multi_level_then_by_chaining(self):
        people = [
            Person("Charlie", 30, "IT"),
            Person("Alice", 20, "HR"),
            Person("Bob", 20, "IT"),
            Person("Alice", 20, "Finance"),
        ]

        # Primary: Age ASC, Secondary: Dept ASC, Tertiary: Name DESC
        result = (
            FlpIt(people)
            .order_by(lambda p: p.age)
            .then_by(lambda p: p.dept)
            .then_by_descending(lambda p: p.name)
            .to_list()
        )

        expected = [
            Person("Alice", 20, "Finance"),
            Person("Alice", 20, "HR"),
            Person("Bob", 20, "IT"),
            Person("Charlie", 30, "IT"),
        ]
        assert result == expected

    def test_ordered_it_caches_results_and_consumes_source_once(self):
        consumed = 0

        def stream():
            nonlocal consumed
            for i in [3, 1, 2]:
                consumed += 1
                yield i

        ordered = FlpIt(stream()).order_by(lambda x: x)

        res1 = list(ordered)
        assert res1 == [1, 2, 3]
        assert consumed == 3

        res2 = list(ordered)
        assert res2 == [1, 2, 3]
        assert consumed == 3  # Generator must NOT be called again

    def test_ordered_it_handles_equal_keys_stably(self):
        data = [{"k": 1, "v": "a"}, {"k": 1, "v": "b"}, {"k": 1, "v": "c"}]
        res = FlpIt(data).order_by(lambda x: x["k"]).to_list()
        assert res == data


# ==============================================================================
# 5. Grouping Operations
# ==============================================================================

class TestGroupingOperations:

    def test_group_by_basic(self):
        words = ["apple", "apricot", "banana", "blueberry", "cherry"]
        groups = FlpIt(words).group_by(lambda w: w[0]).to_list()

        assert len(groups) == 3
        assert groups[0].key == "a"
        assert groups[0].to_list() == ["apple", "apricot"]

        assert groups[1].key == "b"
        assert groups[1].to_list() == ["banana", "blueberry"]

        assert groups[2].key == "c"
        assert groups[2].to_list() == ["cherry"]

    def test_grouping_equality_and_repr(self):
        g1 = Grouping("key1", [1, 2, 3])
        g2 = Grouping("key1", [1, 2, 3])
        g3 = Grouping("key2", [1, 2, 3])
        g4 = Grouping("key1", [1, 2])

        assert g1 == g2
        assert g1 != g3
        assert g1 != g4
        assert g1 != "string_object"
        assert repr(g1) == "Grouping(key='key1', elements=[1, 2, 3])"


# ==============================================================================
# 6. FlpList Class & Overloads
# ==============================================================================

class TestFlpListSpecifics:

    def test_add_and_add_range_paths(self):
        flp_list = FlpList[int]()
        flp_list.add(1)

        # 1. Optimized Path (Sequences)
        flp_list.add_range([2, 3])
        flp_list.add_range((4, 5))

        # 2. Stream Path (Generators)
        flp_list.add_range(volatile_gen([6, 7]))

        # 3. Stream Path (Empty Generator)
        flp_list.add_range(volatile_gen([]))

        assert flp_list == [1, 2, 3, 4, 5, 6, 7]

    def test_to_list_isolation(self):
        orig = FlpList([1, 2, 3])
        copy_lst = orig.to_list()

        copy_lst.append(4)
        assert orig == [1, 2, 3]
        assert copy_lst == [1, 2, 3, 4]

    @pytest.mark.parametrize(
        "arg, expected",
        [
            pp((), 5, id="No_argument_total_length"),
            pp((lambda x: x % 2 == 0,), 3, id="LINQ_Predicate"),  # Fixed: 2, 2, 4 -> 3
            pp((2,), 2, id="Raw_exact_value_matching"),
            pp(("non_existent",), 0, id="Non_existent_value_matching"),
        ],
    )
    def test_count_overload_resolution(self, arg: tuple, expected: int):
        flp = FlpList([1, 2, 2, 3, 4])
        assert flp.count(*arg) == expected

    def test_guarded_empty_methods_on_flp_list(self):
        empty_list = FlpList[int]()

        with pytest.raises(EmptySequenceError):
            empty_list.min()

        with pytest.raises(EmptySequenceError):
            empty_list.min_by(lambda x: x)

        with pytest.raises(EmptySequenceError):
            empty_list.max()

        with pytest.raises(EmptySequenceError):
            empty_list.max_by(lambda x: x)

    def test_element_at_flp_list(self):
        flp = FlpList([100, 200])
        assert flp.element_at(0) == 100
        assert flp.element_at(1) == 200

        with pytest.raises(IndexError, match="Index out of range"):
            flp.element_at(-1)

        with pytest.raises(IndexError, match="Index out of range"):
            flp.element_at(2)

    def test_flp_list_linq_delegation(self):
        flp = FlpList([1, 2, 3, 4, 5])

        assert flp.where(lambda x: x > 3).to_list() == [4, 5]
        assert flp.select(lambda x: x * 10).to_list() == [10, 20, 30, 40, 50]
        assert flp.take(2).to_list() == [1, 2]
        assert flp.append_linq(6).to_list() == [1, 2, 3, 4, 5, 6]
        assert flp.prepend(0).to_list() == [0, 1, 2, 3, 4, 5]
        assert flp.sum() == 15
        assert flp.average() == 3.0


# ==============================================================================
# 7. Deep Chaining & Edge Case Combinations
# ==============================================================================

class TestComplexLINQChaining:

    def test_complex_query_pipeline(self):
        data = [
            {"name": "Alice", "score": 85, "active": True},
            {"name": "Bob", "score": 92, "active": False},
            {"name": "Charlie", "score": 92, "active": True},
            {"name": "David", "score": 60, "active": True},
            {"name": "Eve", "score": 98, "active": True},
        ]

        result = (
            FlpIt(data)
            .where(lambda x: bool(x["active"]))
            .order_by_descending(lambda x: x["score"])
            .then_by(lambda x: x["name"])
            .select(lambda x: x["name"])
            .take(2)
            .to_list()
        )

        assert result == ["Eve", "Charlie"]

    def test_nested_group_by_and_aggregations(self):
        numbers = range(1, 11)

        grouped_sums = (
            FlpIt(numbers)
            .group_by(lambda x: "even" if x % 2 == 0 else "odd")
            .select(lambda g: {"key": g.key, "sum": g.sum(), "avg": g.average()})
            .to_list()
        )

        assert grouped_sums == [
            {"key": "odd", "sum": 25, "avg": 5.0},
            {"key": "even", "sum": 30, "avg": 6.0},
        ]

    def test_generator_exhaustion_safety_in_chaining(self):
        def source():
            yield 1
            yield 2
            yield 3

        query = FlpIt(_FactoryIterable(source)).where(lambda x: x > 0)

        # First evaluation
        assert query.to_list() == [1, 2, 3]
        # Second evaluation should be completely re-run without issue
        assert query.to_list() == [1, 2, 3]


def test_flplist_count_with_callable_elements_fails():
    def my_fn(x: int) -> bool:
        return x > 0

    # List storing function references
    flp_list = FlpList([my_fn, my_fn])

    # INTENT: Count how many times `my_fn` appears in the list (expected: 2).
    # FAILURE: FlpList.count checks `if callable(item):` and executes `my_fn(item)`
    # where `item` is `my_fn` itself. This raises TypeError: '>' not supported between 'function' and 'int'.
    with pytest.raises(TypeError):
        flp_list.count(my_fn)


def test_flpit_min_masks_user_value_error():
    # Non-empty sequence containing invalid string data
    it = FlpIt(["1", "2", "invalid_number"])

    with pytest.raises(ValueError, match="invalid literal"):
        it.min_by(lambda x: int(x))


def test_zip_with_generator_second_argument_fails_on_reiteration():
    first = FlpIt([1, 2, 3])
    second_gen = (x for x in ["a", "b", "c"])  # One-shot generator

    zipped = first.zip(second_gen)

    # First iteration consumes `second_gen`
    assert list(zipped) == [(1, "a"), (2, "b"), (3, "c")]

    # FAILURE: Second iteration re-runs `first` via factory, but `second_gen`
    # is exhausted. `zip()` terminates immediately and returns []
    assert list(zipped) == []  # Expected [(1, "a"), (2, "b"), (3, "c")] if fully multi-pass


def test_ordered_it_parent_invalidated_by_child_iteration():
    def generator():
        yield from [3, 1, 2]

    # Source is a single-pass generator
    parent_ordered = FlpIt(generator()).order_by(lambda x: x)
    child_ordered = parent_ordered.then_by(lambda x: x)

    # Iterating child consumes generator and populates child_ordered._cached_result
    assert list(child_ordered) == [1, 2, 3]

    assert list(parent_ordered) == [1, 2, 3]  # Expected [1, 2, 3]


def test_distinct_on_unhashable_elements_raises_type_error():
    data = [{"id": 1}, {"id": 1}, {"id": 2}]
    it = FlpIt(data)

    # FAILURE: `item not in seen` raises TypeError: unhashable type: 'dict'
    with pytest.raises(TypeError, match="unhashable type"):
        it.distinct().to_list()



def test_ordered_then_concat_then_order():
    original = FlpIt([
        ("A", 2),
        ("B", 1),
    ])

    ordered = original.order_by(lambda x: x[0])

    extended = ordered.concat([
        ("A", 1),
        ("B", 2),
    ])

    result = (
        extended
        .order_by(lambda x: x[0])
        .then_by(lambda x: x[1])
    )

    assert list(result) == [
        ("A", 1),
        ("A", 2),
        ("B", 1),
        ("B", 2),
    ]

def test_ordered_then_concat_after_ordered_has_been_materialized():
    original = FlpIt([
        ("A", 2),
        ("B", 1),
    ])

    ordered = original.order_by(lambda x: x[0])

    assert list(ordered) == [
        ("A", 2),
        ("B", 1),
    ]

    extended = ordered.concat([
        ("A", 1),
        ("B", 2),
    ])

    result = (
        extended
        .order_by(lambda x: x[0])
        .then_by(lambda x: x[1])
    )

    assert list(result) == [
        ("A", 1),
        ("A", 2),
        ("B", 1),
        ("B", 2),
    ]


def test_ordered_it_created_then_source_concatenated_before_then_by():
    original = FlpIt([
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
    ])

    ordered = original.order_by(lambda x: x["group"])

    extended = original.concat([
        {"group": "A", "value": 1},
        {"group": "B", "value": 2},
    ])

    ordered_with_secondary = ordered.then_by(lambda x: x["value"])

    assert list(ordered_with_secondary) == [
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
    ]

    assert list(extended) == [
        {"group": "A", "value": 2},
        {"group": "B", "value": 1},
        {"group": "A", "value": 1},
        {"group": "B", "value": 2},
    ]