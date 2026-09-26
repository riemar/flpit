from unittest.mock import patch
from typing import Any

import pytest
from pytest import param as pp
from flpit import flp, FlpIt
from helpers import Falsy, Bomb


# ---------------------------------------------------------------------------
# Any()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("data", "p_expected", "n_expected"),
    [
        # 1. Empty collection (Both yield False)
        pp([], False, False, id="empty"),

        # 2. Elements exist but all are falsy (Python checks truthiness -> False, .NET checks presence -> True)
        pp([False, False], False, True, id="all_false_bools"),
        pp([0, 0, 0], False, True, id="all_zeros"),
        pp([None, None], False, True, id="all_nones"),
        pp([False, 0, None, ""], False, True, id="mixed_falsy"),

        # 3. Elements exist with at least one truthy value (Both yield True)
        pp([True], True, True, id="single_true"),
        pp([False, True, False], True, True, id="mixed_with_true"),
        pp([0, 42, 0], True, True, id="mixed_with_truthy_int"),

        # 4.
        pp([[]], False, True, id="single_empty_list"),
        pp([{}], False, True, id="single_empty_dict"),
        pp([""], False, True, id="empty_string_element"),
        pp([Falsy()], False, True, id="custom_falsy_object"),
    ],
)
def test_any_vs_any(flp_type, data: list, p_expected: bool, n_expected: bool) -> None:
    it: FlpIt[Any] = flp_type(data)

    p_any = any(it)
    n_any = it.any()

    assert p_any == p_expected
    assert n_any == n_expected


def test_any_short_circuits(flp_type) -> None:

    data: FlpIt[bool | Any] = flp_type([True, Bomb()])

    assert any(data) is True
    assert flp_type(data).any() is True


def test_any_no_truthy_invocation(flp_type)-> None:
    data: list[Any] = [Bomb()]

    with pytest.raises(AssertionError):
        any(flp_type(data))

    assert flp_type(data).any() == True


def test_any_propagates_iterator_error(flp_type) -> None:
    def broken_iterator():
        raise AssertionError("iterator failed before yielding")
        yield  # makes this a generator function

    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        any(broken_iterator())

    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        flp_type(broken_iterator()).any()


# ---------------------------------------------------------------------------
# Any(predicate)
# ---------------------------------------------------------------------------


def test_any_predicate_no_match(flp_type) -> None:
    data = flp_type([1, 2, 3])

    assert data.any(lambda x: x > 10) is False


def test_any_predicate_match(flp_type) -> None:
    data = flp_type([1, 2, 3])

    assert data.any(lambda x: x == 2) is True


def test_any_predicate_empty(flp_type) -> None:
    data = flp_type([])

    assert data.any(lambda x: True) is False


def test_any_predicate_short_circuits(flp_type) -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return x == 2

    data = flp_type([1, 2, 3])

    assert data.any(predicate) is True
    assert seen == [1, 2]


def test_any_predicate_evaluates_predicate_not_element_truthiness(flp_type) -> None:
    data = flp_type([Bomb()])

    assert data.any(lambda _: True) is True


def test_any_predicate_propagates_error(flp_type) -> None:
    def predicate(_):
        raise AssertionError("predicate failed")

    data = flp_type([1])

    with pytest.raises(AssertionError, match="predicate failed"):
        data.any(predicate)


def test_any_predicate_can_match_falsy_elements(flp_type) -> None:
    data = flp_type([0, None, False, ""])

    assert data.any(lambda x: x is None) is True
    assert data.any(lambda x: x == 42) is False


def test_any_predicate_receives_elements_in_order(flp_type) -> None:
    seen = []

    def predicate(x):
        seen.append(x)
        return False

    data = flp_type([1, 2, 3])

    assert data.any(predicate) is False
    assert seen == [1, 2, 3]


# ---------------------------------------------------------------------------
# Any(predicate)
#
# Truthiness semantics are already tested above through builtin any().
# Here we only verify that the predicate result is passed to builtin any().
# ---------------------------------------------------------------------------
def test_any_predicate_uses_builtin_any(flp_type):
    seen = []
    real_any = any

    def predicate(x):
        return x > 1

    def spy(iterable):
        def recording():
            for value in iterable:
                seen.append(value)
                yield value

        return real_any(recording())

    with patch("builtins.any", side_effect=spy) as mocked_any:
        result = flp_type([1, 2, 3]).any(predicate)

    assert result is True
    mocked_any.assert_called_once()
    assert seen == [False, True]