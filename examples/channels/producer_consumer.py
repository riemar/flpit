"""
Example: producer / consumer with backpressure (Channel[T])

The .NET pattern: a bounded channel between fast producers and a slower consumer.
Producers wait while the channel is full, so memory stays bounded:

    var channel = Channel.CreateBounded<Order>(capacity: 5);

    async Task ProduceAsync(int shop)
    {
        for (int i = 0; i < 10; i++)
            await channel.Writer.WriteAsync(new Order(shop, i));   // waits while full
    }

    await Task.WhenAll(ProduceAsync(1), ProduceAsync(2));
    channel.Writer.Complete();                                     // no more orders

    await foreach (var order in channel.Reader.ReadAllAsync())     // ends after Complete()
        await ShipAsync(order);

The same in flpit. Key takeaways:
1. **Backpressure**: `write_async` waits while the channel holds `capacity` items.
2. **Completion**: `writer.complete()` ends `read_all_async()` once the buffer is drained;
   `reader.completion` completes after the last item has been read.
3. **LINQ on a channel**: `read_all_async()` returns an `AsyncFlpIt`, so `where`, `select`,
   `chunk`, ... work on the stream as it arrives.
"""

import sys
import threading
import time

from flpit.channels import Channel
from flpit.task import Task

started_at = time.monotonic()
_print_lock = threading.Lock()


def log(message: str) -> None:
    # Tasks run on several pool threads: write whole lines so output doesn't interleave.
    with _print_lock:
        sys.stdout.write(f"[{time.monotonic() - started_at:4.2f}s] {message}\n")


async def produce(channel: Channel[str], shop: int) -> None:
    for i in range(1, 6):
        order = f"shop {shop} / order {i}"

        await channel.writer.write_async(order)  # waits while the channel is full

        log(f"  queued   {order}   (buffered: {channel.reader.count})")


async def main() -> None:
    channel: Channel[str] = Channel.create_bounded(3)

    async def produce_all() -> None:
        await Task.when_all(produce(channel, 1), produce(channel, 2))

        channel.writer.complete()  # no more orders: ends the consumer's loop
        log("producers done")

    producers = Task.run(produce_all)

    # The consumer ships two orders at a time; the producers are held back meanwhile.
    async for batch in channel.reader.read_all_async().chunk(2):
        await Task.delay(0.1)  # shipping takes a while

        log(f"shipped  {batch}")

    await producers
    await channel.reader.completion

    log("all orders shipped")


if __name__ == "__main__":
    Task.run(main).result()
