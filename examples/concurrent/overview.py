"""Concurrent collections, in short."""
# --8<-- [start:dictionary]
from flpit.concurrent import ConcurrentDictionary
from flpit.task import Task

counts = ConcurrentDictionary[str, int]()
words = ["a", "b", "a"] * 1000


def count(words: list[str]) -> None:
    for word in words:
        counts.add_or_update(word, 1, lambda _, n: n + 1)   # atomic: no lost updates


Task.wait_all([Task.run(count, words) for _ in range(4)])   # four threads, one dictionary
assert counts["a"] == 8000 and counts["b"] == 4000
# --8<-- [end:dictionary]

# --8<-- [start:get_or_add]
cache = ConcurrentDictionary[str, list[int]]()
history = cache.get_or_add("ada", lambda key: [])           # the factory runs only if the key is missing
history.append(1)
assert cache["ada"] == [1]
# --8<-- [end:get_or_add]

# --8<-- [start:queue]
from flpit.concurrent import ConcurrentQueue, ConcurrentStack

queue = ConcurrentQueue([1, 2, 3])
stack = ConcurrentStack([1, 2, 3])

assert queue.try_dequeue() == (True, 1)       # FIFO: the oldest first
assert stack.try_pop() == (True, 3)           # LIFO: the newest first
assert ConcurrentQueue[int]().try_dequeue() == (False, None)   # empty: no exception
# --8<-- [end:queue]
