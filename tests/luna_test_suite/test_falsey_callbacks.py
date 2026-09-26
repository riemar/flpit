from __future__ import annotations

import pytest
from flpit import flp

class FalseyPredicate:
    def __call__(self, value):
        return value % 2 == 0

    def __bool__(self):
        return False


@pytest.mark.parametrize(
    "method, expected",
    [
        ("count", 2),
    ],
)
def test_falsey_callable_is_still_a_predicate_for_count(method, expected) -> None:
    predicate = FalseyPredicate()
    assert getattr(flp.it([1, 2, 3, 4]), method)(predicate) == expected


def test_falsey_callable_is_still_a_predicate_for_first() -> None:
    predicate = FalseyPredicate()
    assert flp.it([1, 2, 3, 4]).first(predicate) == 2


def test_falsey_callable_is_still_a_predicate_for_first_or_default() -> None:
    predicate = FalseyPredicate()
    assert flp.it([1, 2, 3, 4]).first_or_default(99, predicate) == 2


def test_falsey_callable_is_still_a_predicate_for_single() -> None:
    predicate = FalseyPredicate()
    with pytest.raises(ValueError, match="more than one matching"):
        flp.it([2, 4]).single(predicate)

