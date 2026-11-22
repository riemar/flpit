# Changelog

All notable changes to FlpIt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.1] - Unreleased

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
