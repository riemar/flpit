"""
Example: asyncio libraries on the flpit runtime

`@asyncio_task` runs code that needs an asyncio event loop (here `httpx.AsyncClient`) on the
shared loops of `flpit.asyncio_bridge` and returns a flpit Task.

Key Takeaways:
1. **Shared loops, not one per call**: calls run on a small pool of standard asyncio loops
   (one per CPU by default, created on first use). On Linux a loop is a serialized queue on the
   flpit pool and costs no thread; no worker is blocked while a call waits for I/O.
2. **One client per loop**: an `httpx.AsyncClient` belongs to the loop that created it.
   `LoopLocal` keeps one per loop, reused by every call on that loop and closed with the loop.
3. **Cancellation**: a `CancellationToken` argument cancels the call.
4. **Not the default for your own code**: plain functions and flpit coroutines with `@task` need
   no event loop at all. For HTTP itself, one shared sync `httpx.Client` on flpit threads is
   usually the better choice (docs/task/asyncio.md); this example shows the pattern for
   libraries that only exist for asyncio. See lab/task/httpx_Client.py for comparison.
"""
import httpx

from flpit.asyncio_bridge import LoopLocal
from flpit.task import CancellationToken, CancellationTokenSource, Task, asyncio_task

clients: LoopLocal[httpx.AsyncClient] = LoopLocal(httpx.AsyncClient)


@asyncio_task
async def fetch_coro(task_id: int, token: CancellationToken):
    client = await clients.get()
    response = await client.get(f"https://httpbin.org/delay/{5 - task_id * 2}")
    print(f"{task_id}: done!")
    return {"id": task_id, "data": response.json()}


async def main():
    source = CancellationTokenSource()
    source.cancel_after(30)
    t1 = fetch_coro(1, source.token)
    t2 = fetch_coro(2, source.token)

    await Task.when_all([t1, t2])

    print(t1.result())
    print(t2.result())


if __name__ == "__main__":
    Task.run(main).result()
