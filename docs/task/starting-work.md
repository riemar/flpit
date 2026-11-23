---
title: Ways to start work
description: "await, Task.run, @task, Task.run_inline, @task(inline=True) and ThreadPool work items in FlpIt: where each one runs your code, what it costs, and when to use which."
---
# Ways to start work

FlpIt has several ways to get a function running. They differ in one thing above all: **where the code runs
before the first `await` of something that has not completed yet.** That part either runs on the calling thread,
right away, or is queued to the worker pool. Everything after that first real suspension always resumes on the
pool.

| You write | Before the first `await` | You get | .NET counterpart |
|---|---|---|---|
| `await load()` | on the caller, now | the result | `await LoadAsync()` |
| `load()` | nothing runs | a cold coroutine | *(none: C# methods start when called)* |
| `Task.run(fn, ...)` | queued to the pool | a `Task` | `Task.Run(...)` |
| `@task def` / `@task async def` | queued to the pool | a `Task` per call | `Task.Run` on every call |
| `Task.run_inline(fn, ...)` | on the caller, now | a `Task` | `var t = LoadAsync();` |
| `@task(inline=True) async def` | on the caller, now | a `Task` per call | calling an `async` method |
| `Task.when_all(load(), ...)` with coroutines | queued to the pool | a `Task` | `Task.WhenAll(Task.Run(...), ...)` |
| `ThreadPool.queue(fn)` | queued to the pool | nothing | `ThreadPool.UnsafeQueueUserWorkItem` |
| `Task.run(fn, creation_options=LONG_RUNNING)` | a thread of its own | a `Task` | `TaskCreationOptions.LongRunning` |

A plain `def` has no `await`, so "before the first `await`" is all of it: `Task.run` and `@task` run it on the
pool, and the inline forms do not take it (it would simply be a call).

## Await it

Inside an `async def`, awaiting a coroutine runs it right here, without creating a `Task`. This is the cheapest way
and the same as `await` in C#:

```python
--8<-- "examples/task/starting.py:await"
```

Calling an `async def` without awaiting it runs nothing. This is the one place where Python differs from C#,
whose async methods start as soon as they are called:

```python
--8<-- "examples/task/starting.py:cold"
```

## Queue it: `Task.run` and `@task`

`Task.run` queues the work to the pool and returns a `Task` at once. The caller never runs any of it, whether the
function is a plain `def` or an `async def`. `@task` does the same for every call of a function:

```python
--8<-- "examples/task/starting.py:run"
```

```python
--8<-- "examples/task/starting.py:task"
```

On free-threaded Python the queued calls run in parallel from their first line, including CPU work before their
first `await`. A blocking call inside an `async def` holds up only the worker it runs on.

## Start it inline: `Task.run_inline` and `@task(inline=True)`

The inline forms start an `async def` the way calling an `async` method does in .NET. The coroutine runs on the
calling thread until its first `await` of something not yet complete. Then the caller gets a pending `Task` back,
and the rest resumes on the pool. A coroutine that never suspends has already completed when the call returns, with
no queue hop and no wake-up:

```python
--8<-- "examples/task/starting.py:inline"
```

Several inline calls start one after another. Each one runs up to its first `await` before the next one begins,
and only after that do they overlap, exactly as in C#:

```python
--8<-- "examples/task/starting.py:order"
```

Exceptions before the first suspension end up in the returned `Task`, the coroutine runs in a copy of the caller's
context, and deep nesting falls back to queuing. [Start on the calling thread](index.md#start-on-the-calling-thread)
has the details.

## Hand off a call: `ThreadPool` work items

When you only need a call to happen on a worker, with no result and nothing to await, a work item is cheaper than a
`Task`. It is meant for code such as a server's IO thread that must hand a request off at once:

```python
--8<-- "examples/task/starting.py:work_item"
```

See [ThreadPool](../concurrency/threading.md#threadpool) for its context and exception rules.

## Which one to use

- **Inside async code, when you want the result now:** `await` it. No `Task`, no thread switch.
- **To get blocking or CPU-heavy work off the current thread, or to run calls in parallel:** `Task.run`, or `@task`
  on the function. This is the default for starting work, and the safe choice when you are not sure what the
  function does before its first `await`.
- **To start coroutines that usually finish quickly or suspend early** (cache hits, a framework calling a request
  handler, many small coroutines started from a worker): `Task.run_inline`, or `@task(inline=True)`. It saves the
  queue hop and the wake-up, which cost far more than a short coroutine itself. Only where you start them without
  awaiting at once; see [below](#dont-put-taskinlinetrue-on-every-async-def).
- **Not inline** when the coroutine does blocking or heavy work before its first `await` (each call would then hold
  up the caller, and several calls would run one after another), when the caller holds a lock the coroutine might
  need, or when the calling thread must not run your code at all, such as a server's IO thread.
- **To hand a call to a worker and forget it:** `ThreadPool.queue`.
- **For work that blocks for a long time:** `Task.run(..., creation_options=TaskCreationOptions.LONG_RUNNING)`, so
  it does not occupy a pool worker.

## Don't put `@task(inline=True)` on every `async def`

In C# every async method returns a `Task`, so it is tempting to decorate every `async def` the same way. In Python
that makes code slower that simply awaits its calls:

- **`await foo()` on a plain `async def` costs almost nothing.** The coroutine runs inside the caller's own task,
  without a `Task` of its own. A decorated function creates a full `Task` on every call, a few microseconds each.
- **Suspended chains pay once per level.** When a chain of plain coroutines resumes, it resumes as one unit. When
  every level is its own `Task`, each finished level hands control to the one above as a separate work item on the
  pool.
- **Deep chains stop being inline.** Nested inline starts count toward a depth limit (32). Past it, the call is
  queued like `Task.run`.

Measured with `benchmarks/scripts/inline_chain_bench.py` (each figure includes about 3.5 µs for starting and
waiting for the outer task):

| | 3.13 | 3.14t |
|---|---:|---:|
| `await` chain, 10 levels, one real suspension at the bottom, plain `async def` | 50 µs | 46 µs |
| the same chain with every level `@task(inline=True)` | 204 µs | 181 µs |
| `await` of one call that never suspends, plain `async def` | 3.3 µs | 3.5 µs |
| the same call with `@task(inline=True)` | 7.2 µs | 6.0 µs |

The rule: **inline where a `Task` starts, plain `await` everywhere else.** If every caller writes `await foo()`
right away, leave `foo` a plain `async def`; it already behaves like C#'s `await FooAsync()`. Decorate a function
with `@task(inline=True)`, or call it with `Task.run_inline`, where it is started *without* being awaited at once:
fan-out, fire-and-forget, a framework starting a handler.

What it costs, as a rough guide: CPU time per call measured with `benchmarks/scripts/task_start_bench.py` on
a small 2-core machine, Python 3.13 and free-threaded 3.14. Your numbers will differ, the proportions less so.

| Start | Per call |
|---|---:|
| `Task.run` of a function, until its result is there | 5–6 µs |
| `Task.run_inline` of a coroutine that does not suspend | 3.5–4 µs |
| `ThreadPool.queue`, until the call has run | 1.5–3 µs |

On top of that, a caller that starts *one* queued task and waits for it also waits for a worker to wake up: 25–65 µs
in the same measurements. An inline start that does not suspend never pays that.
