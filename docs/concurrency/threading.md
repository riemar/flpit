---
description: SemaphoreSlim, ThreadLocal, AsyncLocal, ManualResetEvent and ThreadPool work items for Python, modelled on .NET System.Threading. Limit parallelism from threads and from tasks.
---
# Threading primitives

`flpit.threading` adds the .NET threading primitives that go with the [task runtime](../task/index.md).

## SemaphoreSlim

A semaphore limits how many callers are inside a section at once. The same instance works from plain threads
(`wait()`) and from tasks (`await wait_async()`), and asynchronous waiters are served in first-in, first-out
order.

```python
--8<-- "examples/threading/overview.py:semaphore"
```

```python
--8<-- "examples/threading/overview.py:async_semaphore"
```

Always release in a `finally` block, so a failure gives the slot back.

!!! warning
    `with throttle:` does **not** acquire the semaphore. As C#'s `using`, it *disposes* it when the block ends.
    Use `wait()` or `wait_async()` with `release()`.

`wait` and `wait_async` take a timeout in seconds (or a `timedelta`) and a `CancellationToken`. They return `False`
on timeout, and raise `OperationCanceledError` when the token is cancelled.
`current_count` reports the free slots.

## ThreadLocal

`ThreadLocal[T]` keeps one value per OS thread, created lazily by a factory:

```python
--8<-- "examples/threading/overview.py:thread_local"
```

A coroutine that resumes on another pool worker after an `await` sees that worker's value. For values that follow
the task instead, use [`AsyncLocal`](#asynclocal). `ThreadLocal(factory, track_all_values=True)` makes `values` list
every thread's value.

## AsyncLocal

`AsyncLocal[T]` keeps a value with the logical flow of a task, however many pool workers it hops between. Typical
uses are a request ID or user context that is set once and read further down the call chain:

```python
--8<-- "examples/threading/overview.py:async_local"
```

A task inherits the value of the flow that started it. Changes made inside the task do not reach its parent.
`AsyncLocal` is built on `contextvars.ContextVar`, and an optional `value_changed_handler` is called when the value
changes.

## ManualResetEvent

`ManualResetEvent` is a signal that stays set until it is reset. Threads wait on it with `wait_one()`, and one
`set()` releases all of them until `reset()` is called:

```python
--8<-- "examples/threading/overview.py:event"
```

`wait_one(timeout)` returns `False` when the timeout elapses first. It blocks the calling thread, so inside a task it
occupies a pool worker while it waits.

## ThreadPool

`ThreadPool.queue(callback, state)` queues a plain call on the
[task runtime's](../task/index.md) worker pool. It creates no `Task`: there is no result to wait for, nothing
to cancel and nothing to await, which makes it the cheapest way onto a worker. It can be called from any thread,
for example a server's IO thread that has to hand a request off at once:

```python
--8<-- "examples/threading/overview.py:thread_pool"
```

The callback is called as `callback(state)`, or as `callback()` when `state` is left out. It runs in a fresh, empty
`contextvars.Context`, as .NET runs a work item with the default execution context: it sees none of the caller's
`AsyncLocal` values, and what it sets ends with the work item. `ThreadPool.queue_user_work_item` runs it
in a copy of the caller's context instead, at the cost of copying it.

An exception that escapes the callback goes to the handler installed with `Task.set_exception_handler`, or is
logged. .NET terminates the process instead. Queuing while the runtime shuts down raises `RuntimeShutdownError`.
`prefer_local` is accepted for porting and has no effect, because the pool has one shared queue.

More programs:
[`examples/threading/`](https://github.com/riemar/flpit/tree/main/examples/threading).
