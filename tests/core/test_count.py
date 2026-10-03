from collections.abc import Sequence
from flpit import flp
import pytest

def test_in_flp_list():
    lst = flp.lst([1,2,3])
    if 2 in lst:
        assert True

def test_count_predicate_none_callable():
    lst = flp.lst([1,2,3])
    with pytest.raises(TypeError):
        assert 1 == lst.count(2)