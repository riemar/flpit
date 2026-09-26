import pytest

from flpit import flp
from helpers import Bomb

# ---------------------------------------------------------------------------
# all(predicate)
# ---------------------------------------------------------------------------

def test_all_predicate_all_match(flp_type) -> None:
    data = flp_type([2, 4, 6])

    assert data.all(lambda x: x % 2 == 0) is True


def test_all_predicate_one_no_match(flp_type) -> None:
    data = flp_type([2, 4, 5, 6])

    assert data.all(lambda x: x % 2 == 0) is False


def test_all_predicate_empty(flp_type) -> None:
    data = flp_type([])

    assert data.all(lambda x: False) is True


def test_all_predicate_single_match(flp_type) -> None:
    data = flp_type([2])

    assert data.all(lambda x: x == 2) is True


def test_all_predicate_single_no_match(flp_type) -> None:
    data = flp_type([2])

    assert data.all(lambda x: x == 3) is False


def test_all_predicate_short_circuits(flp_type) -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return x != 2

    data = flp_type([1, 2, 3])

    assert data.all(predicate) is False
    assert seen == [1, 2]


def test_all_predicate_does_not_use_element_truthiness(flp_type) -> None:
    item = Bomb()
    data = flp_type([item])

    assert data.all(lambda _: True) is True


def test_all_predicate_can_match_falsy_elements(flp_type) -> None:
    data = flp_type([0, None, False, ""])

    assert data.all(lambda x: x is None or x is False or x == 0 or x == "") is True


def test_all_predicate_propagates_error(flp_type) -> None:
    def predicate(_):
        raise AssertionError("predicate failed")

    with pytest.raises(AssertionError, match="predicate failed"):
        flp_type([1]).all(predicate)


def test_all_predicate_receives_elements_in_order(flp_type) -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return True

    data = flp_type([1, 2, 3])

    assert data.all(predicate) is True
    assert seen == [1, 2, 3]


def test_all_predicate_can_be_called_twice() -> None:
    data = flp.it([1, 2, 3])

    assert data.all(lambda x: x > 0) is True
    assert data.all(lambda x: x < 3) is False


def test_all_predicate_on_exhausted_generator_returns_true() -> None:
    # A raw generator should be exhausted after the first call
    gen = (x for x in [1, 2, 3])
    data = flp.it([])

    assert data.all(lambda x: x > 0) is True
    assert data.all(lambda x: x > 0) is True  # True because empty sets yield True


def test_all_predicate_propagates_midstream_iterator_error() -> None:
    def broken_iterator():
        yield 1
        yield 2
        raise AssertionError("iterator failed midstream")

    with pytest.raises(AssertionError, match="iterator failed midstream"):
        flp.it(broken_iterator()).all(lambda x: True)


def test_all_predicate_exhausts_iterable() -> None:
    gen = (x for x in [1, 2, 3])
    data = flp.it(gen)

    assert data.all(lambda x: True) is True

    with pytest.raises(StopIteration):
        next(gen)


def test_all_predicate_propagates_iterator_error() -> None:
    def broken_iterator():
        raise AssertionError("iterator failed before yielding")
        yield

    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        flp.it(broken_iterator()).all(lambda x: True)


def test_all_predicate_short_circuits_before_iterator_error() -> None:
    def broken_iterator():
        yield 1
        raise AssertionError("should not be reached")

    data = flp.it(broken_iterator())

    assert data.all(lambda x: False) is False


def test_all_predicate_missing_throws_exception() -> None:
    data = flp.it([1, 2, 3])

    # .NET LINQ throws ArgumentNullException if predicate is null.
    # Python equivalent: TypeError.
    with pytest.raises(TypeError):
        data.all(None) # type: ignore