---
description: FlpIt keeps LINQ behaviour when operators are chained - streaming through a chain, take, buffering operators and independent derived queries.
---
# Chaining

Individual operators are only half of the story. These examples check that the behaviour holds when
operators are composed. They use the `Tracked` helper from [the contract](contract.md).

## Streaming through a chain

`where`, `select` and `first` stay streaming end to end, so only as many elements are read as needed:

```python
--8<-- "examples/linq/chaining.py:streaming_chain"
```

## `take` stops reading

```python
--8<-- "examples/linq/chaining.py:take"
```

## Operators that must see everything

`order_by` has to read the whole source before it can yield its first element. It does so when the query is
enumerated, not when it is built:

```python
--8<-- "examples/linq/chaining.py:buffering"
```

## Derived queries are independent

Queries built from the same source do not affect each other or the source:

```python
--8<-- "examples/linq/chaining.py:independent"
```

```text
original
   │
   ├── order_by ──→ ordered
   │
   └── concat ────→ extended
```

`ordered` and `extended` are separate queries over `original`. This matches the independent-query behaviour of
.NET LINQ.
