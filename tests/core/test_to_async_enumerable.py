"""
FlpIt / FlpList / Grouping ``to_async_enumerable()``: the sync -> async bridge.

The migrated .NET ToAsyncEnumerable tests live in tests/nettests/async_linq/test_to_async_enumerable.py;
these cover what they cannot: FlpList and Grouping (no .NET counterpart as separate types), not copying
the list, single-use vs re-enumerable sources and failing at the call site.
"""
import pytest

from flpit import AsyncFlpIt, flp


def items(query: AsyncFlpIt) -> list:
    return list(query.to_list().result())


def test_flplist_empty_list_is_not_the_shared_empty_sequence():
    assert flp.lst([]).to_async_enumerable() is not AsyncFlpIt.empty()  # a FlpList is mutable, like List<T>


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8, 6, -1, 5, 14]])
def test_flplist_matches_enumeration_and_is_re_enumerable(values):
    query = flp.lst(values).to_async_enumerable()
    assert items(query) == values
    assert items(query) == values


def test_flplist_is_not_copied_and_enumerates_lazily():
    source = flp.lst([1, 2, 3])
    query = source.to_async_enumerable()
    source.add(4)  # nothing was enumerated yet, so the first enumeration sees it
    assert items(query) == [1, 2, 3, 4]
    source.add(5)
    assert items(query) == [1, 2, 3, 4, 5]


def test_grouping_matches_enumeration():
    groups = flp.it([1, 2, 3, 4, 5]).group_by(lambda i: i % 2).to_list()
    assert {group.key: items(group.to_async_enumerable()) for group in groups} == {1: [1, 3, 5], 0: [2, 4]}


def test_ordered_it_keeps_its_order():
    assert items(flp.it([3, 1, 2]).order_by(lambda i: i).to_async_enumerable()) == [1, 2, 3]


def test_flpit_single_use_source_stays_single_use():
    query = flp.it(iter([1, 2, 3])).to_async_enumerable()
    assert items(query) == [1, 2, 3]
    assert items(query) == []


def test_flpit_re_enumerable_source_stays_re_enumerable():
    query = flp.it([1, 2, 3]).where(lambda i: i > 1).to_async_enumerable()
    assert items(query) == [2, 3]
    assert items(query) == [2, 3]


@pytest.mark.parametrize("bad", [5, 3.5, object()])
def test_not_iterable_fails_at_the_call_site(bad):
    # no deferred failure in the middle of a pipeline: the bridge and the wrapped query raise right away
    with pytest.raises(TypeError, match="neither async iterable nor iterable"):
        flp.ait(bad)
    with pytest.raises(TypeError, match="neither async iterable nor iterable"):
        flp.it(bad).to_async_enumerable()
