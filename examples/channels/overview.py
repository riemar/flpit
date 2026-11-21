"""Channels, in short."""
# --8<-- [start:producer_consumer]
from flpit.channels import Channel
from flpit.task import Task

channel: Channel[int] = Channel.create_bounded(2)    # writers wait while 2 items are buffered


async def produce() -> None:
    for n in range(5):
        await channel.writer.write_async(n)          # waits while the channel is full
    channel.writer.complete()                        # no more items: ends the consumer's loop


async def main() -> None:
    Task.run(produce)

    # read_all_async() is an AsyncFlpIt, so LINQ works on the stream as it arrives.
    squares = await (
        channel.reader
             .read_all_async()
             .select(lambda n: n * n)
             .to_list()
    )
    assert squares == [0, 1, 4, 9, 16]


Task.run(main).result()
# --8<-- [end:producer_consumer]

# --8<-- [start:try]
inbox: Channel[str] = Channel.create_unbounded()

assert inbox.writer.try_write("hello")               # never waits
assert inbox.reader.try_read() == (True, "hello")
assert inbox.reader.try_read() == (False, None)      # nothing there, and no exception
# --8<-- [end:try]

# --8<-- [start:drop]
from flpit.channels import BoundedChannelFullMode, BoundedChannelOptions

latest: Channel[int] = Channel.create_bounded(
    BoundedChannelOptions(2, full_mode=BoundedChannelFullMode.DROP_OLDEST)
)

for reading in range(1, 6):
    latest.writer.try_write(reading)                 # always succeeds: the oldest item makes room

latest.writer.complete()
assert latest.reader.read_all_async().to_list().result() == [4, 5]
# --8<-- [end:drop]
