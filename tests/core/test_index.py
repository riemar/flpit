"""
FlpIt-specific behaviour of index().

The .NET port lives in tests/nettests/linq/test_index.py. This module covers the architectural
invariants from .agents/rules.md (deferred execution, no consumption on construction, single-use
sources, streaming) and the index-specific contract:

    * every element is paired with its zero-based position, in source order,
    * the result is an ``IndexTuple`` that is also a plain ``tuple`` (unpackable, comparable to ``(i, x)``),
    * ``index()`` composes with the other operators, so no indexed ``select`` / ``where`` overloads are needed.
"""
import pytest

from flpit import flp, FlpIt, FlpList, IndexTuple


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
# Architectural invariants
# ---------------------------------------------------------------------------

def test_index_returns_flpit(flp_type):
    assert isinstance(flp_type([1, 2]).index(), FlpIt)


def test_index_construction_does_not_consume_source():
    # FlpList copies its source on construction by design, so this invariant is FlpIt-only.
    source = Tracked([1, 2, 3])

    query = flp.it(source).index()

    assert source.iter_calls == 0
    assert source.yielded == 0
    assert list(query) == [(0, 1), (1, 2), (2, 3)]
    assert source.iter_calls == 1


def test_index_is_lazy_and_streams():
    source = Tracked(["a", "b", "c", "d"])

    iterator = iter(flp.it(source).index())
    assert source.yielded == 0

    assert next(iterator) == (0, "a")
    assert source.yielded == 1
    assert next(iterator) == (1, "b")
    assert source.yielded == 2


def test_index_short_circuits_with_first_and_take():
    source = Tracked(range(1000))

    assert flp.it(source).index().first() == (0, 0)
    assert source.yielded == 1

    source = Tracked(range(1000))
    assert flp.it(source).index().take(3).to_list() == [(0, 0), (1, 1), (2, 2)]
    assert source.yielded == 3


def test_index_one_shot_source_stays_one_shot():
    query = flp.it(x for x in "ab").index()

    assert list(query) == [(0, "a"), (1, "b")]
    assert list(query) == []


def test_index_re_enumerable_source_restarts_at_zero(flp_type):
    query = flp_type(["a", "b"]).index()

    assert list(query) == [(0, "a"), (1, "b")]
    assert list(query) == [(0, "a"), (1, "b")]


def test_index_sees_source_mutation_made_before_enumeration():
    data = ["a"]
    query = flp.it(data).index()

    data.append("b")

    assert list(query) == [(0, "a"), (1, "b")]


def test_index_exception_from_source_propagates():
    def _source():
        yield 1
        raise ValueError("boom")

    iterator = iter(flp.it(_source()).index())

    assert next(iterator) == (0, 1)
    with pytest.raises(ValueError, match="boom"):
        next(iterator)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

def test_index_yields_index_tuples(flp_type):
    result = flp_type(["a", "b"]).index().to_list()

    assert all(type(t) is IndexTuple for t in result)
    assert [t.index for t in result] == [0, 1]
    assert [t.item for t in result] == ["a", "b"]
    assert result[1]._fields == ("index", "item")


def test_index_tuple_unpacks_and_equals_plain_tuple(flp_type):
    pairs = [(i, x) for i, x in flp_type(["a", "b"]).index()]

    assert pairs == [(0, "a"), (1, "b")]
    assert IndexTuple(0, "a") == (0, "a")


def test_index_tuple_index_overridden_count_preserved(flp_type):
    first = flp_type(["a"]).index().first()

    with pytest.raises(TypeError):
        first.index("a")

    assert first.count("a") == 1


def test_index_does_not_alter_none_and_falsey_items(flp_type):
    assert flp_type([None, 0, "", False]).index().to_list() == [(0, None), (1, 0), (2, ""), (3, False)]


# ---------------------------------------------------------------------------
# Composition (replaces indexed select / where overloads)
# ---------------------------------------------------------------------------

def test_index_replaces_indexed_select(flp_type):
    result = flp_type(["a", "b", "c"]).index().select(lambda t: f"{t.index}:{t.item}").to_list()

    assert result == ["0:a", "1:b", "2:c"]


def test_index_replaces_indexed_where(flp_type):
    result = flp_type(["a", "b", "c", "d"]).index().where(lambda t: t.index % 2 == 0).select(lambda t: t.item).to_list()

    assert result == ["a", "c"]


def test_index_after_where_numbers_the_filtered_sequence(flp_type):
    result = flp_type([1, 2, 3, 4, 5, 6]).where(lambda x: x % 2 == 0).index().to_list()

    assert result == [(0, 2), (1, 4), (2, 6)]


def test_index_after_order_by_numbers_the_ordered_sequence(flp_type):
    result = flp_type([3, 1, 2]).order_by(lambda x: x).index().to_list()

    assert result == [(0, 1), (1, 2), (2, 3)]


def test_index_of_index_nests(flp_type):
    result = flp_type(["a", "b"]).index().index().to_list()

    assert result == [(0, (0, "a")), (1, (1, "b"))]


def test_index_on_flplist_does_not_mutate_list():
    data = flp.lst(["a", "b"])

    assert data.index().to_list() == [(0, "a"), (1, "b")]
    assert isinstance(data, FlpList)
    assert list(data) == ["a", "b"]
