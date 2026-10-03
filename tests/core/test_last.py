from flpit import flp, EmptySequenceError, NoMatchError

import pytest
from pytest import param as pp

from helpers import Bomb, broken_iterator, NoIterList


# ---------------------------------------------------------------------------
# last()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pp([1], 1, id="single"),
        pp([1, 2, 3], 3, id="multiple"),
        pp([False, 0, None, ""], "", id="falsy_last"),
        pp([1, None], None, id="none_last"),
    ],
)
def test_last(flp_type, data, expected) -> None:
    assert flp_type(data).last() == expected


def test_last_can_be_called_twice() -> None:
    data = flp.it([1, 2, 3])

    assert data.last() == 3
    assert data.last() == 3


def test_last_empty(flp_type) -> None:
    with pytest.raises(EmptySequenceError):
        flp_type([]).last()


def test_last_returns_same_object(flp_type) -> None:
    item = object()

    assert flp_type([1, item]).last() is item

def test_last_propagates_iterator_error(flp_type) -> None:
    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        flp_type(broken_iterator()).last()


def test_last_uses_indexing_without_predicate() -> None:
    data = flp.lst([])
    data._FlpList__list.data = NoIterList([1, 2, 3])

    assert data.last() == 3


def test_last_propagates_midstream_iterator_error() -> None:
    def broken_iterator_for_last():
        yield 1
        yield 2
        raise AssertionError("iterator failed midstream")

    with pytest.raises(AssertionError, match="iterator failed midstream"):
        flp.it(broken_iterator_for_last()).last()


def test_last_exhausts_iterable() -> None:
    gen = (x for x in [1, 2, 3])
    data = flp.it(gen)

    assert data.last() == 3

    with pytest.raises(StopIteration):
        next(gen)

# ---------------------------------------------------------------------------
# last(predicate)
# ---------------------------------------------------------------------------

def test_last_predicate_can_be_called_twice() -> None:
    data = flp.it([1, 2, 3])

    assert data.last(lambda x: x == 2) == 2
    assert data.last(lambda x: x == 2) == 2


def test_last_predicate_searches_backwards() -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return x == 3

    data = flp.lst([1, 2, 3, 4])

    assert data.last(predicate) == 3
    assert seen == [4, 3]

def test_last_predicate_enumerates_forward() -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return x == 3

    data = flp.it([1, 2, 3, 4])

    assert data.last(predicate) == 3
    assert seen == [1, 2, 3, 4]


def test_last_predicate_no_match(flp_type) -> None:
    data = flp_type([1, 2, 3])

    with pytest.raises(NoMatchError):
        data.last(lambda x: x > 10)


def test_last_predicate_match(flp_type) -> None:
    data = flp_type([1, 2, 3])

    assert data.last(lambda x: x == 2) == 2


def test_last_predicate_empty(flp_type) -> None:
    data = flp_type([])

    with pytest.raises(NoMatchError):
        data.last(lambda x: True)


def test_last_predicate_returns_last_match(flp_type) -> None:
    data = flp_type([1, 2, 3, 2, 4])

    assert data.last(lambda x: x == 2) == 2


def test_last_predicate_does_not_use_element_truthiness(flp_type) -> None:
    item = Bomb()
    data = flp_type([item])

    assert data.last(lambda _: True) is item


def test_last_predicate_returns_last_matching_element(flp_type) -> None:
    data = flp_type([1, None, 2, None, 3])

    assert data.last(lambda x: x is None) is None


def test_last_predicate_propagates_error(flp_type) -> None:
    def predicate(_):
        raise AssertionError("predicate failed")

    data = flp_type([1])

    with pytest.raises(AssertionError, match="predicate failed"):
        data.last(predicate)


def test_last_predicate_can_match_falsy_elements(flp_type) -> None:
    data = flp_type([0, None, False, ""])

    assert data.last(lambda x: x is None) is None

    with pytest.raises(NoMatchError):
        data.last(lambda x: x == 42)


def test_last_predicate_searches_backwards_on_no_match() -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return False

    data = flp.lst([1, 2, 3, 4])

    with pytest.raises(NoMatchError):
        data.last(predicate)

    assert seen == [4, 3, 2, 1]


def test_last_predicate_enumerates_entire_sequence() -> None:
    """Ensure last(predicate) evaluates the entire sequence to find the true last match."""
    evaluated = []

    def predicate(x):
        evaluated.append(x)
        return x % 2 == 0

    data = flp.it([2, 4, 1, 3])

    assert data.last(predicate) == 4
    assert evaluated == [2, 4, 1, 3]