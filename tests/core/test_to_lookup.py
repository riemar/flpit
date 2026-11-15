"""
FlpIt-specific behaviour of to_lookup() and Lookup.

The .NET port lives in tests/nettests/linq/test_to_lookup.py. This module covers the architectural
invariants from .agents/rules.md (immediate execution, single enumeration, single-use sources,
exception propagation) and the Python-specific Lookup contract:

    * to_lookup() is a terminal operation: it enumerates the source exactly once, at call time,
    * per element the key selector runs before the element selector, in source order,
    * the result is a re-enumerable, read-only Lookup that is itself a FlpIt of Groupings,
    * groupings appear in order of first key appearance and keep source order within a group,
    * None is a valid key; indexing a missing key returns a fresh empty sequence and adds no key,
    * `in` / contains() test keys (ILookup.Contains), not groupings,
    * the lookup is a snapshot: later mutations of a FlpList source are not observed.
"""
import pytest

from flpit import flp, FlpIt, FlpList, Grouping, Lookup
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

def test_returns_lookup_of_groupings(flp_type):
    lookup = flp_type([1, 2, 3]).to_lookup(lambda x: x % 2)

    assert isinstance(lookup, Lookup)
    assert isinstance(lookup, FlpIt)
    assert all(isinstance(g, Grouping) for g in lookup)


def test_executes_immediately_and_enumerates_source_once():
    source = Tracked([1, 2, 3, 4])

    lookup = flp.it(source).to_lookup(lambda x: x % 2)

    assert source.iter_calls == 1
    assert source.yielded == 4

    list(lookup)
    list(lookup)
    _ = lookup[0], len(lookup), 1 in lookup

    assert source.iter_calls == 1


def test_one_shot_source_is_consumed_once_and_lookup_is_reenumerable():
    gen = (x for x in [1, 2, 3])

    lookup = flp.it(gen).to_lookup(lambda x: x % 2)

    assert list(gen) == []
    assert [(g.key, list(g)) for g in lookup] == [(1, [1, 3]), (0, [2])]
    assert [(g.key, list(g)) for g in lookup] == [(1, [1, 3]), (0, [2])]


def test_selector_call_order():
    calls = []

    def key(x):
        calls.append(("key", x))
        return x % 2

    def element(x):
        calls.append(("element", x))
        return x * 10

    flp.it([1, 2, 3]).to_lookup(key, element)

    assert calls == [
        ("key", 1), ("element", 1),
        ("key", 2), ("element", 2),
        ("key", 3), ("element", 3),
    ]


def test_argument_validation_happens_before_enumeration():
    with pytest.raises(TypeError):
        flp.it(broken_iterator()).to_lookup(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        flp.it(broken_iterator()).to_lookup(lambda x: x, None)  # type: ignore[arg-type]


def test_source_exception_propagates(flp_type):
    with pytest.raises(AssertionError, match="iterator failed"):
        flp.it(broken_iterator()).to_lookup(lambda x: x)


@pytest.mark.parametrize("selector", ["key", "element"])
def test_selector_exception_propagates(flp_type, selector):
    def boom(_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        if selector == "key":
            flp_type([1]).to_lookup(boom)
        else:
            flp_type([1]).to_lookup(lambda x: x, boom)


# ---------------------------------------------------------------------------
# Lookup contract
# ---------------------------------------------------------------------------

def test_key_order_and_element_order(flp_type):
    lookup = flp_type(["bb", "a", "cc", "d", "eee"]).to_lookup(len)

    assert [g.key for g in lookup] == [2, 1, 3]
    assert list(lookup[2]) == ["bb", "cc"]
    assert list(lookup[1]) == ["a", "d"]


def test_element_selector(flp_type):
    lookup = flp_type([1, 2, 3, 4]).to_lookup(lambda x: x % 2, lambda x: str(x))

    assert list(lookup[1]) == ["1", "3"]
    assert list(lookup[0]) == ["2", "4"]


def test_none_key(flp_type):
    lookup = flp_type([None, 1, None]).to_lookup(lambda x: x)

    assert None in lookup
    assert lookup.contains(None)
    assert list(lookup[None]) == [None, None]


def test_missing_key_returns_fresh_empty_sequence_and_adds_no_key(flp_type):
    lookup = flp_type([1]).to_lookup(lambda x: x)

    missing = lookup[42]
    assert isinstance(missing, FlpList)
    assert list(missing) == []
    assert missing is not lookup[42]

    missing.add(1)
    assert list(lookup[42]) == []
    assert 42 not in lookup
    assert len(lookup) == 1


def test_existing_key_returns_the_grouping(flp_type):
    lookup = flp_type([1, 2]).to_lookup(lambda x: x)

    assert lookup[1] is lookup.first()
    assert lookup[1].key == 1


def test_contains_tests_keys_not_groupings(flp_type):
    lookup = flp_type([1, 2]).to_lookup(lambda x: x % 2)
    grouping = lookup.first()

    assert 1 in lookup
    assert lookup.contains(0)
    assert not lookup.contains(5)
    # Like dict: key lookups require a hashable probe, so a (mutable) Grouping is no valid key.
    with pytest.raises(TypeError):
        _ = grouping in lookup


def test_len_and_count(flp_type):
    lookup = flp_type([1, 2, 3, 4, 5]).to_lookup(lambda x: x % 3)

    assert len(lookup) == 3
    assert lookup.count() == 3
    assert len(flp_type([]).to_lookup(lambda x: x)) == 0


def test_empty_source(flp_type):
    lookup = flp_type([]).to_lookup(lambda x: x)

    assert list(lookup) == []
    assert not lookup.any()


def test_lookup_composes_with_linq(flp_type):
    result = (
        flp_type(range(1, 7))
        .to_lookup(lambda x: x % 3)
        .where(lambda g: g.key != 0)
        .select(lambda g: (g.key, g.sum()))
        .to_list()
    )

    assert result == [(1, 5), (2, 7)]


def test_lookup_is_read_only(flp_type):
    lookup = flp_type([1]).to_lookup(lambda x: x)

    with pytest.raises(TypeError):
        lookup[2] = FlpList([2])  # type: ignore[index]
    with pytest.raises(TypeError):
        del lookup[1]  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        lookup.extra = 1  # type: ignore[attr-defined]


def test_flplist_snapshot_ignores_later_mutation():
    source = FlpList([1, 2])

    lookup = source.to_lookup(lambda x: x % 2)
    source.add(3)

    assert list(lookup[1]) == [1]
    assert source.to_list() == [1, 2, 3]
