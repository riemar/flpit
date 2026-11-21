---
description: Inner, left, full, group and cross joins in FlpIt, plus to_lookup. Modelled on .NET LINQ Join, LeftJoin, FullJoin and GroupJoin.
---
# Joins and lookups

The examples join people to their orders. Each item is a plain tuple:

```python
--8<-- "examples/linq/joins.py:data"
```

## Join

`join` keeps only the pairs that match (.NET `Join`). The arguments are the inner sequence, a key selector for
each side, and a result selector:

```python
--8<-- "examples/linq/joins.py:join"
```

## Left join and full join

`left_join` keeps every outer element (.NET 10 `LeftJoin`). `full_join` also keeps the inner elements nobody
matched (.NET 11 `FullJoin`). An unmatched side reaches the result selector as `None`:

```python
--8<-- "examples/linq/joins.py:left_join"
```

```python
--8<-- "examples/linq/joins.py:full_join"
```

## Group join

`group_join` yields one result per outer element, however many inner elements match (.NET `GroupJoin`). The
result selector receives the matches as a query:

```python
--8<-- "examples/linq/joins.py:group_join"
```

## Cross join

`cross_join` has no .NET equivalent. It yields every combination, with no keys involved:

```python
--8<-- "examples/linq/joins.py:cross_join"
```

Without a result selector, `join`, `left_join`, `full_join` and `cross_join` yield `JoinTuple(outer, inner)`.

## Lookups

`to_lookup` groups a sequence by key once and lets you query the groups by key afterwards (.NET `ToLookup`):

```python
--8<-- "examples/linq/joins.py:lookup"
```

## Rules worth knowing

- Elements whose key is `None` never match. `left_join` and `full_join` still emit them as unmatched, and
  `group_join` emits them with an empty group.
- `full_join` returns the `left_join` rows in outer order, followed by the unmatched inner elements in inner
  order.
- Argument errors are raised immediately; everything else is deferred.
- Keys are compared with `==` and `hash`, like `group_by`. Custom comparers are not supported yet.

How much each join buffers is listed in [Execution characteristics](../semantics/execution.md).
