"""Static inference checks for flpit.concurrent (run: uv run pyrefly check typing/check_concurrent.py)."""
from collections.abc import Callable
from typing import Literal, assert_type

from flpit.concurrent import CDict, ConcurrentBag, ConcurrentDictionary, ConcurrentQueue, ConcurrentStack
from flpit.core.comparers import EqualityComparer, IEqualityComparer

# --- ConcurrentDictionary -----------------------------------------------------------------------
COUNTS = ConcurrentDictionary[str, int]()

assert_type(COUNTS.try_add("a", 1), bool)
assert_type(COUNTS.try_get_value("a"), tuple[Literal[True], int] | tuple[Literal[False], None])
assert_type(COUNTS.try_remove("a"), tuple[Literal[True], int] | tuple[Literal[False], None])
assert_type(COUNTS.try_update("a", 2, 1), bool)
assert_type(COUNTS.get_or_add("a", 1), int)
assert_type(COUNTS.get_or_add("a", value_factory=len), int)


def length_plus(key: str, extra: int) -> int:
    return len(key) + extra


assert_type(COUNTS.get_or_add("a", value_factory=length_plus, factory_argument=1), int)
assert_type(COUNTS.add_or_update("a", 1, lambda k, n: n + 1), int)
assert_type(COUNTS.add_or_update("a", lambda k: len(k), lambda k, n: n + 1), int)
assert_type(COUNTS.add_or_update("a", add_value_factory=len, update_value_factory=lambda k, n: n + 1), int)
assert_type(COUNTS["a"], int)
assert_type(COUNTS.keys(), tuple[str, ...])
assert_type(COUNTS.items(), tuple[tuple[str, int], ...])
assert_type(COUNTS.to_array(), list[tuple[str, int]])
assert_type(COUNTS.comparer, IEqualityComparer[str])



def same_ignoring_case(x: str, y: str) -> bool:
    return x.casefold() == y.casefold()


IGNORE_CASE = EqualityComparer.create(same_ignoring_case, lambda s: hash(s.casefold()))
assert_type(IGNORE_CASE, EqualityComparer[str])
NAMES = ConcurrentDictionary[str, int](comparer=IGNORE_CASE)
FROM_PAIRS = ConcurrentDictionary[str, int]([("a", 1), ("b", 2)])
assert_type(FROM_PAIRS, ConcurrentDictionary[str, int])
SHORT = CDict[str, int]()  # the alias
assert_type(SHORT, ConcurrentDictionary[str, int])

# A callable in the value slot is a factory (C# overload resolution) ...
assert_type(COUNTS.get_or_add("a", len), int)
assert_type(COUNTS.get_or_add("a", length_plus, 1), int)
assert_type(COUNTS.add_or_update("a", len, lambda k, n: n + 1), int)
# ... unless the values are callable themselves: then it is the value.
HANDLERS = ConcurrentDictionary[str, Callable[[], None]]()
assert_type(HANDLERS.get_or_add("click", lambda: None), Callable[[], None])

# --- queue / stack / bag ------------------------------------------------------------------------
QUEUE = ConcurrentQueue([1, 2, 3])
assert_type(QUEUE, ConcurrentQueue[int])
assert_type(QUEUE.try_dequeue(), tuple[Literal[True], int] | tuple[Literal[False], None])
assert_type(QUEUE.to_array(), list[int])

STACK = ConcurrentStack(["x"])
assert_type(STACK.try_pop(), tuple[Literal[True], str] | tuple[Literal[False], None])
assert_type(STACK.try_pop_range(["", ""]), int)

BAG: ConcurrentBag[float] = ConcurrentBag()
BAG.add(1.0)
assert_type(BAG.try_take(), tuple[Literal[True], float] | tuple[Literal[False], None])
assert_type(BAG.count, int)
