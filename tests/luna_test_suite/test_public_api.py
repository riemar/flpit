from __future__ import annotations

from collections import UserList
import flpit
from flpit import flp, FlpIt, FlpList, Grouping, OrderedIt


def test_public_exports_are_present() -> None:
    assert flpit.FlpIt is FlpIt
    assert flpit.FlpList is FlpList
    assert flpit.Grouping is Grouping
    assert flpit.OrderedIt is OrderedIt
    assert callable(flp.it)
    assert callable(flp.lst)
    assert callable(flp.range)
    assert callable(flp.repeat)


def test_it_wraps_an_iterable() -> None:
    query = flp.it([1, 2, 3])
    assert isinstance(query, FlpIt)
    assert list(query) == [1, 2, 3]


def test_lst_materializes_an_iterable() -> None:
    result = flp.lst(x for x in range(3))
    assert isinstance(result, FlpList)
    assert list(result) == [0, 1, 2]


def test_range_uses_start_and_count_semantics() -> None:
    assert list(flp.range(5, 4)) == [5, 6, 7, 8]


def test_range_zero_is_empty() -> None:
    assert list(flp.range(5, 0)) == []


def test_range_negative_count_is_empty() -> None:
    assert list(flp.range(5, -3)) == []


def test_repeat_repeats_exactly_count_times() -> None:
    token = object()
    result = list(flp.repeat(token, 4))
    assert result == [token, token, token, token]
    assert all(item is token for item in result)


def test_repeat_zero_is_empty() -> None:
    assert list(flp.repeat(42, 0)) == []


def test_repeat_negative_is_empty() -> None:
    assert list(flp.repeat(42, -1)) == []


def test_as_type_returns_same_object() -> None:
    query = flp.it([1, 2, 3])
    assert query.as_type(str) is query


def test_flplist_is_a_userlist_and_sequence() -> None:
    result = FlpList([1, 2, 3])
    assert isinstance(result, FlpList)
    assert list(result) == [1, 2, 3]
    assert result[1] == 2


def test_flplist_is_mutable() -> None:
    result = FlpList([1])
    result[0] = 99
    assert result == [99]

