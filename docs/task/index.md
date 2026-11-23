---
description: A lightweight, asyncio-free task runtime for Python modelled on the .NET thread pool. Task.run, when_all, when_any, when_each, continuations, cancellation and shutdown.
---
# Task runtime

FlpIt includes a lightweight, `asyncio`-free task runtime for scheduling and coordinating concurrent work,
modelled on the .NET thread pool: synchronous callables and coroutines both run on pooled worker threads.

- **Scheduling:** `Task.run()` schedules coroutines, awaitables, and synchronous callables. `Task.run_inline()`
  starts them on the calling thread instead, as calling an `async` method does in .NET.
- **Coordination:** `Task.when_all()`, `Task.when_any()` and `Task.when_each()`, also as query operators.
- **Cancellation:** `CancellationToken` and `CancellationTokenSource` support cooperative cancellation,
  callbacks, timeouts, and linked tokens. See [Cancellation](cancellation.md).
- **Resource management:** configure worker capacity, and shut the runtime down with an observable report.
- **Asyncio interoperability:** Tasks can be awaited inside asyncio coroutines when `Task.asyncio_interop`
  is enabled (disabled by default).

The runtime starts lazily and manages its own lifecycle. Cancellation of running synchronous functions is
cooperative.

## Run work in parallel

Decorate a blocking function with `@task` and every call becomes a `Task` that is already running
(see also [mixing sync and async functions](sync-and-async.md)).
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

`Task.when_each` (.NET `Task.WhenEach`) is an async stream of tasks in completion order:

```python
--8<-- "examples/task/overview.py:when_each"
```

`Task.collect` is the former name and still works.

## End a query in the wait

`when_all()`, `when_any()` and `when_each()` are also query operators. A query that produces tasks can end in
any of them, so there is no need to wrap it in a `Task.when_*` call:

```python
--8<-- "examples/task/overview.py:operators"
```

`when_any()` is the `first()` of a query of tasks, and `when_each()` streams them in completion order. .NET has
these only as static `Task` methods, so the operators are FlpIt's own.

Enumerating the query starts every task before the wait begins. `when_any()` on an empty query raises
`ValueError`, and `when_all()` on an empty query gives an empty list.

## Await each result in a query

`select_await()` and `where_await()` (.NET `SelectAwait` and `WhereAwait`) take a callback that returns something
awaitable, usually a `Task`, and await it for you. They are the ones to use when the callback is a `@task`
function or a lambda: `select()` only awaits an `async def` callback, and a plain callable that returns a `Task`
would hand you the `Task` itself.

```python
--8<-- "examples/task/overview.py:select_await"
```

As in .NET, the calls run one at a time. The callback is not called for the next element until the previous result
has arrived, so `select_await(nap)` on its own is sequential. To run the calls side by side, start the tasks first
with `select()`, put `when_each()` in front to take them as they finish, and let `select_await()` await each one
(the second query above), or end the query in `when_all()` to get the results in input order.

Without an argument, `select_await()` awaits the elements themselves, which is what you want after `when_each()`
or any other query of tasks. It is the same as passing `lambda t: t`.

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

## Start on the calling thread

`Task.run` always queues the work: even a coroutine that would finish at once waits for a worker to pick it up.
`Task.run_inline` takes the same arguments and starts the work right here, the way calling an `async` method does
in .NET. The coroutine runs on the calling thread until its first `await` of something that has not completed.
Only then does the caller get control back, holding a pending `Task`, and the rest resumes on the pool. A coroutine
that never suspends has completed when `run_inline` returns:

```python
--8<-- "examples/task/overview.py:run_inline"
```

`@task(inline=True)` on an `async def` does the same for every call. This suits code that is already running on a
worker and starts mostly-synchronous async work, such as a web framework calling an `async def` endpoint.
[Ways to start work](starting-work.md) compares this with `Task.run`, `@task` and plain `await`. The rules:

- **Exceptions** raised before the first suspension complete the returned `Task` as faulted (or canceled, for
  `OperationCanceledError`). They are not raised into the caller.
- **Awaiting a completed task** continues on the same thread. `await Task.yield_now()` is a real suspension.
- **Context:** the work runs in a copy of the caller's context, so `AsyncLocal` changes inside never reach the
  caller.
- **Cancellation:** an already cancelled `token` gives a canceled `Task` without running anything, as with
  `Task.run`.
- **Nesting:** nested inline starts grow the calling thread's stack. Past a fixed depth the work is queued instead.
- `creation_options` behave as with `Task.run`; `LONG_RUNNING` is rejected.

Started from a thread outside the pool, the coroutine also runs there until it suspends, and then resumes on the
pool. That is what .NET does on a thread without a `SynchronizationContext`; flpit has no synchronization contexts.

## Workers and shutdown

Work beyond the worker limit queues up, and workers are added when the pool is starved or blocked in
`Task.result()`. Calling `result()` inside a task on a task that has not started yet runs it inline, as .NET does.
To put a plain call on the pool without creating a `Task`, use
[`ThreadPool.queue`](../concurrency/threading.md#threadpool).
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
