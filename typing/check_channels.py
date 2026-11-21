"""Static inference checks for flpit.channels (run: uv run pyrefly check typing/check_channels.py)."""
from typing import Literal, assert_type

from flpit import AsyncFlpIt
from flpit.channels import (
    BoundedChannelFullMode,
    BoundedChannelOptions,
    Channel,
    ChannelReader,
    ChannelWriter,
    UnboundedPrioritizedChannelOptions,
)
from flpit.task import CancellationToken, Task

# --- factories ----------------------------------------------------------------------------------
UNBOUNDED: Channel[int] = Channel.create_unbounded()
BOUNDED: Channel[str] = Channel.create_bounded(10)
DROPPING: Channel[str] = Channel.create_bounded(
    BoundedChannelOptions(10, full_mode=BoundedChannelFullMode.DROP_OLDEST),
    item_dropped=lambda item: None,
)
PRIORITIZED = Channel.create_unbounded_prioritized(
    UnboundedPrioritizedChannelOptions[int](comparer=lambda a, b: b - a)
)
assert_type(PRIORITIZED, Channel[int])

# --- reader / writer ----------------------------------------------------------------------------
assert_type(UNBOUNDED.reader, ChannelReader[int])
assert_type(UNBOUNDED.writer, ChannelWriter[int])

assert_type(UNBOUNDED.writer.try_write(1), bool)
assert_type(UNBOUNDED.writer.write_async(1), Task[None])
assert_type(UNBOUNDED.writer.wait_to_write_async(CancellationToken.none()), Task[bool])
assert_type(UNBOUNDED.writer.try_complete(), bool)

assert_type(UNBOUNDED.reader.try_read(), tuple[Literal[True], int] | tuple[Literal[False], None])
assert_type(UNBOUNDED.reader.try_peek(), tuple[Literal[True], int] | tuple[Literal[False], None])
assert_type(UNBOUNDED.reader.read_async(), Task[int])
assert_type(UNBOUNDED.reader.wait_to_read_async(), Task[bool])
assert_type(UNBOUNDED.reader.read_all_async(), AsyncFlpIt[int])
assert_type(UNBOUNDED.reader.completion, Task[None])
assert_type(UNBOUNDED.reader.count, int)

match UNBOUNDED.reader.try_read():
    case (True, item):
        assert_type(item, int)  # narrowed by the Literal[True] tuple
    case (False, nothing):
        assert_type(nothing, None)


async def consume() -> None:
    value = await BOUNDED.reader.read_async()
    assert_type(value, str)

    async for text in BOUNDED.reader.read_all_async().where(lambda s: s != ""):
        assert_type(text, str)
