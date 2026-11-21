---
description: Thread-safe ConcurrentDictionary, ConcurrentQueue, ConcurrentStack and ConcurrentBag for Python, modelled on .NET System.Collections.Concurrent. Atomic updates, no lost writes.
---
# Concurrent collections

`flpit.concurrent` has thread-safe collections modelled on .NET's `System.Collections.Concurrent`. They work on
regular and free-threaded CPython.

## ConcurrentDictionary

`counts[word] = counts.get(word, 0) + 1` loses updates when two threads read the same old value.
`add_or_update` does the read-modify-write atomically:

```python
--8<-- "examples/concurrent/overview.py:dictionary"
```

It is also a regular Python mapping: `in`, `[key]`, `len()` and iteration work as for `dict`. Iterating works on a
snapshot, so it never breaks while other threads modify the dictionary.

`get_or_add(key, factory)` creates a value only for a missing key. The factory is a callable that receives the key,
because the dictionary knows its own value type, so even `list` values need one:

```python
--8<-- "examples/concurrent/overview.py:get_or_add"
```

The other atomic operations are `try_update` and `try_remove`. `CDict[str, int]()` is a short alias.

## Queue, stack and bag

```python
--8<-- "examples/concurrent/overview.py:queue"
```

- **`ConcurrentQueue`** (`CQueue`): first in, first out. `try_dequeue` returns the oldest item.
- **`ConcurrentStack`**: last in, first out. `push_range` and `try_pop_range` move several items at once, kept
  together.
- **`ConcurrentBag`**: unordered. A thread gets its own items back first, which makes it cheap for workers that
  consume what they produce, and otherwise takes another thread's oldest.

Instead of raising when empty, `try_dequeue`, `try_pop` and `try_take` return `(True, item)` or `(False, None)`.

More programs:
[`examples/concurrent/`](https://github.com/riemar/flpit/tree/main/examples/concurrent).
