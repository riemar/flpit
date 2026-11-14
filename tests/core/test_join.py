"""
FlpIt-specific behaviour of join / left_join / full_join.

The .NET ports live in tests/nettests/linq/test_join.py and test_left_join.py. This module covers:
    * architectural invariants from .agents/rules.md (deferred execution, no consumption on
      construction, single-use sources, streaming / short-circuiting, O(N + M) key-selector usage),
    * full_join, which has no .NET LINQ equivalent (so no .NET oracle) and defines its own semantics:
      left_join output, followed by the never-matched inner elements (outer = None) in inner order.
"""
import pytest

from flpit import (
    flp,
    FlpIt,
    FlpList,
    InnerKeySelectorNoneError,
    InnerNoneError,
    JoinTuple,
    OuterKeySelectorNoneError,
    ResultSelectorNoneError,
    SourceNoneError,
)

JOINS = ["join", "left_join", "full_join"]


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


def _first(x):
    return x[0]


# ---------------------------------------------------------------------------
# Shared invariants (all three operators)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op", JOINS)
def test_returns_deferred_flpit(op, flp_type):
    result = getattr(flp_type([1]), op)([1], lambda x: x, lambda x: x)

    assert type(result) is FlpIt


@pytest.mark.parametrize("op", JOINS)
def test_construction_does_not_consume_or_call_anything(op):
    outer, inner = Tracked([1, 2]), Tracked([2, 3])
    calls = []

    getattr(flp.it(outer), op)(
        inner,
        lambda x: calls.append("ok") or x,
        lambda x: calls.append("ik") or x,
        lambda o, i: calls.append("rs") or (o, i),
    )

    assert (outer.iter_calls, inner.iter_calls, calls) == (0, 0, [])


@pytest.mark.parametrize("op", JOINS)
def test_one_shot_sources_are_not_touched_on_construction(op):
    outer_gen = (x for x in [1, 2])
    inner_gen = (x for x in [2, 3])

    query = getattr(flp.it(outer_gen), op)(inner_gen, lambda x: x, lambda x: x)

    assert next(outer_gen) == 1 and next(inner_gen) == 2  # nothing consumed yet
    del query


@pytest.mark.parametrize("op", JOINS)
def test_arguments_validated_eagerly(op, flp_type):
    source = flp_type([1])
    method = getattr(source, op)

    with pytest.raises(InnerNoneError):
        method(None, lambda x: x, lambda x: x)
    with pytest.raises(OuterKeySelectorNoneError):
        method([1], None, lambda x: x)
    with pytest.raises(InnerKeySelectorNoneError):
        method([1], lambda x: x, None)
    with pytest.raises(ResultSelectorNoneError):
        method([1], lambda x: x, lambda x: x, None)


@pytest.mark.parametrize("op", JOINS)
def test_none_source_rejected_by_constructor(op, flp_type):
    with pytest.raises(SourceNoneError):
        getattr(flp_type(None), op)([1], lambda x: x, lambda x: x)


@pytest.mark.parametrize("op", JOINS)
def test_reiterable_sources_give_reiterable_query(op, flp_type):
    query = getattr(flp_type([1, 2]), op)([2, 3], lambda x: x, lambda x: x)

    assert list(query) == list(query)


@pytest.mark.parametrize("op", ["join", "left_join"])
def test_one_shot_outer_stays_one_shot(op):
    query = getattr(flp.it(x for x in [1, 2]), op)([1, 2], lambda x: x, lambda x: x)

    assert len(list(query)) == 2
    assert list(query) == []  # no implicit caching / replay of the consumed outer


def test_full_join_one_shot_outer_stays_one_shot():
    query = flp.it(x for x in [1, 2]).full_join([1, 3], lambda x: x, lambda x: x)

    assert [tuple(r) for r in query] == [(1, 1), (2, None), (None, 3)]
    # the consumed outer is not replayed: it is now empty, so every inner element is unmatched
    assert [tuple(r) for r in query] == [(None, 1), (None, 3)]


@pytest.mark.parametrize("op", JOINS)
def test_key_selectors_called_once_per_element(op):
    ok_calls, ik_calls = [], []
    outer, inner = [1, 2, 2, 3], [2, 2, 3, 4]

    list(getattr(flp.it(outer), op)(
        inner,
        lambda x: ok_calls.append(x) or x,
        lambda x: ik_calls.append(x) or x,
    ))

    assert sorted(ik_calls) == sorted(inner)  # O(N + M): no nested re-evaluation
    assert sorted(ok_calls) == sorted(outer) or op == "join" and ok_calls == outer


@pytest.mark.parametrize("op", JOINS)
def test_inner_enumerated_exactly_once_per_iteration(op):
    inner = Tracked([1, 2, 3])

    list(getattr(flp.it([1, 2, 3, 1, 2, 3]), op)(inner, lambda x: x, lambda x: x))

    assert inner.iter_calls == 1


@pytest.mark.parametrize("op", JOINS)
def test_exceptions_propagate(op):
    def boom(_):
        raise RuntimeError("selector failed")

    with pytest.raises(RuntimeError, match="selector failed"):
        list(getattr(flp.it([1]), op)([1], boom, lambda x: x))
    with pytest.raises(RuntimeError, match="selector failed"):
        list(getattr(flp.it([1]), op)([1], lambda x: x, boom))
    with pytest.raises(RuntimeError, match="selector failed"):
        list(getattr(flp.it([1]), op)([1], lambda x: x, lambda x: x, lambda o, i: boom(o)))


@pytest.mark.parametrize("op", JOINS)
def test_unhashable_key_raises_type_error(op):
    with pytest.raises(TypeError):
        list(getattr(flp.it([[1]]), op)([[1]], lambda x: x, lambda x: x))


@pytest.mark.parametrize("op", JOINS)
def test_default_result_is_join_tuple(op):
    result = list(getattr(flp.it([1]), op)([1], lambda x: x, lambda x: x))

    assert result == [(1, 1)]
    assert isinstance(result[0], JoinTuple)
    assert (result[0].outer, result[0].inner) == (1, 1)


@pytest.mark.parametrize("op", JOINS)
def test_outer_is_streamed(op):
    """take(1) must not enumerate the whole outer sequence."""
    outer = Tracked(range(100))

    result = list(getattr(flp.it(outer), op)([0, 1, 2], lambda x: x, lambda x: x).take(1))

    assert len(result) == 1
    assert outer.yielded < 100


# ---------------------------------------------------------------------------
# join specifics
# ---------------------------------------------------------------------------

def test_join_empty_inner_does_not_enumerate_outer():
    outer = Tracked([1, 2, 3])

    assert list(flp.it(outer).join([], lambda x: x, lambda x: x)) == []
    assert outer.iter_calls == 0  # same short-cut as .NET (empty lookup)


def test_join_keeps_outer_order_then_inner_order():
    outer = [("b", 1), ("a", 2), ("b", 3)]
    inner = [("a", "x"), ("b", "y"), ("b", "z")]

    result = list(flp.it(outer).join(inner, _first, _first, lambda o, i: (o[1], i[1])))

    assert result == [(1, "y"), (1, "z"), (2, "x"), (3, "y"), (3, "z")]


def test_join_hash_semantics_match_dict_equality():
    # 1 == 1.0 == True, as for dict / group_by keys
    assert list(flp.it([1]).join([1.0, True], lambda x: x, lambda x: x, lambda o, i: i)) == [1.0, True]


# ---------------------------------------------------------------------------
# left_join specifics
# ---------------------------------------------------------------------------

def test_left_join_enumerates_outer_even_if_inner_empty():
    outer = Tracked([1, 2])

    assert list(flp.it(outer).left_join([], lambda x: x, lambda x: x, lambda o, i: (o, i))) == [(1, None), (2, None)]
    assert outer.iter_calls == 1


def test_left_join_none_keys_never_match_but_are_kept():
    outer = [("a", 1), (None, 2)]
    inner = [(None, "n"), ("a", "x")]

    result = list(flp.it(outer).left_join(inner, _first, _first, lambda o, i: (o[1], i and i[1])))

    assert result == [(1, "x"), (2, None)]


def test_left_join_one_row_per_match_and_one_for_miss():
    result = list(flp.it([1, 2, 3]).left_join([1, 1, 3], lambda x: x, lambda x: x, lambda o, i: (o, i)))

    assert result == [(1, 1), (1, 1), (2, None), (3, 3)]


# ---------------------------------------------------------------------------
# full_join (no .NET equivalent)
# ---------------------------------------------------------------------------

def _fj(outer, inner, selector=None, ok=lambda x: x, ik=lambda x: x):
    query = flp.it(outer)
    if selector is None:
        return [tuple(r) for r in query.full_join(inner, ok, ik)]
    return list(query.full_join(inner, ok, ik, selector))


def test_full_join_matched_unmatched_outer_and_unmatched_inner():
    assert _fj([1, 2, 3], [3, 4, 5]) == [(1, None), (2, None), (3, 3), (None, 4), (None, 5)]


def test_full_join_both_empty():
    assert _fj([], []) == []


def test_full_join_empty_outer_yields_all_inner_with_none_outer():
    assert _fj([], [1, 2]) == [(None, 1), (None, 2)]


def test_full_join_empty_inner_yields_all_outer_with_none_inner():
    assert _fj([1, 2], []) == [(1, None), (2, None)]


def test_full_join_no_matches_outer_first_then_inner():
    assert _fj(["a", "b"], ["c", "d"]) == [("a", None), ("b", None), (None, "c"), (None, "d")]


def test_full_join_all_match_has_no_unmatched_rows():
    assert _fj([1, 2], [2, 1]) == [(1, 1), (2, 2)]


def test_full_join_duplicate_keys_produce_cross_product_and_inner_not_repeated():
    result = _fj(
        [("a", 1), ("a", 2)],
        [("a", "x"), ("a", "y"), ("b", "z")],
        selector=lambda o, i: (o, i),
        ok=_first, ik=_first,
    )

    assert result == [
        (("a", 1), ("a", "x")),
        (("a", 1), ("a", "y")),
        (("a", 2), ("a", "x")),
        (("a", 2), ("a", "y")),
        (None, ("b", "z")),
    ]


def test_full_join_none_keys_never_match_and_appear_on_both_sides():
    outer = [(None, "o-null"), ("a", "o-a")]
    inner = [(None, "i-null"), ("a", "i-a")]

    result = _fj(outer, inner, selector=lambda o, i: (o and o[1], i and i[1]), ok=_first, ik=_first)

    assert result == [("o-null", None), ("o-a", "i-a"), (None, "i-null")]


def test_full_join_unmatched_inner_keep_inner_order():
    result = _fj([2], [5, 2, 4, 3], selector=lambda o, i: (o, i))

    assert result == [(2, 2), (None, 5), (None, 4), (None, 3)]


def test_full_join_result_selector_receives_none_for_missing_side():
    seen = []
    list(flp.it([1, 2]).full_join([2, 3], lambda x: x, lambda x: x, lambda o, i: seen.append((o, i))))

    assert seen == [(1, None), (2, 2), (None, 3)]


def test_full_join_default_result_is_join_tuple_with_none_sides():
    result = list(flp.it([1]).full_join([2], lambda x: x, lambda x: x))

    assert result == [JoinTuple(1, None), JoinTuple(None, 2)]


def test_full_join_inner_enumerated_before_first_result_outer_streamed():
    outer, inner = Tracked([1, 2, 3]), Tracked([3, 4])

    it = iter(flp.it(outer).full_join(inner, lambda x: x, lambda x: x))
    first = next(it)

    assert first == (1, None)
    assert inner.iter_calls == 1 and inner.yielded == 2  # inner fully buffered
    assert outer.yielded == 1                              # outer streamed lazily


def test_full_join_unmatched_inner_come_after_outer_exhausted():
    outer = Tracked([1, 2])

    it = iter(flp.it(outer).full_join([9], lambda x: x, lambda x: x))

    assert next(it) == (1, None)
    assert next(it) == (2, None)
    assert outer.yielded == 2
    assert next(it) == (None, 9)
    assert next(it, "end") == "end"


# ---------------------------------------------------------------------------
# FlpList delegation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op", JOINS)
def test_flplist_delegates_and_returns_flpit(op):
    source = FlpList([1, 2, 3])

    result = getattr(source, op)([2, 3, 4], lambda x: x, lambda x: x)

    assert type(result) is FlpIt
    assert list(result) == list(getattr(flp.it([1, 2, 3]), op)([2, 3, 4], lambda x: x, lambda x: x))
    assert list(source) == [1, 2, 3]  # source untouched


def test_flplist_sees_mutations_made_before_enumeration():
    source = FlpList([1])
    query = source.left_join([1], lambda x: x, lambda x: x, lambda o, i: (o, i))

    source.add(2)  # FlpList.append() is lazy and does not mutate; add() does

    assert list(query) == [(1, 1), (2, None)]
