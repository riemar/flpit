---
description: FlpIt is a deferred, streaming query; FlpList is a materialized list with the full LINQ API. When work happens, and how count() differs from list.count().
---
# Lazy and eager

`FlpIt` is a deferred, streaming query over any iterable. `FlpList` is a materialized list that also has the
whole LINQ API.

## Deferred execution

```python
--8<-- "examples/linq/lazy_vs_eager.py:deferred"
```

## Materialized results

```python
--8<-- "examples/linq/lazy_vs_eager.py:eager"
```

## `count()`

`FlpList.count()` is LINQ's `Count()`. Use the built-in `list.count(value)` on a plain list if you want
Python's meaning.

```python
--8<-- "examples/linq/lazy_vs_eager.py:count"
```
