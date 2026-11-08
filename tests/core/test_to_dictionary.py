"""
Tests for FlpIt.to_dictionary() and FlpList.to_dictionary().
"""

import pytest

from flpit import flp, SelectorNoneError


def test_ToDictionary_UsesSourceElementAsValue(flp_type):
    source = [("a", 1), ("b", 2), ("c", 3)]

    result = flp_type(source).to_dictionary(lambda item: item[0])

    assert result == {"a": ("a", 1), "b": ("b", 2), "c": ("c", 3)}
    assert list(result) == ["a", "b", "c"]


def test_ToDictionary_WithElementSelector(flp_type):
    source = [("a", 1), ("b", 2), ("c", 3)]

    result = flp_type(source).to_dictionary(lambda item: item[0], lambda item: item[1])

    assert result == {"a": 1, "b": 2, "c": 3}


def test_ToDictionary_EmptySource(flp_type):
    assert flp_type([]).to_dictionary(lambda item: item) == {}


def test_ToDictionary_RunOnce():
    source = (item for item in [("a", 1), ("b", 2)])

    assert flp.it(source).to_dictionary(lambda item: item[0], lambda item: item[1]) == {
        "a": 1,
        "b": 2,
    }


def test_ToDictionary_DuplicateKeysRaise(flp_type):
    with pytest.raises(ValueError, match="same key"):
        flp_type([("a", 1), ("a", 2)]).to_dictionary(lambda item: item[0])


def test_ToDictionary_NullKeySelectorRaises(flp_type):
    with pytest.raises(SelectorNoneError):
        flp_type([1, 2]).to_dictionary(None)


def test_ToDictionary_NullElementSelectorRaises(flp_type):
    with pytest.raises(SelectorNoneError):
        flp_type([1, 2]).to_dictionary(lambda item: item, None)


def test_ToDictionary_AllowsNoneKey(flp_type):
    assert flp_type([(None, 1)]).to_dictionary(lambda item: item[0], lambda item: item[1]) == {
        None: 1
    }
