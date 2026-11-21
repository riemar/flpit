# Task runtime

FlpIt includes a lightweight, `asyncio`-free task runtime for scheduling and coordinating concurrent work,
with synchronous callables executed through a bounded worker pool.

- **Task scheduling:** `Task.run()` schedules coroutines, awaitables, and synchronous callables.
- **Task coordination:** `Task.when_all()` waits for all tasks while preserving input order;
  `Task.when_any()` returns the first completed task; `Task.collect()` yields tasks as they complete.
- **Cancellation:** `CancellationToken` and `CancellationTokenSource` support cooperative cancellation,
  cancellation callbacks, timeouts, and linked tokens.
- **Resource management:** configure worker capacity and pending-work limits, and shut down the process-wide
  runtime with an observable report.
- **Asyncio interoperability:** Tasks can be awaited inside asyncio coroutines when `Task.asyncio_interop`
  is enabled (disabled by default).

The runtime starts lazily and manages its own lifecycle. Cancellation of running synchronous functions is
cooperative.

## Example: running tasks in parallel

```python title="examples/task/when_all.py"
--8<-- "examples/task/when_all.py"
```

More examples are in
[`examples/task/`](https://github.com/riemar/flpit/tree/main/examples/task).
