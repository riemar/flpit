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

## Typed domain objects

```python
--8<-- "examples/linq/quickstart.py:domain"
```
