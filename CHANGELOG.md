# Changelog

All notable changes to FlpIt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [Unreleased]

### Fixed

- A finished Task, its result and the `AsyncLocal` values set inside it were only freed by the cyclic
  garbage collector, because a Task and its context referenced each other. They are now freed as soon
  as the last reference goes.
- A failed or cancelled Task, its exception and the objects in its frames were only freed by the cyclic
  garbage collector, whether the failure was awaited, read with `result()` or never looked at: the
  runtime's frames in the exception's traceback still referenced the task. They are now freed as soon as
  the last reference goes. (A variable of your own that holds the task in a frame of that traceback
  still ties it into a cycle, as with any exception Python code keeps.)
- The timer thread kept the task of its next timer, such as a cancelled `Task.delay`, alive until that
  timer's deadline.
- Free-threaded builds: objects created on an idle pool worker, the timer thread or the IO thread
  and released elsewhere stayed allocated until that thread ran again, up to 20 s. Idle runtime
  threads now wake every 0.5 s, which frees them within that time.
- A failed or cancelled Task awaited from an asyncio coroutine (with `Task.asyncio_interop` enabled), its
  exception and the objects in its frames were only freed by the cyclic garbage collector: the interop
  await kept the task in its frame and its callbacks. They are now freed as soon as the last reference goes.

### Added

- `Task.run_inline` starts work on the calling thread, the way calling an `async` method does in .NET: a
  coroutine runs until its first `await` of something not yet complete, then resumes on the pool. A coroutine
  that never suspends has completed when the call returns, with no queue hop and no wake-up. It takes the same
  arguments as `Task.run`, including a coroutine object. Exceptions are captured in the returned Task, the
  work runs in a copy of the caller's context, an already cancelled token cancels it without running it, and
  deep nesting falls back to queuing. `Task.run` is unchanged.
- `@task(inline=True)` on an `async def` starts every call with `Task.run_inline`, so calling the function behaves
  like calling an `async` method in .NET. Plain `@task` is unchanged and still queues every call; `inline=True` on a
  plain function raises `TypeError`. `@task()` now works as well and means `@task`.
- `flpit.threading.ThreadPool` with `queue` and `queue_user_work_item` (.NET
  `ThreadPool.UnsafeQueueUserWorkItem` / `QueueUserWorkItem`): queue a plain call on the worker pool without
  creating a Task. `queue` runs it in a fresh, empty context, `queue_user_work_item` in a copy of the
  caller's. Exceptions go to the `Task.set_exception_handler` handler, or are logged.
- `benchmarks/scripts/task_start_bench.py` measures what it costs to start, resume and complete tasks.
- `flpit.asyncio_bridge` (provisional: its API may change in 0.5): asyncio libraries on the flpit runtime. A pool of standard asyncio event loops, one
  per CPU by default and created on first use. On Linux each loop is a serialized queue on the flpit pool (one
  reactor thread for all loops' I/O, timers on flpit's timer queue, no thread per loop); elsewhere, or with
  `configure(backend="threads")`, each loop has its own thread. `run_asyncio(awaitable, token=...)` runs asyncio
  code on the calling thread's loop or the least busy pool loop and returns a Task; `LoopLocal` keeps one value
  per loop (an `httpx.AsyncClient`, a connection pool) and closes it with the loop; `shutdown()` is also run by
  `Task.shutdown` and at interpreter exit. `loop.run_in_executor(None, ...)` runs on the flpit pool. asyncio code
  that raises `KeyboardInterrupt`, `SystemExit` or another `BaseException` fails its Task with it, as a flpit
  coroutine does, and the loop goes on serving its other work.

### Changed

- `@asyncio_task` runs calls on the shared loops of `flpit.asyncio_bridge` instead of a new `asyncio.Runner`
  (a new event loop) per call on a blocked pool worker. A call made inside asyncio code runs on that code's loop,
  a `CancellationToken` argument cancels the call, and loop-bound clients can be reused across calls through
  `LoopLocal`.
- `ThreadPool.queue` costs about 40% less on the calling thread: it no longer creates the work item's
  context there and checks the runtime inline.
- Starting and stepping tasks is cheaper: `Task.run` costs about 25–40% less per task. `Task` keeps rarely
  changed fields as class defaults, the start path skips `inspect.isawaitable` for plain functions and plain
  results, and a coroutine step no longer passes through an extra frame when no `AsyncLocal` change handler
  exists.
- Tasks can always be awaited inside asyncio coroutines; this no longer needs `Task.asyncio_interop`.
- Being awaitable from asyncio costs a flpit await 15–60 ns instead of 0.4–0.6 µs. To find out whether an
  asyncio loop runs on the thread, an await of a pending Task now makes one C call (asyncio's
  `_get_running_loop`, which returns None) instead of raising and catching an exception through
  `asyncio.get_running_loop()`, and no longer runs an `import` statement each time
  (`benchmarks/scripts/asyncio_interop_bench.py`).

### Deprecated

- `Task.asyncio_interop`: always `True`, and setting it has no effect; both emit a `DeprecationWarning`. It will
  be removed in 0.5. The switch had nothing left to save: enabled, a flpit await costs within measurement noise
  of disabled, and disabling it only made awaiting a Task inside asyncio code fail.

### Documentation

- New page "Ways to start work": `await`, `Task.run`, `@task`, `Task.run_inline`, `@task(inline=True)` and
  `ThreadPool` work items compared, with their .NET counterparts, costs and when to use which, and why
  `@task(inline=True)` belongs where a Task starts, not on every `async def`
  (`benchmarks/scripts/inline_chain_bench.py`).
- `lab/dotnet/AsyncStartOrder`: a C# program that checks the start order of async methods on .NET 8, 9 and 10, as
  the reference for the inline-start tests, and `lab/task/async_start_order.py`, which runs the same cases with
  flpit.

## [0.4.1] - 2026-11-22

### Added

- `Task.when_each` (.NET `Task.WhenEach`) yields tasks as they complete. `Task.collect` stays as an alias.
- The query operators `when_each()`, `when_all()` and `when_any()` on `FlpIt` and `FlpList`, so a query of
  tasks can end in the wait. `when_any()` is the `first()` of a query of tasks. .NET has these only as static
  `Task` methods, not as extension methods.
- The query operators `select_await()` and `where_await()` on `AsyncFlpIt`, `FlpIt` and `FlpList` (.NET
  `SelectAwait` / `WhereAwait`). The callback may return any awaitable, such as a `Task`, and is awaited one
  element at a time. `select_await()` without an argument awaits the elements themselves, for example after
  `when_each()`.

### Documentation

- New page on mixing sync and async functions: start in an `async def`, put `@task` on a blocking function to
  await it, and call async code from sync code with `twait >>`. It includes a blocking-library example.
- The task overview covers the new query operators.

## [0.4.0] - 2026-11-22

### Added

- **`AsyncFlpIt`**: the `IAsyncEnumerable<T>` counterpart to `FlpIt`, modelled on
  .NET 10 `System.Linq.AsyncEnumerable`. It supports lazy `async for` pipelines,
  most operators that exist on `FlpIt`, terminal operators that return a `Task`,
  sync or async callbacks (`async def f(item, token)`), and cancellation through
  `with_cancellation(token)` or `token=`. Bridges: `flp.ait()`,
  `FlpIt.to_async_enumerable()`, `FlpList.to_async_enumerable()`.
- `@async_flpit` (async generator function to `AsyncFlpIt`, token injection) and
  `@await_using` (close streams a coroutine iterated). Abandoned async
  generators are now closed on the pool, so their `finally` blocks run.
- **Task runtime**: `Task.wait`, `wait_all`, `wait_any` (timeout and token),
  `Task.continue_with` with `TaskContinuationOptions`,
  `TaskCreationOptions.LONG_RUNNING`, `Task.completed_task`, `Task.creation_options`.
  `Task.collect` returns an `AsyncFlpIt`; `when_all`, `when_any` and `collect`
  accept typed collections.
- **`flpit.threading`**: `SemaphoreSlim`, `ManualResetEvent`, `ThreadLocal`,
  `AsyncLocal`, `WaitHandle`.
- **`flpit.channels`**: `Channel[T]`, and **`flpit.concurrent`**: concurrent
  collections, both with migrated .NET tests.
- **JSON**: a type registry (`register_type`, `register_collection`,
  `unregister_type`), a pure-Python backend on the stdlib `json` module, and
  `set_backend()` / `FLPIT_JSON_BACKEND` to choose a backend. `FlpList[T]` and
  `whenever` date/time types are registered by default.
- **Documentation site** with guides, semantics, concurrency and "Explore .NET"
  pages. Its examples run in CI.

### Changed

- **Tasks run on a .NET-style worker pool** instead of a scheduler thread. Task
  start and await are about 10x cheaper, and work runs in parallel on
  free-threaded builds. Workers are daemon threads.
- `Task.result()` inside a task now blocks like .NET (and runs unstarted tasks
  inline) instead of raising.
- **CSV** no longer goes through the JSON machinery. Rows are converted by a
  converter generated per model and header, and results are real dataclass
  instances. Loading 300k rows is about 15% faster. Errors name the line and column.
- `CsvCol` only names CSV columns and no longer renames JSON properties. `JProp`
  still applies to CSV when there is no `CsvCol`.
- `flpit.json` is now a package. Decoding registered collections on the
  `msgspec` backend is up to 3x faster.
- `msgspec` is optional: `import flpit` no longer loads JSON support, and it is
  used automatically when installed (on CPython).
- Timeouts and deadlines use `time.perf_counter()`. On Windows with Python 3.12,
  `time.monotonic()` has about 15.6 ms resolution, so short waits could return early.

### Deprecated

- `max_pending_background` is ignored. The work queue is unbounded.

### Fixed

- `sum()` and `average()` on `Decimal` raised `OverflowError` for ordinary
  rounding. They now round silently, as in .NET, and still raise on real overflow.
- The task runtime kept never-completed tasks and their awaiters alive for the
  life of the process.
- Cancelling `Task.delay` no longer runs continuations inside `cancel()`.
- Unknown `TaskCreationOptions` bits are rejected (`~` on an `IntFlag` ignored them).

## [0.3.4] - 2026-11-17

See the [release on GitHub](https://github.com/riemar/flpit/releases/tag/v0.3.4).
