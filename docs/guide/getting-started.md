---
description: Install FlpIt and write your first lazy LINQ query in Python - where, select, select_many and to_list on any iterable.
---
# Getting started

FlpIt requires Python 3.12 or newer.

```bash
uv add flpit
# or: pip install flpit
```

msgspec is installed automatically on CPython and speeds up [JSON](json.md). On other interpreters (PyPy,
Pyodide) FlpIt installs without it and uses a pure-Python backend. Free-threaded CPython 3.13t is not supported by
msgspec: install there with `--no-deps`, or use 3.14t.

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

## Typing

FlpIt is designed to be inferred precisely by [pyrefly](https://pyrefly.org/) without plugins, so annotations like
`FlpIt[int]` above are optional. mypy and pyright work too, but may infer lambda-heavy pipelines differently.

## LINQ operators and Python built-ins

A query is an ordinary Python iterable. LINQ-style operators carry LINQ's semantics, and built-ins such as `list()`
and `any()` work through the normal iterable protocol:

```python
--8<-- "examples/linq/quickstart.py:builtins"
```

## Querying your own objects

`select_many` flattens one level, here from departments to their employees:

```python
--8<-- "examples/linq/quickstart.py:domain"
```

## Where next

- [Lazy and eager](lazy-vs-eager.md): when does work happen, and what is a `FlpList`?
- [Ordering and grouping](ordering-grouping.md)
- [Joins and lookups](joins.md)
- [JSON](json.md) and [CSV](csv.md)
- [Async queries](../async/index.md): the same operators over `async for`.
- [Concurrency](../task/index.md): tasks, channels and concurrent collections.
- [Semantics](../semantics/index.md): how closely FlpIt follows .NET LINQ, with running proof.
