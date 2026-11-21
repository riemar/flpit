---
description: Where FlpIt deliberately differs from .NET LINQ, and why. FlpList.count(), index() instead of indexed select and where, explicit defaults, and Python's lack of overloads.
---
# Where FlpIt differs from .NET

The goal is to match `System.Linq.Enumerable`. Where Python's language or type system forces a different
contract, the difference is deliberate and listed here. If you find a difference that is not listed, please
[open an issue](https://github.com/riemar/flpit/issues).

## `index()` instead of indexed `select` and `where`

`index()` is the .NET 9 `Index()` operator. It pairs every element with its zero-based position and yields
`IndexTuple(index, item)`, a `NamedTuple` that unpacks and compares like a plain tuple. It is deferred and
streams without buffering. The .NET `OverflowException` after `int.MaxValue` elements does not apply, because
Python integers do not overflow.

```python
--8<-- "examples/linq/differences.py:index"
```

.NET also has `Select((item, index) => ...)` and `Where((item, index) => ...)`. FlpIt does not plan to offer
these. .NET chooses between `x => ...` and `(x, i) => ...` at compile time through overload resolution. Python
has no overloads at runtime: a method receives one callable, and telling the two shapes apart would mean
inspecting its signature on every call. That breaks on builtins, `functools.partial` and `*args`, and would make
behaviour depend on how a function happens to be written. One unambiguous signature per operator, composed
with `index()`, says the same thing explicitly:

```python
--8<-- "examples/linq/differences.py:indexed_select"
```

## Defaults are explicit

Python has no `default(T)`, so the `*_or_default` operators e.g.`first_or_default`, `last_or_default`
take the default value as their first argument. It is required: pass `None` where .NET would give
you `null`. An optional predicate follows it. Unmatched sides of `left_join` and `full_join` arrive as `None` for the
same reason.

```python
--8<-- "examples/linq/differences.py:ends"
```

## Not supported yet

- Custom equality comparers. Keys are compared with `==` and `hash`.
- `FlpIt` operator overloads that rely on .NET's `Range` and `Index` types.

## An addition

`cross_join` has no .NET equivalent. See [Joins and lookups](../guide/joins.md#cross-join).
