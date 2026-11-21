---
description: Cooperative cancellation in FlpIt with CancellationToken and CancellationTokenSource. Timeouts, cancellation callbacks and linked tokens, as in .NET.
---
# Cancellation

Cancellation is cooperative, as in .NET. A `CancellationTokenSource` owns the state, its `token` is handed to the
work, and the work checks it or registers a callback. Nothing is interrupted from outside, because Python cannot
stop a running thread.

## Cancel running work

```python
--8<-- "examples/task/cancellation.py:cooperative"
```

`throw_if_cancellation_requested()` raises `OperationCanceledError` when the token has been cancelled. A task
that ends that way has the status `"cancelled"`. Use `cts.cancel_after(seconds)` instead of `cancel()` for a
timeout.

`result()` and `await` on a cancelled task raise `OperationCanceledError`. `task.wait()` and `Task.wait_all()` raise
one `AggregateError` instead, as .NET does.

## Run code on cancellation

```python
--8<-- "examples/task/cancellation.py:callback"
```

`register` returns a registration you can dispose to unsubscribe.

## Combine tokens

A linked source is cancelled as soon as any of its tokens is:

```python
--8<-- "examples/task/cancellation.py:linked"
```

## Where tokens are accepted

Most blocking and awaiting APIs take one: `Task.delay(seconds, token=...)`, `Task.wait_all` and `Task.wait_any`,
`SemaphoreSlim.wait` and `wait_async`, channel reads and writes, and the terminal operators of
[`AsyncFlpIt`](../async/index.md#cancellation).
