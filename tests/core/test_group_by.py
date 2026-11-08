import pytest

from flpit import SelectorNoneError


def test_KeySelectorNull(flp_type):
    """
    The .NET tests cover null key selectors across several overloads.
    Those overloads do not exist in FlpIt yet.

    The Python implementation must enforce the same null-selector contract independently, regardless of overload availability.
    """
    with pytest.raises(SelectorNoneError):
        flp_type([1]).group_by(None)
