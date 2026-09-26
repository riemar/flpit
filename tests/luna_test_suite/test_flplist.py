from __future__ import annotations


from flpit import flp, FlpList


def test_add_appends_single_item() -> None:
    result = FlpList([1, 2])
    result.add(3)
    assert result == [1, 2, 3]


def test_add_preserves_existing_items() -> None:
    result = FlpList([1])
    item = object()
    result.add(item)
    assert result[1] is item


def test_add_range_accepts_list() -> None:
    result = FlpList([1])
    result.add_range([2, 3])
    assert result == [1, 2, 3]


def test_add_range_accepts_tuple() -> None:
    result = FlpList([1])
    result.add_range((2, 3))
    assert result == [1, 2, 3]


def test_add_range_accepts_userlist() -> None:
    result = FlpList([1])
    result.add_range(flp.FlpList([2, 3]))
    assert result == [1, 2, 3]


def test_add_range_consumes_generator_once() -> None:
    calls = []

    def source():
        for value in [2, 3, 4]:
            calls.append(value)
            yield value

    result = FlpList([1])
    result.add_range(source())
    assert result == [1, 2, 3, 4]
    assert calls == [2, 3, 4]


def test_add_range_empty_generator_is_noop() -> None:
    calls = []

    def source():
        calls.append("iterated")
        if False:
            yield 1

    result = FlpList([1])
    result.add_range(source())
    assert result == [1]
    assert calls == ["iterated"]


def test_add_range_handles_infinite_generator_only_until_source_is_consumed() -> None:
    def source():
        yield 2
        yield 3

    result = FlpList([1])
    result.add_range(source())
    assert result == [1, 2, 3]


def test_flplist_query_methods_return_flpit() -> None:
    result = FlpList([1, 2, 3]).where(lambda x: x > 1)
    assert isinstance(result, flp.FlpIt)
    assert list(result) == [2, 3]


def test_flplist_to_list_returns_flplist() -> None:
    result = FlpList([1, 2, 3]).select(lambda x: x * 2).to_list()
    assert isinstance(result, FlpList)
    assert result == [2, 4, 6]


def test_flplist_slice_is_supported() -> None:
    result = FlpList([1, 2, 3, 4])
    assert result[1:3] == [2, 3]


def test_flplist_extend_inherited_behavior() -> None:
    result = FlpList([1])
    result.extend([2, 3])
    assert result == [1, 2, 3]

