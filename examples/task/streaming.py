"""
Example: Native Async Streaming (IAsyncEnumerable with AsyncFlpIt)

This example shows how to stream data lazily using asynchronous generators.
Unlike launching a huge batch of tasks at once, this pattern processes data
in a memory-efficient pipeline, item by item.

`@async_flpit` turns such a producer into a LINQ query (.NET System.Linq.AsyncEnumerable):
operators stay lazy, terminal operators return a Task, and a CancellationToken
flows through the whole pipeline into the producer's `token` parameter.
"""

import time

from flpit import AsyncFlpIt, async_flpit
from flpit.task import CancellationToken, CancellationTokenSource, Task


@async_flpit
async def async_data_stream(token: CancellationToken = CancellationToken.none()):
    """A true lazy data producer. It streams data on demand and observes the token."""
    for i in range(1, 6):
        # In a real app, this would be reading a line from a huge file
        # or fetching the next page from a database chunk by chunk.
        print(f"Producer: Fetching item {i}...")

        # We simulate a small async step inside the pipeline
        await Task.run(time.sleep, 0.2, token=token)

        yield i  # Yield control and data back to the consumer


async def is_interesting(item: int, token: CancellationToken) -> bool:
    """An asynchronous predicate (.NET: Func<T, CancellationToken, ValueTask<bool>>)."""
    await Task.delay(0.01, token=token)
    return item != 3


async def main():
    # @async_flpit passes the enumeration's token to the producer's `token` parameter
    # (the counterpart of an [EnumeratorCancellation] parameter).
    stream = async_data_stream()

    query = (
        stream
        .where(is_interesting)  # async callback
        .select(lambda item: f"Item {item} Payload")  # sync callback
    )

    print("Main: Starting data stream consumption...\n")

    # The native Python equivalent to C#'s await foreach. Nothing above ran yet:
    # the query is enumerated (and the producer started) only now, item by item.
    async for data_item in query:
        print(f"Main: Consumed -> {data_item}")

    # Terminal operators return a Task: await it inside the runtime ...
    total = await stream.sum()
    print(f"\nMain: Sum of the stream -> {total}")

    # ... and the token flows into the producer when the query is cancelled.
    cts = CancellationTokenSource()
    try:
        async for item in stream.with_cancellation(cts.token):
            print(f"Main: Got {item}, cancelling")
            cts.cancel()
    except Exception as error:  # OperationCanceledError
        print(f"Main: Stream cancelled -> {type(error).__name__}")

    print("\nMain: Stream finished cleanly!")


if __name__ == "__main__":
    Task.run(main).result()

    # From synchronous code, block on the Task a terminal operator returns.
    print(AsyncFlpIt.range(1, 10).where(lambda x: x % 2 == 0).to_list().result())
