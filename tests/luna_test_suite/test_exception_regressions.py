from __future__ import annotations

import pytest

import flp
from flp.core.linq import EmptySequenceError


def test_first_or_default_does_not_swallow_value_error_from_predicate(flp_type) -> None:
    def predicate(_):
        raise ValueError("predicate broke")

    with pytest.raises(ValueError, match="predicate broke"):
        flp_type([1]).first_or_default(99, predicate)


@pytest.mark.parametrize("method", ["min", "max"])
def test_min_max_do_not_relabel_user_value_error(method) -> None:
    class BrokenOrder:
        def __lt__(self, other):
            raise ValueError("comparison broke")

        def __gt__(self, other):
            raise ValueError("comparison broke")

    values = [BrokenOrder(), BrokenOrder()]
    with pytest.raises(ValueError, match="comparison broke"):
        getattr(flp.it(values), method)()


def test_min_by_does_not_relabel_selector_value_error(flp_type) -> None:
    def selector(_):
        raise ValueError("selector broke")

    with pytest.raises(ValueError, match="selector broke"):
        flp_type([1, 2]).min_by(selector)


def test_max_by_does_not_relabel_selector_value_error(flp_type) -> None:
    def selector(_):
        raise ValueError("selector broke")

    with pytest.raises(ValueError, match="selector broke"):
        flp_type([1, 2]).max_by(selector)


def test_first_or_default_still_converts_actual_no_match_to_default(flp_type) -> None:
    assert flp_type([1, 2]).first_or_default(99, lambda x: x > 10) == 99


def test_empty_sequence_error_is_a_value_error() -> None:
    assert issubclass(EmptySequenceError, ValueError)
