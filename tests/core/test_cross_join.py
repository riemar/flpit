"""
FlpIt-specific behaviour of cross_join.

cross_join (cartesian product) has no .NET LINQ equivalent, so there is no .NET oracle and no
migrated test in tests/nettests. This module defines and verifies its semantics plus the
architectural invariants from .agents/rules.md:
    * deferred execution; query construction does not consume anything,
    * single-use sources stay single-use,
    * outer is streamed, inner is buffered exactly once,
    * output order: outer order, then inner order per outer element,
    * eager argument validation, lazy callbacks.
"""
import pytest

from flpit import (
    flp,
    FlpIt,
    InnerNoneError,
    JoinTuple,
    ResultSelectorNoneError,
    SourceNoneError,
)


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


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def test_returns_deferred_flpit(flp_type):
    assert type(flp_type([1]).cross_join([2])) is FlpIt


def test_cartesian_product_in_outer_then_inner_order(flp_type):
    result = list(flp_type([1, 2]).cross_join(["a", "b", "c"]))

    assert result == [(1, "a"), (1, "b"), (1, "c"), (2, "a"), (2, "b"), (2, "c")]


def test_default_result_is_join_tuple(flp_type):
    result = list(flp_type([1]).cross_join(["a"]))

    assert result == [JoinTuple(1, "a")]
    assert isinstance(result[0], JoinTuple)
    assert (result[0].outer, result[0].inner) == (1, "a")


def test_result_selector_is_applied(flp_type):
    result = list(flp_type([1, 2]).cross_join([10, 20], lambda o, i: o + i))

    assert result == [11, 21, 12, 22]


def test_result_count_is_product_of_lengths(flp_type):
    assert flp_type(range(7)).cross_join(range(5)).count() == 35


def test_empty_outer_yields_nothing(flp_type):
    assert list(flp_type([]).cross_join([1, 2])) == []


def test_empty_inner_yields_nothing(flp_type):
    assert list(flp_type([1, 2]).cross_join([])) == []


def test_both_empty_yields_nothing(flp_type):
    assert list(flp_type([]).cross_join([])) == []


def test_duplicates_are_kept(flp_type):
    result = list(flp_type([1, 1]).cross_join([2, 2]))

    assert result == [(1, 2)] * 4

def test_cros_join_equal_select_many(flp_type):
    result = list(flp_type([1, 1]).cross_join([2, 2]))

    assert result == [(1, 2)] * 4

    sel_many_result = list(flp_type([1, 1]).select_many(lambda o: flp.it([2, 2]).select(lambda i: JoinTuple(o, i))))
    assert sel_many_result == result

def test_none_elements_are_ordinary_values(flp_type):
    result = list(flp_type([None, 1]).cross_join([None]))

    assert result == [(None, None), (1, None)]


def test_same_source_as_outer_and_inner():
    data = [1, 2]

    assert list(flp.it(data).cross_join(data)) == [(1, 1), (1, 2), (2, 1), (2, 2)]


def test_result_selector_may_return_none_or_falsy(flp_type):
    assert list(flp_type([1, 2]).cross_join([0], lambda o, i: None)) == [None, None]
    assert list(flp_type([1]).cross_join([0, 0], lambda o, i: 0)) == [0, 0]


def test_chains_with_other_operators():
    result = (
        flp.it([1, 2, 3])
        .cross_join([10, 20])
        .where(lambda p: p.outer != 2)
        .select(lambda p: p.outer * p.inner)
        .to_list()
    )

    assert result == [10, 20, 30, 60]


def test_cross_join_of_cross_join():
    result = list(flp.it([1, 2]).cross_join(["a"]).cross_join([True]))

    assert result == [((1, "a"), True), ((2, "a"), True)]


# ---------------------------------------------------------------------------
# Deferred execution / enumeration
# ---------------------------------------------------------------------------

def test_construction_does_not_consume_or_call_anything():
    outer, inner = Tracked([1, 2]), Tracked([3, 4])
    calls = []

    flp.it(outer).cross_join(inner, lambda o, i: calls.append("rs") or (o, i))

    assert (outer.iter_calls, inner.iter_calls, calls) == (0, 0, [])


def test_one_shot_sources_are_not_touched_on_construction():
    outer_gen = (x for x in [1, 2])
    inner_gen = (x for x in [3, 4])

    query = flp.it(outer_gen).cross_join(inner_gen)

    assert next(outer_gen) == 1 and next(inner_gen) == 3  # nothing consumed yet
    del query


def test_result_selector_runs_lazily_during_iteration():
    calls = []
    query = flp.it([1, 2]).cross_join([10], lambda o, i: calls.append((o, i)) or o + i)

    assert calls == []
    it = iter(query)
    assert next(it) == 11
    assert calls == [(1, 10)]  # second pair not computed yet


def test_inner_is_enumerated_exactly_once_and_outer_exactly_once():
    outer, inner = Tracked([1, 2, 3]), Tracked(["a", "b"])

    result = list(flp.it(outer).cross_join(inner))

    assert len(result) == 6
    assert (outer.iter_calls, inner.iter_calls) == (1, 1)
    assert (outer.yielded, inner.yielded) == (3, 2)


def test_outer_is_streamed_not_buffered():
    outer, inner = Tracked([1, 2, 3]), Tracked(["a", "b"])

    it = iter(flp.it(outer).cross_join(inner))
    next(it)

    assert inner.yielded == 2  # inner fully buffered (needed for every outer element)
    assert outer.yielded == 1  # outer only pulled as far as needed


def test_first_short_circuits_on_outer():
    outer, inner = Tracked([1, 2, 3]), Tracked(["a"])

    assert flp.it(outer).cross_join(inner).first() == (1, "a")
    assert outer.yielded == 1


def test_empty_inner_does_not_enumerate_outer():
    outer = Tracked([1, 2, 3])

    assert list(flp.it(outer).cross_join([])) == []
    assert (outer.iter_calls, outer.yielded) == (0, 0)


def test_one_shot_outer_stays_one_shot():
    query = flp.it(x for x in [1, 2]).cross_join([3])

    assert list(query) == [(1, 3), (2, 3)]
    assert list(query) == []  # source exhausted: no implicit caching / replay


def test_replayable_sources_can_be_enumerated_repeatedly():
    query = flp.it([1, 2]).cross_join([3])

    assert list(query) == list(query) == [(1, 3), (2, 3)]


def test_one_shot_inner_is_consumed_on_first_enumeration_only():
    query = flp.it([1, 2]).cross_join(x for x in [3, 4])

    assert len(list(query)) == 4
    assert list(query) == []  # inner generator exhausted


def test_exceptions_from_result_selector_propagate():
    def boom(o, i):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        list(flp.it([1]).cross_join([2], boom))


def test_exceptions_from_inner_enumeration_propagate():
    def failing():
        yield 1
        raise RuntimeError("inner failed")

    with pytest.raises(RuntimeError, match="inner failed"):
        list(flp.it([1]).cross_join(failing()))


# ---------------------------------------------------------------------------
# Argument validation (eager)
# ---------------------------------------------------------------------------

def test_none_inner_raises_eagerly(flp_type):
    with pytest.raises(InnerNoneError):
        flp_type([1]).cross_join(None)


def test_none_result_selector_raises_eagerly(flp_type):
    with pytest.raises(ResultSelectorNoneError):
        flp_type([1]).cross_join([1], None)


def test_none_source_raises():
    with pytest.raises(SourceNoneError):
        flp.it(None)
