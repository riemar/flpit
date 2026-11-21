# Task runtime

FlpIt includes a lightweight, `asyncio`-free task runtime for scheduling and coordinating concurrent work,
modelled on the .NET thread pool: synchronous callables and coroutines both run on pooled worker threads.

- **Scheduling:** `Task.run()` schedules coroutines, awaitables, and synchronous callables.
- **Coordination:** `Task.when_all()`, `Task.when_any()` and `Task.collect()`.
- **Cancellation:** `CancellationToken` and `CancellationTokenSource` support cooperative cancellation,
  callbacks, timeouts, and linked tokens.
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

## More examples

The [`examples/`](https://github.com/riemar/flpit/tree/main/examples) folder has runnable programs for:

- [tasks](https://github.com/riemar/flpit/tree/main/examples/task): awaiting sync functions, async streams with
  `@async_flpit`, cleanup with `@await_using`
- [channels](https://github.com/riemar/flpit/tree/main/examples/channels): producer/consumer queues with
  backpressure
- [concurrent collections](https://github.com/riemar/flpit/tree/main/examples/concurrent): thread-safe queue,
  stack, bag and dictionary
- [threading](https://github.com/riemar/flpit/tree/main/examples/threading): `SemaphoreSlim` for limiting
  parallelism
