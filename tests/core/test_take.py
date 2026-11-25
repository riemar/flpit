"""
FlpIt-specific behaviour of take().

The .NET port lives in tests/nettests/linq/test_take.py. This module keeps the architectural invariants from
.agents/rules.md that the port does not cover (deferred execution, no consumption for ``count <= 0``,
short-circuiting, no truth-testing of elements, repeatable Python sources). Moved here unchanged from the
earlier tests/nettests/linq/test_take.py.
"""

import pytest

from flpit import (
    EmptySequenceError,
    MultipleElementsError,
    MultipleMatchesError,
    NoMatchError,
    flp,
)
from tests.helpers import (
    Bomb,
    Falsy,
    NoIterList,
    broken_iterator,
)


def materialize(query):
    """Materialize either FlpIt or FlpList through the common iterable protocol."""
    return list(query)



def test_take_does_not_truth_test_elements(flp_type):
    bomb = Bomb()
    falsy = Falsy()

    result = materialize(flp_type([bomb, falsy]).take(2))

    assert result[0] is bomb
    assert result[1] is falsy


def test_flpit_take_zero_does_not_iterate_source():
    source = flp.it(NoIterList([1, 2, 3]))

    query = source.take(0)

    assert materialize(query) == []


def test_flpit_take_negative_does_not_iterate_source():
    source = flp.it(NoIterList([1, 2, 3]))

    query = source.take(-10)

    assert materialize(query) == []


def test_flpit_take_is_deferred_until_iteration():
    query = flp.it(broken_iterator()).take(1)

    # Building the query must not pull from the source.
    with pytest.raises(AssertionError, match="iterator failed before yielding"):
        materialize(query)


def test_flpit_take_only_consumes_the_requested_elements():
    consumed = []

    def source():
        for value in range(10):
            consumed.append(value)
            yield value

    query = flp.it(source()).take(3)

    assert materialize(query) == [0, 1, 2]
    assert consumed == [0, 1, 2]


def test_flpit_take_does_not_pull_past_the_end_of_a_short_source():
    consumed = []

    def source():
        for value in range(2):
            consumed.append(value)
            yield value

    assert materialize(flp.it(source()).take(10)) == [0, 1]
    assert consumed == [0, 1]


def test_take_on_a_repeatable_python_source_is_repeatable(flp_type):
    source = [1, 2, 3, 4, 5]
    query = flp_type(source).take(3)

    first = materialize(query)
    second = materialize(query)

    assert first == [1, 2, 3]
    assert second == [1, 2, 3]


@pytest.mark.parametrize(
    ("exception_type", "message"),
    [
        (EmptySequenceError, "Sequence contains no elements"),
        (NoMatchError, "Sequence contains no matching elements"),
        (
                MultipleMatchesError,
                "Sequence contains more than one matching element",
        ),
        (
                MultipleElementsError,
                "Sequence contains more than one element",
        ),
    ],
)
def test_required_helper_exceptions_exist(exception_type, message):
    error = exception_type()
    assert isinstance(error, ValueError)
    assert str(error) == message
