# The contract

Each snippet below is part of a file under `examples/linq/` that runs in CI. Several of them use a small
helper that counts how many elements a source has handed out:

```python
--8<-- "examples/linq/_support.py:tracked"
```

## Building a query reads nothing

```python
--8<-- "examples/linq/contract.py:deferred"
```

## Callbacks run during enumeration

```python
--8<-- "examples/linq/contract.py:callbacks"
```

## Short-circuiting

```python
--8<-- "examples/linq/contract.py:short_circuit"
```

## Exceptions

```python
--8<-- "examples/linq/contract.py:exceptions"
```

## Sources keep their enumeration characteristics

As in .NET, a re-enumerable source can be enumerated again, and a one-shot source stays one-shot. The .NET
LINQ tests exercise this with `RunOnce()`; the migrated tests do the same with one-shot generators.

```python
--8<-- "examples/linq/contract.py:sources"
```

## Ordering of results

```python
--8<-- "examples/linq/contract.py:set_ops"
```

See also [ordering and grouping](../guide/ordering-grouping.md).
