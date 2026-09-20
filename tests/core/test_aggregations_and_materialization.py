import pytest
from flp import FlpIt, FlpList

class TestAggregationsAndMaterialization:

    def test_first_with_and_without_predicate(self):
        assert FlpIt([10, 20, 30]).first() == 10
        assert FlpIt([10, 20, 30]).first(lambda x: x > 15) == 20

    def test_first_raises_value_error_on_empty_or_no_match(self):
        with pytest.raises(ValueError):
            FlpIt([]).first()
        with pytest.raises(ValueError):
            FlpIt([1, 2, 3]).first(lambda x: x > 100)

    def test_first_or_default(self):
        assert FlpIt([]).first_or_default(default=-1) == -1
        assert FlpIt([1, 2, 3]).first_or_default(default=-1, predicate=lambda x: x > 10) == -1
        assert FlpIt([1, 2, 3]).first_or_default(default=-1, predicate=lambda x: x == 2) == 2

    def test_single_contract(self):
        assert FlpIt([42]).single() == 42
        
        # Throws when sequence has more than one matching element
        with pytest.raises(ValueError):
            FlpIt([1, 2]).single()

        # Throws when sequence is empty
        with pytest.raises(ValueError):
            FlpIt([]).single()

    def test_aggregate_with_and_without_seed(self):
        # Without seed: x + y over [1, 2, 3, 4] -> 10
        assert FlpIt([1, 2, 3, 4]).aggregate(lambda acc, x: acc + x) == 10
        
        # With seed: initial 10 + sum([1, 2, 3]) -> 16
        assert FlpIt([1, 2, 3]).aggregate(lambda acc, x: acc + x, seed=10) == 16

    def test_min_max_and_by_variants(self):
        items = [{"val": 10}, {"val": 30}, {"val": 20}]
        
        assert FlpIt([5, 1, 9, 3]).min() == 1
        assert FlpIt([5, 1, 9, 3]).max() == 9
        
        assert FlpIt(items).min_by(lambda x: x["val"]) == {"val": 10}
        assert FlpIt(items).max_by(lambda x: x["val"]) == {"val": 30}

    def test_sum_and_average(self):
        assert FlpIt([1, 2, 3, 4]).sum() == 10
        assert FlpIt(["a", "bb", "ccc"]).sum(lambda s: len(s)) == 6
        assert FlpIt([10, 20, 30]).average() == 20.0
        assert FlpIt(["a", "bb"]).average_by(lambda s: len(s)) == 1.5

    def test_to_list_materialization(self, run_once):
        source = run_once([1, 2, 3])
        flp_list = FlpIt(source).to_list()
        
        assert isinstance(flp_list, FlpList)
        assert flp_list == [1, 2, 3]