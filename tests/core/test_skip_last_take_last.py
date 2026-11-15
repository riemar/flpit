"""
FlpIt-specific behaviour of skip_last() and take_last().

The .NET ports live in tests/nettests/linq/test_skip_last.py and test_take_last.py. This module covers the
architectural invariants from .agents/rules.md (deferred execution, no consumption on construction,
single-use sources, streaming / bounded buffering) and the Python-specific edges:

    * skip_last() streams: it reads at most ``count`` elements ahead of the element it yields,
    * take_last() must see the whole source first, but keeps only ``count`` elements and enumerates it once,
    * ``count <= 0``: skip_last() is the identity and still streams, take_last() is empty and never touches the source,
    * exceptions raised by the source propagate unchanged,
    * both operators compose with each other and with the rest of the pipeline.
"""
import pytest

from flpit import flp, FlpIt
from tests.helpers import NoIterList, broken_iterator


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

def test_skip_last_and_take_last_return_flpit(flp_type):
    assert isinstance(flp_type([1, 2, 3]).skip_last(1), FlpIt)
    assert isinstance(flp_type([1, 2, 3]).take_last(1), FlpIt)


@pytest.mark.parametrize("operator", ["skip_last", "take_last"])
def test_construction_does_not_consume_source(operator):
    # FlpList copies its source on construction by design, so this invariant is FlpIt-only.
    source = Tracked([1, 2, 3])

    query = getattr(flp.it(source), operator)(2)

    assert source.iter_calls == 0
    assert source.yielded == 0
    assert list(query) == ([1] if operator == "skip_last" else [2, 3])
    assert source.iter_calls == 1


@pytest.mark.parametrize("operator", ["skip_last", "take_last"])
def test_is_deferred_until_iteration(operator):
    query = getattr(flp.it(broken_iterator()), operator)(1)

    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        list(query)


@pytest.mark.parametrize("operator", ["skip_last", "take_last"])
def test_one_shot_source_stays_one_shot(operator):
    query = getattr(flp.it(x for x in range(5)), operator)(2)

    assert list(query) == ([0, 1, 2] if operator == "skip_last" else [3, 4])
    assert list(query) == []


@pytest.mark.parametrize("operator", ["skip_last", "take_last"])
def test_re_enumerable_source_can_be_enumerated_repeatedly(flp_type, operator):
    query = getattr(flp_type([1, 2, 3, 4, 5]), operator)(2)

    assert list(query) == list(query)
    assert len(list(query)) == (3 if operator == "skip_last" else 2)


# ---------------------------------------------------------------------------
# skip_last: streaming with a look-ahead of `count`
# ---------------------------------------------------------------------------

def test_skip_last_reads_at_most_count_elements_ahead():
    source = Tracked(range(10))
    iterator = iter(flp.it(source).skip_last(3))

    assert next(iterator) == 0
    assert source.yielded == 4  # elements 0..3: three buffered plus the one that releases element 0
    assert next(iterator) == 1
    assert source.yielded == 5


def test_skip_last_short_circuits_downstream():
    source = Tracked(range(1000))

    assert flp.it(source).skip_last(2).first() == 0
    assert source.yielded == 3


def test_skip_last_zero_or_negative_streams_without_read_ahead():
    for count in (0, -1):
        source = Tracked(range(10))
        iterator = iter(flp.it(source).skip_last(count))

        assert next(iterator) == 0
        assert source.yielded == 1


def test_skip_last_count_larger_than_source_is_empty():
    source = Tracked(range(3))

    assert list(flp.it(source).skip_last(10)) == []
    assert source.yielded == 3


# ---------------------------------------------------------------------------
# take_last: consumes the source once, keeps only `count` elements
# ---------------------------------------------------------------------------

def test_take_last_consumes_the_source_once_on_first_element():
    source = Tracked(range(10))
    iterator = iter(flp.it(source).take_last(3))
    assert source.yielded == 0

    assert next(iterator) == 7
    assert source.yielded == 10
    assert source.iter_calls == 1
    assert list(iterator) == [8, 9]
    assert source.iter_calls == 1


@pytest.mark.parametrize("count", [0, -1])
def test_take_last_zero_or_negative_never_touches_the_source(count):
    source = flp.it(NoIterList([1, 2, 3]))

    assert list(source.take_last(count)) == []


@pytest.mark.parametrize("count", [2**63 - 1, 2**64, 10**100])
def test_take_last_count_larger_than_source_returns_everything(flp_type, count):
    # Python ints are unbounded; counts beyond sys.maxsize must behave like any other oversized count.
    assert list(flp_type([1, 2, 3]).take_last(count)) == [1, 2, 3]


@pytest.mark.parametrize("count", [2**63 - 1, 2**64, 10**100])
def test_skip_last_count_larger_than_source_is_empty_for_huge_counts(flp_type, count):
    assert list(flp_type([1, 2, 3]).skip_last(count)) == []


# ---------------------------------------------------------------------------
# Edge cases and composition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("operator", ["skip_last", "take_last"])
def test_source_exceptions_propagate(operator):
    def source():
        yield 1
        yield 2
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        list(getattr(flp.it(source()), operator)(1))


def test_falsy_and_none_elements_are_preserved(flp_type):
    data = [None, 0, False, "", None]

    assert list(flp_type(data).skip_last(1)) == [None, 0, False, ""]
    assert list(flp_type(data).take_last(4)) == [0, False, "", None]


def test_skip_last_and_take_last_compose(flp_type):
    data = flp_type(range(10))

    assert list(data.skip_last(2).take_last(3)) == [5, 6, 7]
    assert list(data.take_last(5).skip_last(2)) == [5, 6, 7]
    assert list(data.take_last(3).take_last(5)) == [7, 8, 9]
    assert list(data.skip_last(3).skip_last(4)) == [0, 1, 2]


def test_composes_with_where_and_select(flp_type):
    result = (
        flp_type(range(20))
        .where(lambda x: x % 2 == 0)
        .skip_last(2)
        .take_last(3)
        .select(lambda x: x * 10)
        .to_list()
    )

    assert result == [100, 120, 140]
