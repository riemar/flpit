import pytest

from flpit import flp, FlpIt


def _make_data(size: int) -> list[dict[str, int]]:
    return [
        {
            "k1": i % 100,
            "k2": (i * 7) % 100,
            "k3": (i * 13) % 100,
            "k4": (i * 17) % 100,
            "k5": (i * 23) % 100,
            "k6": (i * 29) % 100,
            "k7": (i * 31) % 100,
            "k8": (i * 37) % 100,
        }
        for i in range(size, 0, -1)
    ]


def _build_query(data, levels: int):
    query = FlpIt(data).order_by(lambda x: x["k1"])

    for i in range(2, levels + 1):
        query = query.then_by(lambda x, key=f"k{i}": x[key])

    return query


@pytest.mark.benchmark
@pytest.mark.parametrize("levels", [1, 2, 4, 8])
@pytest.mark.parametrize("size", [10_000, 100_000])
def test_ordered_it_benchmark(benchmark, levels: int, size: int):
    data = _make_data(size)

    def run():
        query = _build_query(data, levels)
        return query.to_list()

    result = benchmark(run)

    assert len(result) == size


@pytest.mark.benchmark
def test_ordered_it_cached_enumeration_benchmark(benchmark):
    data = _make_data(100_000)

    query = _build_query(data, 4)

    # First execution: materialization + sorting.
    list(query)

    def run():
        return list(query)

    result = benchmark(run)

    assert len(result) == 100_000


@pytest.mark.benchmark
def test_ordered_it_key_selector_benchmark(benchmark):
    data = _make_data(100_000)
    calls = 0

    def key(x):
        nonlocal calls
        calls += 1
        return x["k1"]

    query = FlpIt(data).order_by(key)

    result = benchmark(lambda: list(query))

    assert len(result) == 100_000
    assert calls == 100_000