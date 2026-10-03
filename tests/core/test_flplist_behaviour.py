import pytest
from flpit import FlpList, FlpIt, SourceNoneError

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
        
        appended = lst.append(4)
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

# =====================================================================
# PYTEST SUITE FOR USERLIST BEHAVIORS
# =====================================================================

class TestFlpListUserListBehavior:

    # -----------------------------------------------------------------
    # Initialization & State
    # -----------------------------------------------------------------
    def test_init_without_source_creates_empty_list(self):
        """A missing source initializes an empty collection."""
        flp = FlpList()

        assert len(flp) == 0
        assert list(flp) == []

    def test_init_with_iterable_populates_data(self):
        """An iterable source is materialized into the underlying collection."""
        items = [1, 2, 3]

        flp = FlpList(items)
        assert len(flp) == len(items)
        assert list(flp) == items

    def test_init_with_generator_materializes_data(self):
        """A one-shot generator is consumed during initialization."""
        flp = FlpList(x * 2 for x in range(3))

        assert list(flp) == [0, 2, 4]

    def test_init_with_none_raises_source_none_error(self):
        """An explicit None source is rejected."""
        with pytest.raises(SourceNoneError):
            FlpList(None)

    # -----------------------------------------------------------------
    # Collection Protocol
    # -----------------------------------------------------------------
    def test_collection_protocol(self):
        """The wrapper exposes the expected collection protocol."""
        flp = FlpList(["a", "b", "c"])

        assert len(flp) == 3
        assert list(flp) == ["a", "b", "c"]
        assert "b" in flp
        assert "z" not in flp

    def test_iteration_preserves_order(self):
        """Enumeration yields elements in collection order."""
        flp = FlpList([3, 1, 2])

        assert list(iter(flp)) == [3, 1, 2]

    def test_empty_collection_is_not_contained(self):
        """An empty collection contains no elements."""
        flp = FlpList()

        assert len(flp) == 0
        assert list(flp) == []
        assert 1 not in flp

    # -----------------------------------------------------------------
    # Representation
    # -----------------------------------------------------------------
    def test_repr_matches_underlying_list(self):
        """repr() reflects the underlying list representation."""
        items = [1, 2, 3]
        flp = FlpList(items)

        assert repr(flp) == repr(items)

    def test_str_matches_underlying_list(self):
        """str() reflects the underlying list representation."""
        items = [1, 2, 3]
        flp = FlpList(items)

        assert str(flp) == str(items)

    # -----------------------------------------------------------------
    # Comparison Operations
    # -----------------------------------------------------------------
    @pytest.mark.parametrize(
        "left_items, right_items, expected_eq, expected_lt, expected_le, expected_gt, expected_ge",
        [
            ([1, 2], [1, 2], True,  False, True,  False, True),
            ([1, 2], [1, 3], False, True,  True,  False, False),
            ([1, 3], [1, 2], False, False, False, True,  True),
            ([1],    [1, 2], False, True,  True,  False, False),
            ([1, 2], [1],    False, False, False, True,  True),
            ([],     [],      True,  False, True,  False, True),
        ],
    )
    def test_comparisons_against_other_flplist(
            self,
            left_items,
            right_items,
            expected_eq,
            expected_lt,
            expected_le,
            expected_gt,
            expected_ge,
    ):
        """Rich comparisons follow the underlying sequence ordering semantics."""
        left = FlpList(left_items)
        right = FlpList(right_items)

        assert (left == right) is expected_eq
        assert (left != right) is not expected_eq
        assert (left < right) is expected_lt
        assert (left <= right) is expected_le
        assert (left > right) is expected_gt
        assert (left >= right) is expected_ge

    @pytest.mark.parametrize(
        "flp_items, raw_list, expected_eq, expected_lt, expected_le, expected_gt, expected_ge",
        [
            ([1, 2], [1, 2], True,  False, True,  False, True),
            ([1, 2], [1, 3], False, True,  True,  False, False),
            ([1, 3], [1, 2], False, False, False, True,  True),
            ([1],    [1, 2], False, True,  True,  False, False),
        ],
    )
    def test_comparisons_against_raw_list(
            self,
            flp_items,
            raw_list,
            expected_eq,
            expected_lt,
            expected_le,
            expected_gt,
            expected_ge,
    ):
        """Rich comparisons work against a standard Python list."""
        flp = FlpList(flp_items)

        assert (flp == raw_list) is expected_eq
        assert (flp != raw_list) is not expected_eq
        assert (flp < raw_list) is expected_lt
        assert (flp <= raw_list) is expected_le
        assert (flp > raw_list) is expected_gt
        assert (flp >= raw_list) is expected_ge

    # -----------------------------------------------------------------
    # Element Retrieval
    # -----------------------------------------------------------------
    def test_getitem_with_index(self):
        """Indexing returns the corresponding element."""
        flp = FlpList(["x", "y", "z"])

        assert flp[0] == "x"
        assert flp[1] == "y"
        assert flp[-1] == "z"
        assert flp[-3] == "x"

    @pytest.mark.parametrize("index", [3, -4, 100, -100])
    def test_getitem_with_out_of_range_index_raises_index_error(self, index):
        """Out-of-range indexing raises IndexError."""
        flp = FlpList(["x", "y", "z"])

        with pytest.raises(IndexError):
            _ = flp[index]

    # -----------------------------------------------------------------
    # Slicing
    # -----------------------------------------------------------------
    @pytest.mark.parametrize(
        "slice_",
        [
            slice(None),
            slice(1, 3),
            slice(None, None, 2),
            slice(None, None, -1),
            slice(10, 20),
            slice(-3, -1),
        ],
    )
    def test_getitem_with_slice_returns_flplist(self, slice_):
        """Slicing returns a new FlpList containing the selected elements."""
        items = [10, 20, 30, 40]
        flp = FlpList(items)

        sliced = flp[slice_]

        assert isinstance(sliced, FlpList)
        assert sliced is not flp
        assert list(sliced) == items[slice_]

    def test_slice_mutation_does_not_affect_source(self):
        """Mutating a slice does not mutate the source collection."""
        flp = FlpList([10, 20, 30, 40])

        sliced = flp[1:3]
        # sliced list append lazy back to list
        ll = sliced.append(99).to_list()
        sliced.add(99)

        assert list(sliced) == [20, 30, 99]
        assert list(ll) == [20, 30, 99]
        assert list(flp) == [10, 20, 30, 40]

    # -----------------------------------------------------------------
    # Boundary Cases
    # -----------------------------------------------------------------
    def test_empty_slice_returns_empty_flplist(self):
        """A valid empty slice still returns an FlpList."""
        flp = FlpList([1, 2, 3])

        sliced = flp[1:1]

        assert isinstance(sliced, FlpList)
        assert list(sliced) == []
        assert len(sliced) == 0

    def test_single_element_slice_returns_flplist_not_element(self):
        """A slice remains a collection even when it selects one element."""
        flp = FlpList([10, 20, 30])

        sliced = flp[1:2]

        assert isinstance(sliced, FlpList)
        assert list(sliced) == [20]

    # -----------------------------------------------------------------
    # Source Materialization / Ownership
    # -----------------------------------------------------------------
    def test_init_with_tuple_materializes_to_list(self):
        """Tuple input is materialized into the underlying list representation."""
        flp = FlpList((1, 2, 3))

        assert list(flp) == [1, 2, 3]

    def test_init_with_empty_iterable_creates_empty_list(self):
        """An empty iterable produces an empty collection."""
        flp = FlpList(iter(()))

        assert list(flp) == []
        assert len(flp) == 0

    def test_init_with_list_does_not_share_list_storage(self):
        """Initializing from a list does not accidentally alias the source list."""
        source = [1, 2, 3]
        flp = FlpList(source)

        source.append(4)

        assert source == [1, 2, 3, 4]
        assert list(flp) == [1, 2, 3]
