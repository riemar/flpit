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

    def test_hash_join_execution(self):
        outer = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        inner = [{"owner_id": 1, "item": "Book"}, {"owner_id": 1, "item": "Pen"}, {"owner_id": 2, "item": "Car"}]

        joined = FlpIt(outer).join(
            inner=inner,
            outer_key_selector=lambda o: o["id"],
            inner_key_selector=lambda i: i["owner_id"],
            result_selector=lambda o, i: (o["name"], i["item"])
        )

        result = list(joined)
        assert len(result) == 3
        assert ("Alice", "Book") in result
        assert ("Alice", "Pen") in result
        assert ("Bob", "Car") in result