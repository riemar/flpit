"""
FlpIt-specific behaviour of group_join.

The .NET port lives in tests/nettests/linq/test_group_join.py. This module covers the architectural
invariants from .agents/rules.md (deferred execution, no consumption on construction, single-use sources,
streaming, O(N + M) key-selector usage) and the group_join-specific contract:

    * exactly one result per outer element, in outer order, unmatched ones with an empty group,
    * like .NET, ``inner`` is only enumerated once the outer sequence yields its first element,
    * each group is a re-enumerable snapshot that is independent of the internal lookup and of other groups,
    * without a result selector a ``Grouping`` keyed by the *outer element itself* is yielded.
"""
import pytest

from flpit import flp, FlpIt, FlpList, Grouping


class Tracked:
    """Re-iterable source that records how often / how far it was enumerated."""

    def __init__(self, items):
        self.items = list(items)
        self.iter_calls = 0
        self.yielded = 0

    def __iter__(self):
        self.iter_calls += 1
        for item in self.items:
            self.yielded += 1
            yield item


def _ident(x):
    return x


# ---------------------------------------------------------------------------
# Architectural invariants
# ---------------------------------------------------------------------------

def test_returns_deferred_flpit(flp_type):
    result = flp_type([1]).group_join([1], _ident, _ident)

    assert type(result) is FlpIt


def test_construction_does_not_consume_or_call_anything():
    outer, inner = Tracked([1, 2]), Tracked([2, 3])
    calls = []

    flp.it(outer).group_join(
        inner,
        lambda x: calls.append("ok") or x,
        lambda x: calls.append("ik") or x,
        lambda o, g: calls.append("rs") or (o, g),
    )

    assert (outer.iter_calls, inner.iter_calls, calls) == (0, 0, [])


def test_one_shot_sources_are_not_touched_on_construction():
    outer_gen = (x for x in [1, 2])
    inner_gen = (x for x in [2, 3])

    query = flp.it(outer_gen).group_join(inner_gen, _ident, _ident)

    assert next(outer_gen) == 1 and next(inner_gen) == 2  # nothing consumed yet
    del query


def test_reiterable_sources_give_reiterable_query(flp_type):
    query = flp_type([1, 2]).group_join([2, 3], _ident, _ident, lambda o, g: (o, list(g)))

    assert list(query) == list(query) == [(1, []), (2, [2])]


def test_one_shot_outer_stays_one_shot():
    query = flp.it(x for x in [1, 2]).group_join([1, 2], _ident, _ident)

    assert len(list(query)) == 2
    assert list(query) == []  # no implicit caching / replay of the consumed outer


def test_key_selectors_called_once_per_element():
    ok_calls, ik_calls = [], []
    outer, inner = [1, 2, 2, 3], [2, 2, 3, 4]

    list(flp.it(outer).group_join(
        inner,
        lambda x: ok_calls.append(x) or x,
        lambda x: ik_calls.append(x) or x,
    ))

    assert ik_calls == inner  # O(N + M): no nested re-evaluation
    assert ok_calls == outer


def test_inner_enumerated_exactly_once_per_iteration():
    inner = Tracked([1, 2, 3])

    list(flp.it([1, 2, 3, 1, 2, 3]).group_join(inner, _ident, _ident))

    assert inner.iter_calls == 1


def test_exceptions_propagate_from_every_callback():
    def boom(*_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        list(flp.it([1]).group_join([1], boom, _ident))
    with pytest.raises(RuntimeError):
        list(flp.it([1]).group_join([1], _ident, boom))
    with pytest.raises(RuntimeError):
        list(flp.it([1]).group_join([1], _ident, _ident, boom))


def test_outer_is_streamed():
    outer, inner = Tracked([1, 2, 3, 4]), Tracked([1, 2])

    it = iter(flp.it(outer).group_join(inner, _ident, _ident))
    first = next(it)

    assert first.key == 1
    assert outer.yielded == 1  # one result needs exactly one outer element
    assert inner.yielded == 2  # the inner side is buffered once, on the first outer element


# ---------------------------------------------------------------------------
# .NET-compatible enumeration timing of `inner`
# ---------------------------------------------------------------------------

def test_empty_outer_never_enumerates_inner():
    inner = Tracked([1, 2, 3])

    assert list(flp.it([]).group_join(inner, _ident, _ident)) == []
    assert inner.iter_calls == 0


def test_empty_inner_still_enumerates_outer():
    outer = Tracked([1, 2, 3])

    result = list(flp.it(outer).group_join([], _ident, _ident, lambda o, g: (o, len(g))))

    assert result == [(1, 0), (2, 0), (3, 0)]
    assert outer.iter_calls == 1


# ---------------------------------------------------------------------------
# Result shape and group semantics
# ---------------------------------------------------------------------------

def test_one_result_per_outer_element_in_outer_order_including_duplicates():
    result = flp.it(["b", "a", "b", "z"]).group_join(
        [("a", 1), ("b", 2), ("b", 3)],
        _ident,
        lambda i: i[0],
        lambda o, g: (o, [n for _, n in g]),
    )

    assert list(result) == [("b", [2, 3]), ("a", [1]), ("b", [2, 3]), ("z", [])]


def test_group_keeps_inner_order():
    result = flp.it([1]).group_join([(1, "c"), (2, "x"), (1, "a"), (1, "b")], _ident, lambda i: i[0])

    assert [v for _, v in next(iter(result))] == ["c", "a", "b"]


def test_none_keys_never_match_but_outer_is_kept():
    result = flp.it([None, 1]).group_join(
        [None, 1, None], _ident, _ident, lambda o, g: (o, list(g))
    )

    assert list(result) == [(None, []), (1, [1])]


def test_default_result_is_grouping_keyed_by_the_outer_element_itself():
    outer_item = ("k", object())

    (group,) = flp.it([outer_item]).group_join([("k", 1), ("k", 2)], lambda o: o[0], lambda i: i[0])

    assert isinstance(group, Grouping)
    assert group.key is outer_item
    assert list(group) == [("k", 1), ("k", 2)]


def test_result_selector_receives_re_enumerable_flplist():
    seen = []

    list(flp.it([1]).group_join([1, 1], _ident, _ident, lambda o, g: seen.append(g)))

    (group,) = seen
    assert isinstance(group, FlpList)
    assert list(group) == list(group) == [1, 1]


def test_groups_are_independent_snapshots():
    groups = list(flp.it([1, 1]).group_join([1, 1], _ident, _ident))
    groups[0].add(99)  # FlpList.append() is lazy and does not mutate; add() does

    assert list(groups[0]) == [1, 1, 99]
    assert list(groups[1]) == [1, 1]  # same key, other outer element: unaffected

    again = list(flp.it([1]).group_join([1, 1], _ident, _ident))
    assert list(again[0]) == [1, 1]


def test_unhashable_key_raises_type_error():
    with pytest.raises(TypeError):
        list(flp.it([[1]]).group_join([1], _ident, _ident))


def test_composes_with_downstream_operators():
    totals = (
        flp.it([("a", 1), ("b", 2), ("c", 3)])
        .group_join([("a", 10), ("a", 20), ("c", 5)], lambda c: c[0], lambda o: o[0],
                    lambda c, orders: (c[0], orders.select(lambda o: o[1]).sum()))
        .where(lambda r: r[1] > 0)
        .to_list()
    )

    assert totals == [("a", 30), ("c", 5)]


# ---------------------------------------------------------------------------
# FlpList delegation
# ---------------------------------------------------------------------------

def test_flplist_delegates_and_returns_flpit():
    query = flp.lst([1, 2]).group_join([2], _ident, _ident, lambda o, g: (o, list(g)))

    assert type(query) is FlpIt
    assert list(query) == [(1, []), (2, [2])]


def test_flplist_sees_mutations_made_before_enumeration():
    source = flp.lst([1])
    query = source.group_join([2], _ident, _ident, lambda o, g: (o, list(g)))

    source.add(2)  # FlpList.append() is lazy and does not mutate; add() does

    assert list(query) == [(1, []), (2, [2])]
