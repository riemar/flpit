from __future__ import annotations

import pytest

import flp


class Animal:
    pass


class Dog(Animal):
    pass


class Cat(Animal):
    pass


def test_cast_accepts_matching_instances(flp_type) -> None:
    dogs = [Dog(), Dog()]
    result = list(flp_type(dogs).cast(Dog))
    assert result == dogs


def test_cast_is_lazy(flp_type) -> None:
    source = flp_type([Dog(), Cat(), Dog()]).cast(Dog)
    with pytest.raises(TypeError, match="Cannot cast element"):
        list(source)


def test_cast_rejects_wrong_type(flp_type) -> None:
    with pytest.raises(TypeError, match="Cat"):
        list(flp_type([Dog(), Cat()]).cast(Dog))


def test_of_type_filters_to_requested_type(flp_type) -> None:
    values = [Dog(), Cat(), Dog(), Animal()]
    result = list(flp_type(values).of_type(Dog))
    assert len(result) == 2
    assert all(isinstance(item, Dog) for item in result)


def test_of_type_uses_python_isinstance_semantics(flp_type) -> None:
    assert list(flp_type([True, 1, 2.0, "x"]).of_type(int)) == [True, 1]


def test_distinct_preserves_first_seen_order(flp_type) -> None:
    assert list(flp_type([3, 1, 3, 2, 1, 2]).distinct()) == [3, 1, 2]


def test_distinct_supports_repeated_enumeration_on_reiterable_source(flp_type) -> None:
    query = flp_type([1, 2, 1, 3]).distinct()
    assert list(query) == [1, 2, 3]
    assert list(query) == [1, 2, 3]


def test_distinct_by_preserves_first_item_for_each_key(flp_type) -> None:
    rows = [
        {"id": 1, "value": "a"},
        {"id": 2, "value": "b"},
        {"id": 1, "value": "c"},
    ]
    result = list(flp_type(rows).distinct_by(lambda row: row["id"]))
    assert result == rows[:2]


def test_distinct_raises_for_unhashable_values(flp_type) -> None:
    with pytest.raises(TypeError):
        list(flp_type([[1], [1]]).distinct())


def test_distinct_by_raises_for_unhashable_keys(flp_type) -> None:
    with pytest.raises(TypeError):
        list(flp_type([1, 2]).distinct_by(lambda x: [x]))


def test_zip_without_selector_returns_pairs(flp_type) -> None:
    assert list(flp_type([1, 2, 3]).zip([10, 20])) == [(1, 10), (2, 20)]


def test_zip_uses_shortest_input(flp_type) -> None:
    assert list(flp_type([1, 2]).zip([10, 20, 30])) == [(1, 10), (2, 20)]


def test_zip_result_selector_projects_pairs(flp_type) -> None:
    assert list(flp_type([1, 2, 3]).zip([10, 20, 30], lambda a, b: a + b)) == [11, 22, 33]


def test_zip_is_deferred(flp_type) -> None:
    seen = []
    query = flp_type([1, 2]).zip([3, 4], lambda a, b: seen.append((a, b)) or a + b)
    assert seen == []
    assert list(query) == [4, 6]
    assert seen == [(1, 3), (2, 4)]

