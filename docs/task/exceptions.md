---
description: What result(), await, wait() and exception() raise or return for a failed or cancelled task, and where FlpIt differs from .NET.
---
# Exceptions

A task that fails can be observed four ways. They follow .NET, with one deviation:

| | raises or returns | .NET |
|---|---|---|
| `result()` | the **first** failure, as it is | `task.GetAwaiter().GetResult()` |
| `await task` | the **first** failure, as it is | `await task` |
| `task.wait()`, `Task.wait_all(...)` | an `AggregateError` with **every** failure | `task.Wait()`, `Task.WaitAll(...)` |
| `task.exception()` | an `AggregateError` with **every** failure (the same instance each time) | `task.Exception` |

"First" is the first in argument order for `Task.when_all` and for `TaskCompletionSource.set_exception` with
several exceptions, as in .NET. So the exception type does not depend on how many tasks failed: catch the
exception you expect around `result()` or `await`, and use `exception()` or `wait()` to see all of them.

```python
from flpit.task import AggregateError, Task

calls = Task.when_all(Task.run(fetch, a), Task.run(fetch, b))
try:
    results = calls.result()
except httpx.HTTPError as error:        # the first failure, however many failed
    for failure in calls.exception().exceptions:   # all of them, in argument order
        log.warning("call failed: %r", failure)
```

```python
try:
    calls.wait()                         # AggregateError for one failure as for several
except AggregateError as error:
    failures = error.exceptions
```

`Task.when_all` waits for every task before it fails, also when the first one fails early. A failure wins over a
cancellation: if one task fails and another is cancelled, the combined task fails.

## Cancellation

A cancelled task raises its cancellation from `result()`, `await` and `exception()`: the
`OperationCanceledError` the work raised, or a `TaskCanceledError` (a subclass) when the task was cancelled
without one, before it started or through `TaskCompletionSource.set_canceled`. `wait()` raises an
`AggregateError` holding a `TaskCanceledError` for the task. Like .NET's `Task.WhenAll`, a combined task in
which some tasks were cancelled and none failed is cancelled.

## Where FlpIt differs from .NET

- **`result()` is `GetAwaiter().GetResult()`, not `Task.Result`.** .NET has both: `Result` wraps every failure
  in an `AggregateException`, `GetAwaiter().GetResult()` throws the failure itself, as `await` does. A Python
  method can only behave one way, and `result()` follows `await`, so that sync and async code catch the same
  exceptions. `wait()` gives the wrapped form.
- **`exception()` raises for a cancelled task.** .NET's `Task.Exception` is null for a cancelled task; FlpIt
  raises the cancellation, as Python's `asyncio.Future.exception()` does.
- **`KeyboardInterrupt` and `SystemExit` are never put in an `AggregateError`.** They have no .NET counterpart.
  An `AggregateError` is an `Exception`, so `except Exception` would swallow them inside one. `result()`,
  `await`, `wait()`, `Task.wait_all()` and `exception()` give them as they are.
