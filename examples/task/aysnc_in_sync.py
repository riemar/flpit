"""
Example: Making Asynchronous Functions Awaitable inside Synchronous Scopes

This example demonstrates the exact inversion of what flpit.task was made for.
It works but...
    You also can drill a hole into your knee and plug it with a cork
    — the question is whether you should.

Key Takeaways:
1. **The Inversion Pattern**:
    This is NOT the intended default use case of the library,
    but it works. It flips the execution model—allowing regular blocking functions
    to seamlessly invoke and resolve async coroutines.

2. **Shared loops**:
    Behind the scenes, `@asyncio_task` runs the coroutine on one of the shared asyncio loops of
    `flpit.asyncio_bridge`; no event loop is created per call.
"""
from flpit.task import Task, task, asyncio_task, twait

async def coro_independent():
    return 2

@task
async def work():
    res = await coro_independent()
    await Task.delay(0.5)
    return res + 3

@asyncio_task
async def coro_dependent():
    """co routine with asyncio dependency."""
    import asyncio
    await asyncio.sleep(1)
    return 4

def main():
    task = work() # immediately executes and returns a task
    res = twait >> task # awaits the task
    print("received from sync: ", res)

    coro_res = twait >> coro_dependent()
    print("received from coro: ", coro_res)


if __name__ == '__main__':
    main()