# asyncio libraries

!!! note "Provisional"
    `flpit.asyncio_bridge` (`LoopLocal`, `run_asyncio`, `configure`, `shutdown`) is provisional: its API may
    still change in 0.5. The default backend on Linux drives CPython's asyncio internals; the `"threads"`
    backend uses public asyncio API only and is the fallback should a Python release change them.
    `@asyncio_task` keeps its signature.

## Prefer the sync client

flpit runs your code on threads, so the first choice for I/O is a library's **sync** client, written for threads
and meant to be shared: one `httpx.Client` for the whole process, one psycopg `ConnectionPool`. They need no event
loop, no bridge and no per-loop copies.

A sync call holds its worker while it waits. Give the pool as many workers as you expect calls in flight, and
the client as many connections:

```python
import httpx
from flpit.task import Task, task

Task.configure(min_workers=64)  # before the runtime starts
client = httpx.Client(limits=httpx.Limits(max_connections=64, max_keepalive_connections=64))


@task
def fetch(url: str) -> dict:
    return client.get(url).json()
```

With the default pool (CPU count + 4 workers), 100 parallel calls that each wait 50 ms ran in about 1.6 s on a
2-core machine, because only that many ran at once; with 32 workers, in about 0.24 s, on par with one asyncio
loop and one `httpx.AsyncClient`.

## When a library only exists for asyncio

Libraries built only on asyncio, such as asyncpg, need an event loop: their code calls
`asyncio.get_running_loop()`, and their connections, locks and futures belong to the loop that created them.
asyncio code is not thread-safe: one client cannot be shared between loops. `flpit.asyncio_bridge` provides
those loops on the flpit runtime, and `@asyncio_task` runs a function on them. The example uses
`httpx.AsyncClient` because it is easy to try; for HTTP itself, the sync client above is the better fit.

```python
import httpx
from flpit.asyncio_bridge import LoopLocal
from flpit.task import CancellationToken, asyncio_task

clients = LoopLocal(httpx.AsyncClient)  # one client per loop, closed with the loop


@asyncio_task
async def fetch(url: str, token: CancellationToken) -> dict:
    client = await clients.get()
    return (await client.get(url)).json()


task = fetch("https://example.org/data.json", token)  # a flpit Task; await it, or .result()
```

## How it runs

- **Shared loops.** Calls run on a small pool of standard asyncio event loops, by default one per CPU, created
  the first time they are needed. No loop is created per call, and nothing is created before the first call.
- **The caller's loop first.** Called from code already running on an asyncio loop (asyncio code calling more
  asyncio code, or an application that runs its own loop), the call runs on that loop.
- **Least busy loop otherwise.** Of two loops picked at random, the call goes to the one with fewer running
  calls; a new loop is created while all picked loops are busy and the pool is below its size.
- **No blocked workers.** While a call waits for I/O, no pool worker waits with it.
- **Context.** The call starts in a copy of the caller's context, so `AsyncLocal` and `ContextVar` values flow in.
- **Executor.** `loop.run_in_executor(None, ...)` and `getaddrinfo` run on the flpit pool.

## Backends

| Backend | Where | How a loop runs |
|---|---|---|
| `"strands"` (default on Linux) | needs epoll | Each loop is a serialized queue on the flpit pool: when it has work, one work item runs its iterations, never two at once. One reactor thread waits for I/O on all loops; timers use flpit's timer queue. A loop costs no thread. |
| `"threads"` (default elsewhere) | any platform | One dedicated thread per loop running `run_forever()`. Public asyncio API only. |

Both run asyncio's own `SelectorEventLoop`, transports and sockets, so libraries see a normal loop. The strands
backend drives asyncio's internal `_run_once` and replaces two private hooks; the threads backend is the
fallback should a Python release change them.

```python
from flpit import asyncio_bridge

asyncio_bridge.configure(loops=4, backend="threads")  # before first use
```

## Cancellation

A `CancellationToken` among the arguments of an `@asyncio_task` function cancels the call, as in .NET: the
asyncio task is cancelled, its `finally` blocks run, and the returned Task ends cancelled. An already cancelled
token starts nothing. Code that catches `asyncio.CancelledError` and returns normally completes normally.
`run_asyncio(awaitable, token=...)` does the same for an awaitable you already have.

## Objects that outlive one call

Clients and connection pools are bound to the loop that created them. Keep them in a `LoopLocal`: one value per
loop, created on first use on that loop. `await local.get()` works with plain and `async def` factories;
`local.value` works with plain factories. When a loop is closed, its values are closed with it
(`await value.aclose()` if the value has one, otherwise `value.close()`).

## Shutdown

`asyncio_bridge.shutdown(timeout)` cancels the calls still running, closes the `LoopLocal` values and async
generators of each loop, and closes the loops. `Task.shutdown` calls it first, and it runs at interpreter exit.
Later calls create new loops.

## Awaiting Tasks from asyncio

The other direction needs no bridge: a flpit Task can be awaited inside any asyncio coroutine
(no setting needed), and its completion resumes the coroutine on its loop.
