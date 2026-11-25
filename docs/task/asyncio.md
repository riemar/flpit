# asyncio libraries

!!! note "Provisional"
    `flpit.asyncio_bridge` (`provide`, `Loop`, `PerLoop`, `run_asyncio`, `configure`, `shutdown`) is provisional: its API may
    still change in 0.5. The default backend on Linux drives CPython's asyncio internals; the `"threads"`
    backend uses public asyncio API only and is the fallback should a Python release change them.
    `@asyncio_task` keeps its signature.

## Prefer the sync client

flpit runs your code on threads, so the first choice for I/O is a library's **sync** client, written for threads
and meant to be shared: one `httpx.Client` for the whole process, one psycopg `ConnectionPool`. They need no event
loop, no bridge and no per-loop copies.

A sync call holds its worker while it waits. The pool notices: a worker that has waited for a few milliseconds
while work is queued is replaced, up to `burst_workers` (default 256), so the pool grows with the calls in flight
(see [the Task runtime](index.md)). Give the client as many connections:

```python
import httpx
from flpit.task import task

client = httpx.Client(limits=httpx.Limits(max_connections=256, max_keepalive_connections=64))


@task
def fetch(url: str) -> dict:
    return client.get(url).json()
```

100 parallel calls that each wait 50 ms took about 0.9 s on a 2-core machine with the pool's default size
(CPU count + 4 workers) and no replacement, and 0.12–0.25 s with it, on par with one asyncio loop and one
`httpx.AsyncClient`.

## When a library only exists for asyncio

Libraries built only on asyncio, such as asyncpg, need an event loop: their code calls
`asyncio.get_running_loop()`, and their connections, locks and futures belong to the loop that created them.
asyncio code is not thread-safe: one client cannot be shared between loops. `flpit.asyncio_bridge` provides
those loops on the flpit runtime, and `@asyncio_task` runs a function on them. The example uses
`httpx.AsyncClient` because it is easy to try; for HTTP itself, the sync client above is the better fit.

```python
import httpx
from flpit import asyncio_bridge
from flpit.asyncio_bridge import Loop, injected
from flpit.task import CancellationToken, asyncio_task

# One client per loop, created when the loop starts, closed with the loop.
asyncio_bridge.provide(httpx.AsyncClient, lambda: httpx.AsyncClient(timeout=10), warm=True)


@asyncio_task
async def fetch(url: str, token: CancellationToken, client: Loop[httpx.AsyncClient] = injected) -> dict:
    return (await client.get(url)).json()


task = fetch("https://example.org/data.json", token)  # a flpit Task; await it, or .result()
```

The caller does not pass `client`: a `Loop[T]` parameter receives the `T` of the loop the call runs on.
`= injected` tells type checkers that it may be left out; a value the caller does pass wins.

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

Clients and connection pools are bound to the loop that created them, so an object that lives longer than a
call, such as a singleton, must not keep one: it would keep the client of the loop it was built on. It keeps a
`PerLoop[T]` instead and reads `.current`, the value of the loop the call runs on:

```python
from flpit.asyncio_bridge import PerLoop

clients = PerLoop(lambda: httpx.AsyncClient(base_url="https://api.github.com"), warm=True)


class GitHubApi:
    def __init__(self, clients: PerLoop[httpx.AsyncClient]) -> None:
        self._clients = clients

    @asyncio_task
    async def repo(self, name: str) -> dict:
        return (await self._clients.current.get(f"/repos/{name}")).json()


api = GitHubApi(clients)
```

`provide()` returns the `PerLoop` it uses, so both styles can share one set of clients, and it also accepts
an existing `PerLoop`. Providing a type again replaces the provider and closes the values its factory made.

- **Factories** may be plain functions or `async def`. `await per_loop.get()` works with both; `.current`
  needs a plain factory or `warm=True`.
- **`warm=True`** creates the value on each pool loop when the loop starts, before it takes work, and on the
  loops that exist already, so no call pays for it. If the factory fails there, the work waiting for that loop
  fails with `LoopStartError` (the factory's error as its cause) and the loop is replaced by a new one.
- **Other loops.** On a loop the bridge did not create (your application's own), values are created on first
  use and not warmed.
- **Closing.** When a loop is closed, its values are closed with it (`await value.aclose()` if the value has
  one, otherwise `value.close()`), on that loop. `per_loop.close()` closes the values of every loop.

A client whose async API is thread-safe, such as pyreqwest's `Client`, needs none of this: one instance can
be shared by every loop. `LoopLocal`, the earlier form of `PerLoop`, keeps working.

## Shutdown

`asyncio_bridge.shutdown(timeout)` cancels the calls still running, closes the per-loop values and async
generators of each loop, and closes the loops. `Task.shutdown` calls it first, and it runs at interpreter exit.
Later calls create new loops.

## Awaiting Tasks from asyncio

The other direction needs no bridge: a flpit Task can be awaited inside any asyncio coroutine
(no setting needed), and its completion resumes the coroutine on its loop.
