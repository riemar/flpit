# Changelog

All notable changes to FlpIt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `Task.from_result()`, `Task.from_exception()` and `Task.from_canceled()`: tasks that are already complete
  (.NET `Task.FromResult` / `FromException` / `FromCanceled`). `from_exception()` fails the task even for an
  `OperationCanceledError`, and `from_canceled()` requires a cancelled token, as in .NET.

### Fixed

- On macOS and Windows, a worker that computes could count as waiting and get a replacement thread after
  about 10 ms. Without per-thread CPU clocks the pool judges from the process's CPU, and it measured that over one
  5 ms tick; Windows' `process_time()` moves in 15.625 ms steps, so the sample read 0 most of the time. It is
  measured over at least 100 ms now. On a machine whose CPU is busy with other processes the guess can still be
  wrong; Linux reads each worker's own CPU clock and is not affected.
- `flpit.json` (msgspec backend) could crash a free-threaded interpreter (a segmentation fault in
  `msgspec._core`) when threads used a dataclass type for the first time at once: msgspec 0.22 builds its
  information for a type lazily and caches it on the type, and a thread could use it while another was still
  building it. The first use of each type now runs once, under a lock; afterwards it is one set lookup. Building
  the wire types also read the dataclass's own `__dict__` while msgspec added its cache to it
  (`RuntimeError: dictionary changed size during iteration`); it reads a snapshot now. Seen in stoop's soak
  test: the server crashed 10 s in, on the first concurrent requests with a JSON body.

- `Task.run()` with an already cancelled token queued the work and cancelled the task only when a worker
  picked it up. The task is cancelled at once and the work is never queued, as in .NET.
- `Task.run(None)` raises `ArgumentNullError` (was `TypeError`), and `TaskCompletionSource.set_exception()` /
  `try_set_exception()` raise `ArgumentNullError` for `None` and `ArgumentError` for an empty collection (was
  `ValueError`) or one with a `None` element, as .NET does. Both are `TypeError` subclasses.
- `Task.when_all()`, `when_any()` and `when_each()` raise `ArgumentNullError` for `None` and `ArgumentError` for a
  `None` task (was a plain `TypeError`), and `when_any()` with no tasks raises `ArgumentError` (was `ValueError`),
  as .NET does. `when_each()` checks its arguments when called, not when the stream is first iterated.
  `AggregateError(None)` raises `ArgumentNullError` and a `None` element `ArgumentError`.
  `TaskCompletionSource.set_from_task()` / `try_set_from_task()` raise `ArgumentNullError` for `None` (was
  `TypeError`) and `ArgumentError` for a task that has not completed (was `ValueError`).
- The ported .NET task tests (`tests/nettests/task`) were re-checked against the originals method by method:
  `WaitAny` waits on a gate instead of delays (it was flaky on macOS), and parts that had been rewritten or
  dropped are back. `MethodCoverage`, `TaskCompletionSource<TResult>`, `AggregateException`,
  `OperationCanceledException` and `TaskCanceledException` tests are ported too. Tests for API FlpIt does not
  have are skips naming the missing API; contracts FlpIt does not follow yet are strict xfails: `Task.Delay`'s
  `TimeSpan` / `-1` / bounds, `WhenEach` enumerable only once, an empty `AggregateException`, and
  `OperationCanceledException(message, innerException, token)`.

- `task.wait()` and `Task.wait_all()` turned a `KeyboardInterrupt` or `SystemExit` from a task into a plain
  `Exception` inside their `AggregateError`, so `except Exception` swallowed a Ctrl-C. They raise it as it is
  now, as `result()` and `await` already did; `Task.when_all` no longer puts it in an `AggregateError` either.

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

- `flpit.asyncio_bridge`: values per loop without `LoopLocal` in user code. `provide(T, factory)` makes
  `Loop[T]` parameters of `@asyncio_task` functions receive the `T` of the loop the call runs on (the caller
  leaves them out; `= injected` tells type checkers so). `PerLoop[T]` is for objects that live longer than a
  call, such as singletons: `.current` is the value of the running loop. `warm=True` creates the values on
  each loop before it takes work; a factory that fails there fails that work with `LoopStartError` and the
  loop is replaced. `PerLoop.close()` closes the values of every loop.
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
- The worker pool replaces workers that wait instead of compute. While work is queued and no worker is free, a
  worker that has sat on one item for a few milliseconds without using CPU (on a socket, a database driver, a
  lock, a file, a sleep) gets a replacement right away, up to `burst_workers` workers (default 256, a new
  `Task.configure` option); before, only the starvation rule added a worker, at most every 0.5 s. 100 work items
  that each wait 50 ms on the default pool take about 55 ms instead of 855 ms; CPU-bound work adds no workers.
  Nothing outside flpit is patched: each worker's own CPU clock tells waiting from computing on Linux and other
  platforms that have per-thread CPU clocks; elsewhere the pool goes by how much CPU the process uses, which can
  add a few workers for CPU work when other processes keep the CPU busy
  (`benchmarks/scripts/worker_replacement_bench.py`).
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

- **Breaking:** what a failed task raises no longer depends on how many tasks failed. It follows .NET, with
  `result()` behaving like `GetAwaiter().GetResult()` (docs/task/exceptions.md):
  - `result()` and `await` on a `Task.when_all` in which several tasks failed raise the first failure in
    argument order instead of an `AggregateError`; so does a `TaskCompletionSource` given several exceptions.
    One failure raised the failure itself before and still does.
  - `exception()` returns an `AggregateError` with every failure, also for a single one (.NET `Task.Exception`),
    the same instance each time; before, it returned the failure itself, or an `AggregateError` for several.
  - `wait()` and `Task.wait_all()` are unchanged: an `AggregateError` with every failure. An `AggregateError`
    that the task's own code raised is now kept in it as one failure, as .NET does, instead of being unpacked.
  - A task cancelled without an exception of its own (before it started, by `TaskCompletionSource.set_canceled`,
    a `Task.when_all` of cancelled tasks, shutdown) records a `TaskCanceledError`, a subclass of
    `OperationCanceledError`, so `except OperationCanceledError` still catches it.

  Code that catches `AggregateError` around `result()` or `await` of a `when_all` should catch the expected
  exception and read `exception().exceptions` for all of them, or call `wait()` first.

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
- Socket waits (`IO.wait_readable`, `IO.wait_writable`) on Linux cost the IO thread about 2–3 µs per wait
  instead of 12–14 µs, and a single core serves about 50% more Redis round trips. The waiting worker arms
  the socket in the IO thread's epoll itself, one-shot, so no command is queued and the IO thread is not
  woken to register it. Other platforms keep the `selectors` reactor, which no longer looks a socket up
  with `selector.get_key` (an exception per first wait) to learn whether it is registered.

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

## [Unreleased]

### Fixed

- `any(None)` and `all(None)` on `FlpIt` and `FlpList`, and `FlpList.exists(None)`, raise
  `PredicateNoneError` (.NET `ArgumentNullException`). Before, they raised a plain `TypeError` once there was an
  element, and returned `False` / `True` for an empty sequence.
- `FlpIt.to_dictionary(key_selector, None)` and `FlpList.to_dictionary(key_selector, None)` raise
  `ElementSelectorNoneError`, like `to_lookup` and `AsyncFlpIt.to_dictionary`. Before, they raised
  `SelectorNoneError`.

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
