"""
Example: keep only the newest readings (BoundedChannelFullMode.DROP_OLDEST)

A sensor writes faster than the dashboard reads. Nobody wants a growing backlog of stale
values: with a drop mode the writer never waits, and a full channel makes room by
dropping an item, reported to `item_dropped`:

    var channel = Channel.CreateBounded<int>(
        new BoundedChannelOptions(3) { FullMode = BoundedChannelFullMode.DropOldest },
        itemDropped: reading => Console.WriteLine($"dropped {reading}"));

    channel.Writer.TryWrite(reading);   // always succeeds

The same in flpit. Key takeaways:
1. **Writers never wait**: `try_write` always succeeds in a drop mode.
2. **Bounded staleness**: the reader sees at most the 3 newest readings.
3. **DROP_NEWEST / DROP_WRITE** keep the old items instead and drop the newest one, or the
   one being written.
"""

from flpit.channels import BoundedChannelFullMode, BoundedChannelOptions, Channel
from flpit.task import Task


async def main() -> None:
    dropped: list[int] = []

    channel: Channel[int] = Channel.create_bounded(
        BoundedChannelOptions(3, full_mode=BoundedChannelFullMode.DROP_OLDEST),
        item_dropped=dropped.append,
    )

    for reading in range(1, 11):  # the sensor: ten readings, nobody reading yet
        assert channel.writer.try_write(reading)

    channel.writer.complete()

    readings = await channel.reader.read_all_async().to_list()

    print(f"read:    {readings}")  # [8, 9, 10]
    print(f"dropped: {dropped}")   # [1, 2, 3, 4, 5, 6, 7]


if __name__ == "__main__":
    Task.run(main).result()
