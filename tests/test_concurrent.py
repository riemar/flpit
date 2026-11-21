"""flpit-specific ConcurrentDictionary tests: what upstream's tests cannot observe.

* Races: the factories of ``get_or_add`` / ``add_or_update`` run outside the lock. These tests
  make another thread write while a factory runs, and check that the write is never lost.
* The runtime overload resolution: whether a callable in the value slot is a factory or the value.
"""
from __future__ import annotations

import functools
import threading
import types
import typing
from collections.abc import Callable
from typing import Annotated, Any

import pytest

from flpit.concurrent import (
    CBag,
    CDict,
    ConcurrentBag,
    ConcurrentDictionary,
    ConcurrentQueue,
    ConcurrentStack,
    CQueue,
    CStack,
)
from flpit.task import Task


def _on_other_thread(action) -> None:
    thread = threading.Thread(target=action)
    thread.start()
    thread.join()


def test_add_or_update_retries_when_the_value_changed_while_updating() -> None:
    d = ConcurrentDictionary[str, int]({"k": 0})
    seen: list[int] = []

    def update(_: str, value: int) -> int:
        seen.append(value)
        if len(seen) == 1:
            _on_other_thread(lambda: d.__setitem__("k", 100))  # a write while the factory runs
        return value + 1

    assert d.add_or_update("k", -1, update) == 101

    assert seen == [0, 100]  # retried on the new value instead of overwriting it
    assert d["k"] == 101


def test_add_or_update_updates_when_the_key_was_added_while_adding() -> None:
    d = ConcurrentDictionary[str, int]()

    def add(_: str) -> int:
        _on_other_thread(lambda: d.try_add("k", 100))  # someone else adds the key first
        return 1

    result = d.add_or_update("k", add_value_factory=add, update_value_factory=lambda _, v: v + 1)

    assert result == 101
    assert d["k"] == 101


def test_add_or_update_retries_when_the_key_was_removed_while_updating() -> None:
    d = ConcurrentDictionary[str, int]({"k": 0})
    calls = 0

    def update(_: str, value: int) -> int:
        nonlocal calls
        calls += 1
        _on_other_thread(lambda: d.try_remove("k"))
        return value + 1

    assert d.add_or_update("k", 7, update) == 7  # the key is gone: the add value wins

    assert calls == 1
    assert d["k"] == 7


def test_get_or_add_returns_the_value_added_while_the_factory_ran() -> None:
    d = ConcurrentDictionary[str, str]()

    def factory(_: str) -> str:
        _on_other_thread(lambda: d.try_add("k", "first"))
        return "second"

    assert d.get_or_add("k", value_factory=factory) == "first"
    assert d["k"] == "first"


def test_add_or_update_counts_exactly_under_contention() -> None:
    d = ConcurrentDictionary[str, int]()
    threads, increments = 8, 2000
    barrier = threading.Barrier(threads)

    def count() -> None:
        barrier.wait()
        for _ in range(increments):
            d.add_or_update("n", 1, lambda _, v: v + 1)

    Task.wait_all([Task.run(count) for _ in range(threads)])

    assert d["n"] == threads * increments


def test_try_update_compares_with_the_current_value() -> None:
    d = ConcurrentDictionary[str, int]({"k": 1})

    assert not d.try_update("k", 3, 2)  # 2 is not the current value
    assert d["k"] == 1

    assert d.try_update("k", 3, 1)
    assert d["k"] == 3


# --- what a callable in the value slot means: the value type decides (C# overload resolution) ---

def test_a_callable_is_a_factory_when_values_are_not_callable() -> None:
    d = ConcurrentDictionary[str, int]()

    assert d.get_or_add("a", len) == 1
    assert d.get_or_add("bb", lambda key, extra: len(key) + extra, 10) == 12
    assert d.add_or_update("c", lambda key: 5, lambda _, n: n + 1) == 5
    assert d.add_or_update("c", lambda key: 5, lambda _, n: n + 1) == 6
    assert d.add_or_update("d", lambda key, extra: extra, lambda _, n, extra: n + extra, 3) == 3

    assert dict(d.items()) == {"a": 1, "bb": 12, "c": 6, "d": 3}


def test_a_callable_is_the_value_when_values_are_callable() -> None:
    def on_click() -> None: ...

    handlers = ConcurrentDictionary[str, Callable[[], None]]()

    assert handlers.get_or_add("click", on_click) is on_click
    assert handlers.add_or_update("hover", on_click, lambda _, old: old) is on_click
    assert handlers["click"] is on_click

    # value_factory= still says "factory" explicitly
    assert handlers.get_or_add("key", value_factory=lambda _: on_click) is on_click


@pytest.mark.parametrize(
    ("value_type", "callable_values"),
    [
        (int, False),
        (Any, False),               # as C# picks the Func overload for object
        (object, False),
        (list[int], False),
        (int | None, False),
        (Callable[[], int], True),
        (int | Callable[[], int], True),
        (type, True),               # classes are callable
        (type[int], True),
        (functools.partial, True),  # a class with __call__
        (Annotated[Callable[[], int], "meta"], True),
    ],
)
def test_value_types(value_type: Any, callable_values: bool) -> None:
    d = ConcurrentDictionary[str, value_type]()  # type: ignore[valid-type]

    stored = d.get_or_add("k", len)

    assert (stored is len) == callable_values


def test_types_are_required() -> None:
    with pytest.raises(TypeError, match=r"ConcurrentDictionary\[str, int\]\(\)"):
        ConcurrentDictionary()
    with pytest.raises(TypeError, match="type arguments"):
        ConcurrentDictionary({"a": 1})


def test_the_alias_is_a_public_generic_alias() -> None:
    alias = ConcurrentDictionary[str, int]

    assert isinstance(alias, types.GenericAlias)
    assert typing.get_origin(alias) is ConcurrentDictionary
    assert typing.get_args(alias) == (str, int)
    assert alias == CDict[str, int]

    with pytest.raises(TypeError, match="Too few arguments"):
        ConcurrentDictionary[str]  # type: ignore[misc]
    with pytest.raises(TypeError, match="Too many arguments"):
        ConcurrentDictionary[str, int, int]  # type: ignore[misc]


def test_subclasses_carry_their_types() -> None:
    class Handlers(ConcurrentDictionary[str, Callable[[], None]]):
        pass

    class Counts[K](ConcurrentDictionary[K, int]):
        pass

    def on_click() -> None: ...

    assert Handlers().get_or_add("click", on_click) is on_click
    assert Counts[str]().get_or_add("abc", len) == 3

    with pytest.raises(TypeError, match=r"Counts\[\.\.\.\]\(\)"):
        Counts()


def test_dictionaries_created_inside_a_factory_need_their_own_types() -> None:
    outer = ConcurrentDictionary[str, Any]()

    with pytest.raises(TypeError):
        outer.get_or_add("k", value_factory=lambda _: ConcurrentDictionary())  # no types: still an error

    inner = outer.get_or_add("k", value_factory=lambda _: ConcurrentDictionary[str, int]())
    assert isinstance(inner, ConcurrentDictionary)


def test_factory_argument_needs_a_factory() -> None:
    d = ConcurrentDictionary[str, int]()

    with pytest.raises(TypeError, match="factory_argument"):
        d.get_or_add("k", 1, 2)
    with pytest.raises(TypeError, match="factory_argument"):
        d.add_or_update("k", 1, lambda _, n, a: n, 2)


def test_setdefault_always_stores_the_default() -> None:
    d = ConcurrentDictionary[str, Any]()

    assert d.setdefault("k", len) is len  # Python semantics: a value, never a factory


def test_short_names_are_the_same_classes() -> None:
    assert CDict is ConcurrentDictionary
    assert CQueue is ConcurrentQueue
    assert CStack is ConcurrentStack
    assert CBag is ConcurrentBag

    counts = CDict[str, int]()
    counts.add_or_update("w", 1, lambda _, n: n + 1)
    assert isinstance(counts, ConcurrentDictionary)
    assert counts["w"] == 1
