from __future__ import annotations

from decimal import Decimal

import pytest

from flpit import flp, EmptySequenceError, FlpList
from flpit.core.linq import SelectorNoneError

NAN = float("nan")
NEG_INF = float("-inf")


def _is_nan(x) -> bool:
    return x != x


@pytest.fixture(params=[flp.it, FlpList], ids=["FlpIt", "FlpList"])
def make(request):
    return request.param


@pytest.fixture(params=[True, False], ids=["min", "max"])
def is_min(request):
    return request.param


def _call(src, is_min, *args):
    return (src.min if is_min else src.max)(*args)


def _call_by(src, is_min, key):
    return (src.min_by if is_min else src.max_by)(key)


# ---------------------------------------------------------------- selector None
@pytest.mark.parametrize("method", ["min", "max"])
def test_none_selector_raises_eagerly_for_values(make, method) -> None:
    with pytest.raises(SelectorNoneError):
        getattr(make([1, 2]), method)(None)
    with pytest.raises(SelectorNoneError):
        getattr(make([]), method)(None)


@pytest.mark.parametrize("method", ["min_by", "max_by"])
def test_none_key_selector_raises_when_there_is_an_element(make, method) -> None:
    with pytest.raises(SelectorNoneError):
        getattr(make([1, 2]), method)(None)


@pytest.mark.parametrize("method", ["min_by", "max_by"])
def test_none_key_selector_on_empty_source_returns_none(make, method) -> None:
    assert getattr(make([]), method)(None) is None


def test_none_selector_does_not_consume_one_shot_for_values() -> None:
    it = flp.it(iter([1, 2, 3]))
    with pytest.raises(SelectorNoneError):
        it.min(None)
    assert it.max() == 3


# ----------------------------------------------------------------------- empty
# flpit has no runtime generics, so every type is None-able: empty -> None.
@pytest.mark.parametrize("method", ["min", "max"])
def test_empty_returns_none(make, method) -> None:
    assert getattr(make([]), method)() is None
    assert getattr(make([]), method)(lambda x: x) is None


@pytest.mark.parametrize("method", ["min_by", "max_by"])
def test_empty_by_returns_none(make, method) -> None:
    assert getattr(make([]), method)(lambda x: x) is None


# ------------------------------------------------------------- values + selector
def test_values_and_selector(make, is_min) -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    expected = 1 if is_min else 3
    assert _call(make(rows), is_min, lambda r: r[1]) == expected
    assert _call(make([3, 1, 2]), is_min) == expected


def test_selector_value_error_not_relabelled(make, is_min) -> None:
    def boom(_):
        raise ValueError("selector broke")

    with pytest.raises(ValueError, match="selector broke"):
        _call(make([1, 2]), is_min, boom)
    with pytest.raises(ValueError, match="selector broke"):
        _call_by(make([1, 2]), is_min, boom)


def test_selector_called_once_per_element_in_order(is_min) -> None:
    calls: list[int] = []

    def sel(x: int) -> int:
        calls.append(x)
        return x

    _call(flp.it(iter([4, 2, 9])), is_min, sel)
    assert calls == [4, 2, 9]
    calls.clear()
    _call_by(flp.it(iter([4, 2, 9])), is_min, sel)
    assert calls == [4, 2, 9]


# ------------------------------------------------------------------ None values
def test_values_skip_none(make, is_min) -> None:
    expected = 1 if is_min else 5
    assert _call(make([None, 5, None, 1, None]), is_min) == expected
    assert _call(make([("x", None), ("y", 5), ("z", 1)]), is_min, lambda r: r[1]) == expected


def test_values_all_none_returns_none(make, is_min) -> None:
    assert _call(make([None, None]), is_min) is None


# -------------------------------------------------------------------- NaN values
# .NET total order: NaN is smaller than every value (incl. -inf).
# min -> NaN if present; max -> NaN only when every value is NaN.
def _nan_expected(is_min, data):
    return None if is_min else max(x for x in data if x is not None and x == x)


@pytest.mark.parametrize(
    "data",
    [[NAN, 1.0, 2.0], [1.0, NAN, 2.0], [-5.6, 3.0, NAN], [3, 2, NAN, 1], [None, 1.0, NAN, -9.0]],
)
def test_values_nan_follows_total_order(make, is_min, data) -> None:
    for got in (_call(make(data), is_min), _call(make(data), is_min, lambda x: x)):
        if is_min:
            assert _is_nan(got)
        else:
            assert got == _nan_expected(is_min, data)


def test_values_nan_in_later_chunk(make, is_min) -> None:
    data = [float(i) for i in range(5000)] + [NAN] + [-1.0]
    got = _call(make(data), is_min)
    assert _is_nan(got) if is_min else got == 4999.0


def test_max_nan_vs_neg_inf(make) -> None:
    assert make([NAN, float("-inf")]).max() == float("-inf")
    assert make([float("-inf"), NAN]).max() == float("-inf")


def test_all_nan_returns_nan(make, is_min) -> None:
    assert _is_nan(_call(make([NAN, NAN, NAN]), is_min))


def test_values_across_chunks_without_nan(make, is_min) -> None:
    data = [float(i) for i in range(5000, 0, -1)]
    assert _call(make(data), is_min) == (1.0 if is_min else 5000.0)


def test_values_decimal_nan(make, is_min) -> None:
    got = _call(make([Decimal(1), Decimal("NaN"), Decimal(-3)]), is_min)
    if is_min:
        assert _is_nan(got)
    else:
        assert got == Decimal(1)


def test_values_strings(make, is_min) -> None:
    assert _call(make(["b", "a", "c"]), is_min) == ("a" if is_min else "c")


# ----------------------------------------------------------------------- *_by
def test_by_returns_element(make, is_min) -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    assert _call_by(make(rows), is_min, lambda r: r[1]) == (("b", 1) if is_min else ("a", 3))


def test_by_ties_keep_first(make, is_min) -> None:
    rows = [("a", 1), ("b", 1), ("c", 1)]
    assert _call_by(make(rows), is_min, lambda r: r[1]) == ("a", 1)


def test_by_ties_keep_first_across_chunks(make, is_min) -> None:
    rows = [(i, 7) for i in range(3000)]
    assert _call_by(make(rows), is_min, lambda r: r[1]) == (0, 7)


def test_by_skips_none_keys(make, is_min) -> None:
    rows = [("n1", None), ("a", 4), ("n2", None), ("b", 2), ("c", 9)]
    assert _call_by(make(rows), is_min, lambda r: r[1]) == (("b", 2) if is_min else ("c", 9))


def test_by_all_none_keys_returns_first_element(make, is_min) -> None:
    rows = [("n1", None), ("n2", None)]
    assert _call_by(make(rows), is_min, lambda r: r[1]) == ("n1", None)


def test_by_across_chunks(make, is_min) -> None:
    rows = [(i, 5000 - i) for i in range(5000)]
    got = _call_by(make(rows), is_min, lambda r: r[1])
    assert got == ((4999, 1) if is_min else (0, 5000))


def test_by_nan_keys_follow_net_comparer(make) -> None:
    rows = [("a", 3.0), ("n", NAN), ("b", 1.0), ("m", NAN)]
    # NaN orders below everything: min_by -> first NaN element, max_by ignores NaN
    assert make(rows).min_by(lambda r: r[1])[0] == "n"
    assert make(rows).max_by(lambda r: r[1]) == ("a", 3.0)


def test_by_all_nan_keys(make, is_min) -> None:
    rows = [("a", NAN), ("b", NAN)]
    assert _call_by(make(rows), is_min, lambda r: r[1])[0] == "a"


def test_by_non_comparable_keys_raise_type_error(make, is_min) -> None:
    with pytest.raises(TypeError):
        _call_by(make([1, "a"]), is_min, lambda x: x)
