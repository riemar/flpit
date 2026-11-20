"""
Example: async yield + await foreach (async generators on the flpit runtime)

C# has async iterators: an `async IAsyncEnumerable<T>` method that both awaits and
`yield return`s, consumed with `await foreach`:

    async IAsyncEnumerable<int> CountdownAsync(int from)
    {
        for (var i = from; i > 0; i--)
        {
            await Task.Delay(100);
            yield return i;
        }
    }

    await foreach (var n in CountdownAsync(3))
        Console.WriteLine(n);

The Python equivalent is an `async def` that contains `yield` (an async generator),
consumed with `async for`. This example runs it on the flpit task runtime: no asyncio.

Key takeaways:
1. **Lazy**: calling the async generator runs nothing; each `async for` step resumes
   the producer until its next `yield`.
2. **Await inside the producer**: the producer can await flpit Tasks (`Task.delay`,
   `Task.run`) between yields.
3. **Disposal on break**: C#'s `await foreach` always calls `DisposeAsync()`, so the
   producer's `finally` runs at once. Python's `async for` does not close the
   generator on `break`; use `contextlib.aclosing` (or call `aclose()`) to get the
   same guarantee.
4. **LINQ on top**: `flp.ait(...)` wraps the same async generator in an `AsyncFlpIt`
   query, which also closes its enumerators when it short-circuits.
"""

import time
from collections.abc import AsyncGenerator
from contextlib import aclosing

from flpit import flp
from flpit.task import Task


async def countdown(start: int) -> AsyncGenerator[int]:
    """An async method that yields: the counterpart of `async IAsyncEnumerable<int>`."""
    print(f"  producer: started (from {start})")
    try:
        for i in range(start, 0, -1):
            await Task.delay(0.1)  # await inside the producer ...
            print(f"  producer: yield {i}")
            yield i  # ... and yield the next element back to the consumer
    finally:
        # Runs when the sequence completes, or when the consumer closes it early.
        print("  producer: disposed")


def blocking_square(x: int) -> int:
    time.sleep(0.05)  # stands in for blocking I/O or CPU work
    return x * x


async def slow_square(n: int) -> AsyncGenerator[int]:
    """The producer can also await blocking work offloaded to the pool."""
    for i in range(1, n + 1):
        yield await Task.run(blocking_square, i)


async def main() -> None:
    print("1) await foreach over an async generator")
    async for n in countdown(3):  # C#: await foreach (var n in CountdownAsync(3))
        print(f"consumer: got {n}")

    print("\n2) break early with await foreach disposal semantics")
    async with aclosing(countdown(5)) as numbers:
        async for n in numbers:
            print(f"consumer: got {n}")
            if n == 4:
                break  # aclosing closes the generator -> its `finally` runs now

    print("\n3) the producer awaits pool work between yields")
    async for square in slow_square(4):
        print(f"consumer: square {square}")

    print("\n4) the same async generator as a LINQ query (AsyncFlpIt)")
    query = flp.ait(countdown(6)).where(lambda n: n % 2 == 0).select(lambda n: n * 10)
    async for value in query:  # still just `async for`
        print(f"consumer: query value {value}")

    print("\n5) terminal operators return a Task you can await")
    first_even = await flp.ait(countdown(5)).first(lambda n: n % 2 == 0)
    print(f"consumer: first even -> {first_even}")  # producer is disposed after the match


if __name__ == "__main__":
    Task.run(main).result()
