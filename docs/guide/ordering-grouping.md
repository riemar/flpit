---
description: Stable sorting with order_by and then_by, and grouping with group_by, in FlpIt. Same behaviour as .NET LINQ.
---
# Ordering and grouping

## Ordering

`order_by` is stable, and `then_by` adds a tie-breaker:

```python
--8<-- "examples/linq/ordering_grouping.py:order"
```

## Grouping

`group_by` yields groups with a `key`. Each group is itself a query over its elements:

```python
--8<-- "examples/linq/ordering_grouping.py:group"
```
