---
description: Channel[T] in Python, modelled on .NET System.Threading.Channels. Thread-safe producer/consumer queues with backpressure, drop modes, prioritised channels and LINQ over the stream.
---
# Channels

`Channel[T]` is a thread-safe producer/consumer queue with backpressure, modelled on .NET's
`System.Threading.Channels`. It works between [tasks](../task/index.md) and between plain threads.

## Producer and consumer

A bounded channel makes writers wait while it is full, so memory stays bounded however fast the producers are.
`writer.complete()` ends the consumer's loop once the buffer is drained:

```python
--8<-- "examples/channels/overview.py:producer_consumer"
```

`read_all_async()` returns an [`AsyncFlpIt`](../async/index.md), so `where`, `select`, `chunk` and the rest work
on the stream as it arrives. `reader.completion` completes after the last item has been read.

## Without waiting

`try_write` and `try_read` never wait. `try_read()` returns `(True, item)` or `(False, None)`:

```python
--8<-- "examples/channels/overview.py:try"
```

## Dropping instead of waiting

When a reader only cares about recent values, such as a sensor feeding a dashboard, let a full channel make room
by dropping an item. The writer never waits:

```python
--8<-- "examples/channels/overview.py:drop"
```

## Kinds of channel

- **Unbounded:** `Channel.create_unbounded()`. Writes always succeed.
- **Bounded:** `Channel.create_bounded(capacity)`. Writers wait when it is full, or, with
  `BoundedChannelOptions(capacity, full_mode=...)`, drop the oldest item (`DROP_OLDEST`), the newest one in the
  buffer (`DROP_NEWEST`), or the item being written (`DROP_WRITE`). Pass `item_dropped=callback` to
  `create_bounded` to be told about each dropped item.
- **Rendezvous:** `Channel.create_bounded(0)`. A write completes only when a reader takes the item.
- **Prioritised:** `Channel.create_unbounded_prioritized()`. Reads return the smallest item first.

Writing to a completed channel raises `ChannelClosedError`.

More programs:
[`examples/channels/`](https://github.com/riemar/flpit/tree/main/examples/channels).
