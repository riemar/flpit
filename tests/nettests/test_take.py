"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Tests for the FlpIt ``take`` operator.

Ported to pytest/Python from the .NET Runtime System.Linq TakeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/TakeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

These test are just a sm subset as several as e.g. Take(1..2) is not possible in python
"""

import pytest

from flpit import (
    flp,
    EmptySequenceError,
    NoMatchError,
    MultipleElementsError,
    MultipleMatchesError,
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


def test_same_results_on_repeat_calls(flp_type):
    data = [9999, 0, 888, -1, 66, -777, 1, 2, -12345]
    query = flp_type(data)

    assert materialize(query.take(9)) == materialize(query.take(9))
    assert materialize(query.take(7)) == materialize(query.take(7))


def test_same_results_on_repeat_calls_for_strings(flp_type):
    data = ["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]
    query = flp_type(data)

    assert materialize(query.take(7)) == [
        "!@#$%^",
        "C",
        "AAA",
        "",
        "Calling Twice",
        "SoS",
        "",
    ]
    assert materialize(query.take(7)) == materialize(query.take(7))


def test_empty_source_with_positive_count(flp_type):
    assert materialize(flp_type([]).take(5)) == []


def test_non_empty_source_with_negative_count(flp_type):
    source = flp_type([2, 5, 9, 1])
    assert materialize(source.take(-5)) == []
    assert materialize(source.take(-1)) == []


def test_non_empty_source_with_zero_count(flp_type):
    source = flp_type([2, 5, 9, 1])
    assert materialize(source.take(0)) == []


def test_non_empty_source_with_one(flp_type):
    assert materialize(flp_type([2, 5, 9, 1]).take(1)) == [2]


def test_take_all_exactly(flp_type):
    source = [2, 5, 9, 1]
    assert materialize(flp_type(source).take(4)) == source


def test_take_all_but_one(flp_type):
    assert materialize(flp_type([2, 5, 9, 1]).take(3)) == [2, 5, 9]


def test_take_excessive_count(flp_type):
    source = [2, 5, None, 9, 1]
    assert materialize(flp_type(source).take(5)) == source
    assert materialize(flp_type(source).take(50)) == source


def test_take_preserves_none_values(flp_type):
    value = None
    result = materialize(flp_type([1, value, 3]).take(2))
    assert result[0] == 1
    assert result[1] is value


def test_follow_with_take(flp_type):
    source = flp_type([5, 6, 7, 8])

    result = source.take(5).take(3).take(2).take(40)

    assert materialize(result) == [5, 6]


def test_repeat_enumerating(flp_type):
    source = flp_type([1, 2, 3, 4, 5])
    taken = source.take(3)

    assert materialize(taken) == [1, 2, 3]
    assert materialize(taken) == [1, 2, 3]


def test_large_counts_do_not_change_the_result(flp_type):
    for count in (1000, 1_000_000, 2**63 - 1):
        assert materialize(flp_type([1, 2, 3]).take(count)) == [1, 2, 3]


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
