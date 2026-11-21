# Getting started

FlpIt requires Python 3.12 or newer.

```bash
uv add flpit
# or: pip install flpit
```

## Your first query

```python
--8<-- "examples/linq/quickstart.py:quickstart"
```

`flp.it(...)` wraps any `Iterable[T]` in a lazy `FlpIt[T]`. Nothing runs until you enumerate it or
materialize it with `to_list()`.

## Flipping the pipeline

Native built-ins read inside-out. A FlpIt pipeline reads in the order things happen:

```python
--8<-- "examples/linq/quickstart.py:flip"
```

## Querying your own objects

`select_many` flattens one level, here from departments to their employees:

```python
--8<-- "examples/linq/quickstart.py:domain"
```

## Where next

- [Lazy and eager](lazy-vs-eager.md): when does work happen, and what is a `FlpList`?
- [Ordering and grouping](ordering-grouping.md)
- [JSON](json.md)
- [Semantics](../semantics/index.md): how closely FlpIt follows .NET LINQ, with running proof.
