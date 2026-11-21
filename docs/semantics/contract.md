# The contract

Each snippet below is part of a file under `examples/linq/` that runs in CI. Two small helpers keep them
short. `Tracked` counts how many elements a source has handed out:

```python
--8<-- "examples/linq/_support.py:tracked"
```

and `raises(SomeError)` is a `with` block that asserts the error is raised.

## Building a query reads nothing

```python
--8<-- "examples/linq/contract.py:deferred"
```

## Callbacks run during enumeration

```python
--8<-- "examples/linq/contract.py:callbacks"
```

## Short-circuiting

`any` stops at the first match, `single` as soon as it sees a second one:

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

## Results and their order

```python
--8<-- "examples/linq/contract.py:results"
```

See also [ordering and grouping](../guide/ordering-grouping.md).
