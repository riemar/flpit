---
title: Mixing sync and async functions in Python
description: "Call blocking functions from async code and async functions from sync code in Python with one Task type. No wrappers, no asyncio event loop to manage."
---
# Mixing sync and async functions in Python

Python splits functions into two kinds. A coroutine (`async def`) can only be awaited from another coroutine,
and a plain function can't await anything. This is often called the function color problem, after Bob Nystrom's
essay [What Color Is Your Function?](https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/).

FlpIt's [task runtime](index.md) puts both kinds behind one type, `Task`. The practical rule is short: **start in
`async def` and `await` whatever you need.** If something is a plain blocking function, put `@task` on it.

## Await a blocking function

`@task` makes every call start immediately on a pooled worker thread and return a `Task`. A `Task` can be
awaited, or run side by side with others in `Task.when_all`:

```python
--8<-- "examples/interop/sync_and_async.py:await_sync"
```

## Start many calls at once

Put `@task` on a function, sync or `async def`, and every call starts immediately and returns a `Task`. A query
that selects such a function therefore has all its calls running before you wait for any of them. End the query in
`when_all()` to get the results in input order:

```python
--8<-- "examples/interop/sync_and_async.py:blocking_library"
```

To handle each result as soon as it is ready, end the query in `when_each()` instead. It is an async stream of the
tasks in the order they finish, and each task is already done when you receive it.

```python
--8<-- "examples/interop/sync_and_async.py:blocking_stream"
```

To work with the values and not the tasks, add `select_await()`, which awaits each finished task, and then
post-process with an ordinary `select`. The callback can be a plain function or an `async def`:

```python
--8<-- "examples/interop/sync_and_async.py:blocking_processed"
```

## Call an async function from sync code

`Task.run` starts a coroutine function (or a plain one) and returns the same `Task`. From synchronous code,
wait for it with `twait >>`, the sync counterpart of `await`, or with `.result()`:

```python
--8<-- "examples/interop/sync_and_async.py:call_async"
```

Both block the calling thread until the task is done. The difference is a safety check: `twait >>` raises
`RuntimeError` when it is written directly inside an `async def`, where blocking would tie up a pool worker.
Use `await` there. The check looks only at the function that contains the expression, so it can't
catch a plain helper that is called from async code.

## Mix both in one query

[`AsyncFlpIt`](../async/index.md) callbacks may be plain functions or `async def` functions. You don't have to
pick one for the whole pipeline:

```python
--8<-- "examples/interop/sync_and_async.py:query"
```

## What still applies

- **`await` still needs `async def`.** FlpIt removes the wrappers, not the keyword. A plain function either
  gets `@task` and is awaited, or is called through `Task.run(...).result()`.
- **`twait >>` and `.result()` block the calling thread.** Use them at the edge of your program or in plain
  threads, and prefer `await` inside a task.
- **Blocking work occupies a worker.** `@task` functions run on the pool's threads. Data they share needs the
  usual care; see [threading primitives](../concurrency/threading.md).
- **Code that needs an asyncio event loop** (such as `httpx.AsyncClient`) is a different case. See
  [Using asyncio libraries](index.md#using-asyncio-libraries).
