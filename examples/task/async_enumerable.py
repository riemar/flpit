"""
Example: async iterators with @async_flpit (C#: async IAsyncEnumerable<T> + await foreach)

C# has async iterators: an `async IAsyncEnumerable<T>` method that both awaits and
`yield return`s, consumed with `await foreach`:

    async IAsyncEnumerable<int> CountdownAsync(int from, [EnumeratorCancellation] CancellationToken token = default)
    {
        for (var i = from; i > 0; i--)
        {
            await Task.Delay(100, token);
            yield return i;
        }
    }

    await foreach (var n in CountdownAsync(3))
        Console.WriteLine(n);

In flpit: an `async def` with `yield`, decorated with `@async_flpit`, consumed with
`async for`. Calling it returns an `AsyncFlpIt`, flpit's `IAsyncEnumerable<T>`.

Key takeaways:
1. **Cold**: calling `countdown(3)` runs nothing; each `async for` starts a fresh
   enumeration, so the same stream can be enumerated again.
2. **Await inside the producer**: the producer awaits flpit Tasks between yields.
3. **LINQ**: the result is an `AsyncFlpIt`, so the async LINQ operators work on it.
4. **Cancellation**: the `token` parameter receives the enumeration's token, like
   C#'s `[EnumeratorCancellation]`; `with_cancellation(token)` passes one in.

Leaving the loop early is safe as well; await_using.py shows how to have the
producer's cleanup completed at a point you choose.
"""

from collections.abc import AsyncGenerator

from flpit import async_flpit
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task


@async_flpit
async def countdown(start: int, token: CancellationToken = CancellationToken.none()) -> AsyncGenerator[int]:
    """C#: async IAsyncEnumerable<int> CountdownAsync(int start, [EnumeratorCancellation] CancellationToken token = default)"""
    print(f"  producer: started (from {start})")

    for i in range(start, 0, -1):
        await Task.delay(0.05, token=token)  # await inside the producer ...
        yield i  # ... and yield the next element back to the consumer


async def main() -> None:
    print("1) await foreach")

    async for n in countdown(3):  # C#: await foreach (var n in CountdownAsync(3))
        print(f"consumer: got {n}")

    print("\n2) cold and enumerable again: each loop starts the producer anew")

    numbers = countdown(2)

    print(f"consumer: first pass  {[n async for n in numbers]}")
    print(f"consumer: second pass {[n async for n in numbers]}")

    print("\n3) LINQ on the stream")

    evens = await countdown(6).where(lambda n: n % 2 == 0).select(lambda n: n * 10).to_list()

    print(f"consumer: {evens}")

    print("\n4) cancellation reaches the producer's token")

    cts = CancellationTokenSource()

    try:
        async for n in countdown(5).with_cancellation(cts.token):
            print(f"consumer: got {n}, cancelling")
            cts.cancel()

    except OperationCanceledError:
        print("consumer: stream cancelled")


if __name__ == "__main__":
    Task.run(main).result()
