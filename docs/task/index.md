---
description: A lightweight, asyncio-free task runtime for Python modelled on the .NET thread pool. Task.run, when_all, when_any, collect, continuations, cancellation and shutdown.
---
# Task runtime

FlpIt includes a lightweight, `asyncio`-free task runtime for scheduling and coordinating concurrent work,
modelled on the .NET thread pool: synchronous callables and coroutines both run on pooled worker threads.

- **Scheduling:** `Task.run()` schedules coroutines, awaitables, and synchronous callables.
- **Coordination:** `Task.when_all()`, `Task.when_any()` and `Task.collect()`.
- **Cancellation:** `CancellationToken` and `CancellationTokenSource` support cooperative cancellation,
  callbacks, timeouts, and linked tokens. See [Cancellation](cancellation.md).
- **Resource management:** configure worker capacity, and shut the runtime down with an observable report.
- **Asyncio interoperability:** Tasks can be awaited inside asyncio coroutines when `Task.asyncio_interop`
  is enabled (disabled by default).

The runtime starts lazily and manages its own lifecycle. Cancellation of running synchronous functions is
cooperative.

## Run work in parallel

Decorate a blocking function with `@task` and every call becomes a `Task` that is already running.
`Task.when_all` waits for all of them and returns their results in input order:

```python
--8<-- "examples/task/overview.py:when_all"
```

## Take the first result

`Task.when_any` returns the first `Task` to complete:

```python
--8<-- "examples/task/overview.py:when_any"
```

## Handle results as they arrive

`Task.collect` is an async stream of tasks in completion order:

```python
--8<-- "examples/task/overview.py:collect"
```

## Cancel

```python
--8<-- "examples/task/overview.py:cancel"
```

## Continue when a task completes

`continue_with` runs a function with the finished task as its argument and returns a new `Task`. Options such as
`TaskContinuationOptions.ONLY_ON_FAULTED` or `NOT_ON_CANCELED` filter when it runs, and `token=` cancels it:

```python
--8<-- "examples/task/overview.py:continue_with"
```

## Block with a timeout

From synchronous code, `task.wait(timeout)`, `Task.wait_all(...)` and `Task.wait_any(...)` block with an optional
timeout and token. They return `False` (`wait_any`: `-1`) on timeout and leave the tasks running:

```python
--8<-- "examples/task/overview.py:wait"
```

## Long-running work

Blocking work that runs for a long time should not occupy a pool worker:

```python
--8<-- "examples/task/overview.py:long_running"
```

## Workers and shutdown

Work beyond the worker limit queues up, and workers are added when the pool is starved or blocked in
`Task.result()`. Calling `result()` inside a task on a task that has not started yet runs it inline, as .NET does.
Set the limits with `Task.configure(min_workers=..., max_workers=...)` before the runtime first starts, and stop
the process-wide runtime with `Task.shutdown(grace_timeout=..., worker_timeout=...)`, which returns a report of
work that could not be stopped.

## Using asyncio libraries

Tasks can be awaited inside asyncio coroutines once `Task.asyncio_interop` is enabled. It is off by default
because it adds a runtime check to every pending await. Code that depends on an asyncio event loop, such as
`httpx.AsyncClient`, can run on the pool through the `@asyncio_task` decorator; see
[`coro.py`](https://github.com/riemar/flpit/tree/main/examples/task/coro.py). That is an escape hatch and not the
recommended default.

## Related

- [Cancellation](cancellation.md)
- [Async queries](../async/index.md)
- [Channels](../concurrency/channels.md), [concurrent collections](../concurrency/collections.md) and
  [threading primitives](../concurrency/threading.md)

## More examples

The [`examples/`](https://github.com/riemar/flpit/tree/main/examples) folder has runnable programs for:

- [tasks](https://github.com/riemar/flpit/tree/main/examples/task): awaiting sync functions, async streams with
  `@async_flpit`, cleanup with `@await_using`
- [channels](https://github.com/riemar/flpit/tree/main/examples/channels),
  [concurrent collections](https://github.com/riemar/flpit/tree/main/examples/concurrent) and
  [threading](https://github.com/riemar/flpit/tree/main/examples/threading)
