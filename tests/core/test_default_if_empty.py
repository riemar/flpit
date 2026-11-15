"""
FlpIt-specific behaviour of default_if_empty().

The .NET port lives in tests/nettests/linq/test_default_if_empty.py. This module covers the architectural
invariants from .agents/rules.md (deferred execution, no consumption on construction, single-use sources,
streaming) and the Python-specific edges:

    * the default value is mandatory and is yielded as the very same object (no copy),
    * "empty" means "the source yielded nothing", never "the elements are falsy",
    * the source is enumerated exactly once per enumeration, also when it is empty,
    * the operator streams: the first element is released after reading a single source element,
    * FlpList checks emptiness when enumeration starts, so later mutations of the list are observed,
    * exceptions raised by the source propagate unchanged,
    * the operator composes with the rest of the pipeline.
"""
import pytest

from flpit import flp, FlpIt
from tests.helpers import broken_iterator


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

def test_returns_flpit(flp_type):
    assert isinstance(flp_type([1, 2]).default_if_empty(0), FlpIt)
    assert isinstance(flp_type([]).default_if_empty(0), FlpIt)


def test_default_is_mandatory(flp_type):
    with pytest.raises(TypeError):
        flp_type([]).default_if_empty()  # type: ignore[call-arg]


@pytest.mark.parametrize("items", [[], [1, 2, 3]], ids=["empty", "non-empty"])
def test_construction_does_not_consume_source(items):
    # FlpList copies its source on construction by design, so this invariant is FlpIt-only.
    source = Tracked(items)

    query = flp.it(source).default_if_empty(-1)

    assert source.iter_calls == 0
    assert source.yielded == 0
    assert list(query) == (items or [-1])
    assert source.iter_calls == 1


def test_is_deferred_until_iteration():
    query = flp.it(broken_iterator()).default_if_empty(0)

    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        list(query)


def test_one_shot_source_stays_one_shot():
    query = flp.it(x for x in range(3)).default_if_empty(-1)

    assert list(query) == [0, 1, 2]
    # The exhausted generator is now an empty source, so the default is produced (as in .NET).
    assert list(query) == [-1]


@pytest.mark.parametrize("items", [[], [1, 2, 3]], ids=["empty", "non-empty"])
def test_re_enumerable_source_can_be_enumerated_repeatedly(flp_type, items):
    query = flp_type(items).default_if_empty(-1)

    assert list(query) == list(query) == (items or [-1])


@pytest.mark.parametrize("items", [[], [1, 2, 3]], ids=["empty", "non-empty"])
def test_source_is_enumerated_once_per_enumeration(items):
    source = Tracked(items)
    query = flp.it(source).default_if_empty(-1)

    list(query)
    list(query)

    assert source.iter_calls == 2
    assert source.yielded == 2 * len(items)


def test_streams_without_read_ahead():
    source = Tracked(range(10))
    iterator = iter(flp.it(source).default_if_empty(-1))

    assert next(iterator) == 0
    assert source.yielded == 1
    assert next(iterator) == 1
    assert source.yielded == 2


def test_short_circuiting_terminal_stops_early():
    source = Tracked(range(10))

    assert flp.it(source).default_if_empty(-1).first() == 0
    assert source.yielded == 1


# ---------------------------------------------------------------------------
# default_if_empty-specific contract
# ---------------------------------------------------------------------------

def test_default_is_yielded_as_same_object(flp_type):
    default = object()

    (actual,) = flp_type([]).default_if_empty(default)

    assert actual is default


def test_none_is_a_valid_default(flp_type):
    assert list(flp_type([]).default_if_empty(None)) == [None]


@pytest.mark.parametrize("items", [[0], [None], [""], [False, 0, None]], ids=["0", "None", "empty-str", "mixed"])
def test_falsy_elements_do_not_count_as_empty(flp_type, items):
    assert list(flp_type(items).default_if_empty("default")) == items


def test_default_is_not_appended_to_non_empty_source(flp_type):
    assert list(flp_type([1, 2, 3]).default_if_empty(1)) == [1, 2, 3]


def test_flplist_observes_mutation_after_construction():
    container = flp.lst([])
    query = container.default_if_empty(-1)

    assert list(query) == [-1]
    container.add(7)
    assert list(query) == [7]
    container.clear()
    assert list(query) == [-1]


def test_flpit_over_live_list_observes_mutation_after_construction():
    data = []
    query = flp.it(data).default_if_empty(-1)

    assert list(query) == [-1]
    data.append(7)
    assert list(query) == [7]


def test_source_exception_propagates_after_yielded_elements():
    def failing():
        yield 1
        raise ValueError("boom")

    iterator = iter(flp.it(failing()).default_if_empty(-1))

    assert next(iterator) == 1
    with pytest.raises(ValueError, match="boom"):
        next(iterator)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def test_composes_with_where_that_filters_everything(flp_type):
    query = flp_type([1, 2, 3]).where(lambda x: x > 10).default_if_empty(0).select(lambda x: x * 10)

    assert list(query) == [0]


def test_composes_with_where_that_keeps_elements(flp_type):
    query = flp_type([1, 2, 3]).where(lambda x: x > 1).default_if_empty(0).select(lambda x: x * 10)

    assert list(query) == [20, 30]


def test_chained_default_if_empty_keeps_first_default(flp_type):
    assert list(flp_type([]).default_if_empty(1).default_if_empty(2)) == [1]


def test_left_outer_join_pattern_via_group_join_and_select_many():
    # The classic .NET left-outer-join idiom: GroupJoin + SelectMany(g => g.DefaultIfEmpty()).
    outer = [(1, "a"), (2, "b")]
    inner = [(1, "x"), (1, "y")]

    query = (
        flp.it(outer)
        .group_join(inner, lambda o: o[0], lambda i: i[0], lambda o, matches: (o, matches))
        .select_many(lambda pair: flp.it(pair[1]).default_if_empty(None).select(lambda i: (pair[0][1], i and i[1])))
    )

    assert list(query) == [("a", "x"), ("a", "y"), ("b", None)]
