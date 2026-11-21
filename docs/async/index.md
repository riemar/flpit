---
description: AsyncFlpIt is LINQ for async streams in Python, modelled on .NET IAsyncEnumerable and System.Linq.AsyncEnumerable. Lazy pipelines, async callbacks, cancellation and cleanup.
---
# Async queries

`AsyncFlpIt` is to `async for` what `FlpIt` is to `for`: a lazy query over an async stream. It is the
counterpart of .NET's `IAsyncEnumerable<T>` and .NET 10's `System.Linq.AsyncEnumerable`. It wraps any async
iterable (such as an async generator or another `AsyncFlpIt`) or sync iterable, runs on the
[task runtime](../task/index.md), and is consumed with `async for`.

## A first pipeline

`@async_flpit` turns an async generator function into one that returns an `AsyncFlpIt` (C#'s
`async IAsyncEnumerable<T>` method). Callbacks can be plain functions or `async def` functions that take the
`CancellationToken` as their last argument:

```python
--8<-- "examples/linq/async_queries.py:pipeline"
```

- Intermediate operators (`where`, `select`, ...) never touch the source. Each enumeration enumerates it again,
  and one-shot sources stay one-shot.
- Terminal operators (`to_list`, `first`, `single`, `count`, `any`, `sum`, `min_by`, `to_dictionary`,
  `to_lookup`, `aggregate`, ...) return a `Task`. `await` it inside the runtime, or call `.result()` from
  synchronous code. Argument errors are raised immediately, before the `Task` exists.
- `flp.ait(source)` wraps any async or sync iterable, and `FlpIt.to_async_enumerable()` converts a sync query.
  `AsyncFlpIt.empty()`, `range()` and `repeat()` are available too.

## From synchronous code

```python
--8<-- "examples/linq/async_queries.py:sync_bridge"
```

## Cancellation

`with_cancellation(token)` binds a token to an `async for` loop, and terminal operators accept `token=`. The
token reaches the producer through the `token` parameter of an `@async_flpit` function, like C#'s
`[EnumeratorCancellation]`. As in .NET, operators pass the token on and do not poll it themselves:

```python
--8<-- "examples/linq/async_queries.py:cancel"
```

## Cleanup

C#'s `await foreach` always disposes the stream it iterates. FlpIt gives `async for` the same cleanup:

- Every enumerator an operator opens is closed when it completes, fails or short-circuits.
- A stream left early (`break`, `return`, an exception) is closed by the runtime right after the loop, so its
  `finally` blocks run even when they await. Nothing waits for that to finish.
- When the cleanup must be finished at a known point, use `async with query.get_async_enumerator()` (C#'s
  `await using (...) { }`), or put `@await_using` on the consuming function (C#'s `await using var`).

```python
--8<-- "examples/linq/async_queries.py:cleanup"
```

Use one of the last two when you need a connection, lock or semaphore slot released before you go on.

## What is not there yet

`AsyncFlpIt` implements the operators `FlpIt` has. Overloads that `FlpIt` lacks (index-based selectors, comparers,
`Range` and `Index` arguments) are not provided yet.

More runnable programs are in
[`examples/task/`](https://github.com/riemar/flpit/tree/main/examples/task):
`async_enumerable.py`, `await_using.py` and `streaming.py`.
