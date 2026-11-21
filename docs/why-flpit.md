# Why FlpIt

Method names are the easy part of LINQ. The valuable part is behaviour: when work happens, how much of the
source is read, which exception is raised and when, what order results come out in, and what happens when
operators are chained.

I didn't want a library that only looks like LINQ. I wanted every operator FlpIt implements to behave as
close as possible to its `System.Linq.Enumerable` counterpart, on its own and when composed. That way LINQ
documentation, books and instincts carry over, and chaining holds no surprises.

## What that looks like

A query reads nothing until it is enumerated, and then reads only as much as it needs:

```python
--8<-- "examples/linq/contract.py:deferred"
```

The same holds when you chain several operators:

```python
--8<-- "examples/linq/chaining.py:streaming_chain"
```

Failures are the LINQ ones too, with the same hierarchy as `InvalidOperationException`:

```python
--8<-- "examples/linq/contract.py:exceptions"
```

Every snippet on this page is a real file under [`examples/`](https://github.com/riemar/flpit/tree/main/examples)
that runs in CI, so the examples cannot drift from the library.

## How this is checked

FlpIt is verified against the .NET runtime's own LINQ tests, migrated to Python, and a .NET oracle is in
development to extend that to generated pipelines. See [Verification](semantics/verification.md).

## FAQ

### Isn't there already a LINQ library for Python?

There are several, and they're built around different goals: convenience, brevity, a functional style.
FlpIt's goal is narrower and stricter: to stay as close to .NET LINQ's behaviour as Python allows, operator
by operator and in composition. If that's what you're looking for, FlpIt is built for it. If you want
something else, other libraries may suit you better.
