from __future__ import annotations

import pytest


from flpit import flp, EmptySequenceError, MultipleMatchesError, MultipleElementsError


def test_first_or_default_uses_explicit_none_to_mean_no_predicate() -> None:
    assert flp.it([1, 2]).first_or_default(99, None) == 1


def test_first_uses_none_to_mean_no_predicate() -> None:
    assert flp.it([1, 2]).first(None) == 1


def test_count_uses_none_to_mean_no_predicate() -> None:
    assert flp.it([1, 2]).count(None) == 2


def test_single_uses_none_to_mean_no_predicate() -> None:
    with pytest.raises(MultipleElementsError):
        flp.it([1, 2]).single()


def test_empty_error_message_is_consistent_for_aggregate() -> None:
    with pytest.raises(EmptySequenceError):
        flp.it([]).aggregate(lambda a, b: a + b)


def test_min_max_empty_messages_are_consistent() -> None:
    for method in ("min", "max", "min_by", "max_by"):
        with pytest.raises(ValueError, match="Sequence contains no elements"):
            if method.endswith("_by"):
                getattr(flp.it([]), method)(lambda x: x)
            else:
                getattr(flp.it([]), method)()


def test_first_and_single_messages_distinguish_zero_and_many(flp_type) -> None:
    with pytest.raises(EmptySequenceError):
        flp_type([]).first()
    with pytest.raises(EmptySequenceError):
        flp_type([]).single()
    with pytest.raises(MultipleElementsError):
        flp_type([1, 2]).single()

