from __future__ import annotations

import pytest

from flpit import flp, EmptySequenceError, FlpList
from flpit.core.linq import SelectorNoneError


@pytest.fixture(params=[flp.it, FlpList], ids=["FlpIt", "FlpList"])
def make(request):
    return request.param


def test_min_selector_returns_projected_value(make) -> None:
    rows = [("a", 3), ("b", 1), ("c", 2)]
    assert make(rows).min(lambda r: r[1]) == 1


def test_min_selector_empty_returns_none(make) -> None:
    assert make([]).min(lambda x: x) is None


def test_min_selector_none_raises_eagerly(make) -> None:
    with pytest.raises(SelectorNoneError):
        make([1, 2]).min(None)


def test_min_selector_does_not_relabel_value_error(make) -> None:
    def selector(_):
        raise ValueError("selector broke")

    with pytest.raises(ValueError, match="selector broke"):
        make([1, 2]).min(selector)


def test_min_selector_runs_once_per_element_in_one_pass() -> None:
    calls: list[int] = []

    def selector(x: int) -> int:
        calls.append(x)
        return -x

    assert flp.it(iter([1, 2, 3])).min(selector) == -3
    assert calls == [1, 2, 3]


def test_min_selector_is_not_applied_to_original_elements_ordering(make) -> None:
    assert make(["bb", "a", "ccc"]).min(len) == 1


def test_min_selector_single_use_source_is_consumed_once() -> None:
    it = flp.it(iter([3, 1, 2]))
    assert it.min(lambda x: x * 2) == 2
    assert it.min(lambda x: x) is None  # the one-shot source is exhausted


def test_min_none(make) -> None:
    assert 1 == make([1, None, 2]).min()


def test_min_skips_leading_and_interleaved_none(make) -> None:
    assert make([None, None, 5, None, 3, None]).min() == 3


def test_min_all_none_returns_none(make) -> None:
    assert make([None, None]).min() is None


def test_min_selector_skips_none_projections(make) -> None:
    rows = [("a", None), ("b", 4), ("c", 2), ("d", None)]
    assert make(rows).min(lambda r: r[1]) == 2
    assert make(rows).min(lambda r: None) is None


def test_min_none_is_single_pass_on_one_shot_iterator() -> None:
    seen: list[object] = []

    def gen():
        for x in (None, 4, None, 2, 9):
            seen.append(x)
            yield x

    assert flp.it(gen()).min() == 2
    assert seen == [None, 4, None, 2, 9]


NAN = float("nan")


def _is_nan(x) -> bool:
    return x != x


@pytest.mark.parametrize(
    "data",
    [
        [NAN, 1.0, 2.0],
        [1.0, NAN, 2.0],
        [-5.6, 3.0, NAN],
        [3, 2, NAN, 1],
        [None, 1.0, NAN, -9.0],
    ],
)
def test_min_nan_anywhere_returns_nan(make, data) -> None:
    assert _is_nan(make(data).min())
    assert _is_nan(make(data).min(lambda x: x))


def test_min_nan_in_later_chunk_returns_nan(make) -> None:
    data = [float(i) for i in range(5000)] + [NAN] + [-1.0]
    assert _is_nan(make(data).min())


def test_min_float_without_nan_across_chunks(make) -> None:
    data = [float(i) for i in range(5000, 0, -1)]
    assert make(data).min() == 1.0


def test_min_decimal_nan_returns_nan(make) -> None:
    from decimal import Decimal
    assert _is_nan(make([Decimal(1), Decimal("NaN"), Decimal(-3)]).min())


def test_min_strings_unaffected(make) -> None:
    assert make(["b", "a", "c"]).min() == "a"
