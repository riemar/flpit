import pytest
from flpit import flp, FlpList, FlpIt

class TestFlpList:

    def test_flplist_mutation_and_type_check(self):
        lst = FlpList([1, 2, 3])
        lst.add(4)
        assert lst == [1, 2, 3, 4]

        lst.add_range([5, 6])
        assert lst == [1, 2, 3, 4, 5, 6]

    def test_flplist_linq_chaining(self):
        lst: FlpList[int] = FlpList([1, 2, 3, 4, 5])
        
        # Querying a FlpList yields a lazy FlpIt instance
        query = lst.where(lambda x: x % 2 != 0).select(lambda x: x * 10)
        
        assert isinstance(query, FlpIt)
        assert list(query) == [10, 30, 50]

    def test_flplist_lazy_append_and_prepend(self):
        lst = FlpList([2, 3])
        
        appended = lst.append_linq(4)
        prepended = lst.prepend(1)
        
        # Ensure original list remains unmutated
        assert lst == [2, 3]
        
        assert list(appended) == [2, 3, 4]
        assert list(prepended) == [1, 2, 3]

    def test_flplist_empty_guard_decorators(self):
        empty_list = FlpList([])
        
        with pytest.raises(ValueError):
            empty_list.min()
            
        with pytest.raises(ValueError):
            empty_list.max()