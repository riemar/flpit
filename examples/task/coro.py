"""
Example: Integration with Asyncio-Dependent Ecosystems (Escape Hatch)

This example demonstrates how to use the `@coro_task` decorator to bridge
existing, asyncio-dependent code blocks (such as `httpx.AsyncClient`)
into the flpit native thread-pool runtime.

Key Takeaways:
1. **Escape Hatch Pattern**: This is NOT the recommended default for flpit.
   For regular application logic, use the native synchronous `@task` decorator
   to achieve maximum performance with zero event-loop overhead.
   See lab/task/httpx_Client.py for comparison
2. **Dynamic Runner Provisioning**: Behind the scenes, EVERY SINGLE task invocation
   and background await spins up its own dedicated, short-lived `asyncio.Runner`
   context manager inside the assigned worker thread. It is completely
   thread-isolated and ephemeral.
3. **Ecosystem Compatibility**: Use this pattern strictly when you are forced
   to interface with third-party async libraries that cannot be run in a
   standard synchronous thread context.
"""
import httpx
from flpit.task import coro_task, Task


@coro_task # this is meant to be an escape hatch, not the default
async def fetch_coro(task_id: int):
    # the async client is asyncio dependent
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://httpbin.org/delay/{5 - task_id * 2}")
        print(f"{task_id}: done!")
        return { "id": task_id, "data": response.json()}


async def main():
    # runs 2 regular asyncio.Runner dependent execute in parallel
    t1 = Task.run(lambda: fetch_coro(1))
    t2 = Task.run(lambda: fetch_coro(2))

    await Task.when_all([t1, t2])

    print(t1.result())
    print(t2.result())


if __name__ == "__main__":
    Task.run(main).result()