import pytest
from typing import Union
from flpit import flp, FlpIt, FlpList

class TestFilteringAndProjection:
    
    @pytest.mark.parametrize("source,predicate,expected", [
        ([], lambda x: x > 0, []),
        ([1, 2, 3, 4, 5], lambda x: x % 2 == 0, [2, 4]),
        ([-1, -2, -3], lambda x: x > 0, []),
    ])
    def test_where_variations(self, non_collection, source, predicate, expected):
        query = FlpIt(non_collection(source)).where(predicate)
        assert list(query) == expected

    def test_select_projection_type_mutation(self):
        source = [1, 2, 3]
        query = FlpIt(source).select(lambda x: f"val_{x}")
        assert list(query) == ["val_1", "val_2", "val_3"]

    def test_select_many_flattens_nested_structures(self):
        data = [[1, 2], [], [3, 4, 5]]
        query = FlpIt(data).select_many(lambda x: x)
        assert list(query) == [1, 2, 3, 4, 5]

    def test_distinct_preserves_first_occurrence_order(self, run_once):
        source = run_once([1, 3, 2, 3, 1, 4, 2])
        query = FlpIt(source).distinct()
        assert list(query) == [1, 3, 2, 4]

    def test_distinct_by_key_selector(self):
        words = ["apple", "banana", "apricot", "blueberry", "cherry"]
        query = FlpIt(words).distinct_by(lambda s: s[0])
        assert list(query) == ["apple", "banana", "cherry"]

    def test_of_type_filters_by_class(self):
        mixed: list[Union[int, str, float]] = [1, "two", 3.0, "four", 5]
        query = FlpIt(mixed).of_type(str)
        assert list(query) == ["two", "four"]

    def test_cast_success(self):
        items = ["a", "b", "c"]
        query = FlpIt(items).cast(str)
        assert list(query) == ["a", "b", "c"]

    def test_cast_raises_type_error_on_failure(self):
        mixed = [1, "two", 3]
        query = FlpIt(mixed).cast(int)
        it = iter(query)
        assert next(it) == 1
        with pytest.raises((TypeError, ValueError)):
            next(it)

    def test_chunk_splitting(self, run_once):
        source = run_once([1, 2, 3, 4, 5, 6, 7])
        chunks = list(FlpIt(source).chunk(3))
        assert len(chunks) == 3
        assert list(chunks[0]) == [1, 2, 3]
        assert list(chunks[1]) == [4, 5, 6]
        assert list(chunks[2]) == [7]