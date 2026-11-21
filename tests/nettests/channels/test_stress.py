"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Channel stress tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/Stress.cs

Upstream runs these only with stress mode enabled; here they are marked ``stress`` (run them
with ``-m stress``).
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from flpit.channels import (
    BoundedChannelFullMode,
    BoundedChannelOptions,
    Channel,
    ChannelClosedError,
    ChannelOptions,
    ChannelReader,
    ChannelWriter,
    UnboundedChannelOptions,
)
from flpit.task import AggregateError, CancellationTokenSource, OperationCanceledError, Task

from nettests.channels.channel_helpers import Counter, async_test

type ReadDelegate = Callable[[ChannelReader[int]], Awaitable[bool]]
type WriteDelegate = Callable[[ChannelWriter[int], int], Awaitable[Any]]


async def read_synchronous(reader: ChannelReader[int]) -> bool:
    while not reader.try_read()[0]:
        if not await reader.wait_to_read_async():
            return False

        reader.try_peek()

    return True


async def read_asynchronous(reader: ChannelReader[int]) -> bool:
    if await reader.wait_to_read_async():
        await reader.read_async()
        return True

    return False


async def read_asynchronous_no_wait(reader: ChannelReader[int]) -> bool:
    await reader.read_async()
    return True


async def write_asynchronous_no_wait(writer: ChannelWriter[int], value: int) -> bool:
    await writer.write_async(value)
    return True


async def read_sync_and_async(reader: ChannelReader[int]) -> bool:
    if not reader.try_read()[0]:
        if await reader.wait_to_read_async():
            await reader.read_async()
            return True
        return False

    return True


async def write_synchronous(writer: ChannelWriter[int], value: int) -> None:
    while not writer.try_write(value):
        if not await writer.wait_to_write_async():
            break


async def write_asynchronous(writer: ChannelWriter[int], value: int) -> None:
    if await writer.wait_to_write_async():
        await writer.write_async(value)


async def write_sync_and_async(writer: ChannelWriter[int], value: int) -> None:
    if not writer.try_write(value):
        if await writer.wait_to_write_async():
            await writer.write_async(value)


def _unbounded(options: ChannelOptions) -> Channel[int]:
    assert isinstance(options, UnboundedChannelOptions)
    return Channel.create_unbounded(options)


def _bounded(options: ChannelOptions) -> Channel[int]:
    assert isinstance(options, BoundedChannelOptions)
    return Channel.create_bounded(options)


def read_write_variations_test_data() -> list[Any]:
    data: list[Any] = []
    reads: list[ReadDelegate] = [read_synchronous, read_asynchronous, read_sync_and_async]
    writes: list[WriteDelegate] = [write_synchronous, write_asynchronous, write_sync_and_async]
    bools = [False, True]

    # Unbounded
    for read_delegate in reads:
        for write_delegate in writes:
            for single_reader in bools:
                for single_writer in bools:
                    for allow in bools:
                        options = UnboundedChannelOptions(
                            single_reader=single_reader, single_writer=single_writer,
                            allow_synchronous_continuations=allow,
                        )
                        data.append((_unbounded, options, read_delegate, write_delegate))

    # Bounded
    for read_delegate in reads:
        for write_delegate in writes:
            for bco in BoundedChannelFullMode:
                for capacity in (1, 1000):
                    for single_reader in bools:
                        for single_writer in bools:
                            for allow in bools:
                                options = BoundedChannelOptions(
                                    capacity, full_mode=bco, single_reader=single_reader,
                                    single_writer=single_writer, allow_synchronous_continuations=allow,
                                )
                                data.append((_bounded, options, read_delegate, write_delegate))

    # Rendezvous
    for read_delegate in [*reads, read_asynchronous_no_wait]:
        for write_delegate in [*writes, write_asynchronous_no_wait]:
            for bcfm in (BoundedChannelFullMode.WAIT, BoundedChannelFullMode.DROP_WRITE):
                for allow in bools:
                    if read_delegate is not read_asynchronous_no_wait and write_delegate is not write_asynchronous_no_wait:
                        # At least one side must be persistent.
                        continue

                    options = BoundedChannelOptions(0, full_mode=bcfm, allow_synchronous_continuations=allow)
                    data.append((_bounded, options, read_delegate, write_delegate))

    return data


MAX_NUMBER_TO_WRITE_TO_CHANNEL = 400_000
MAX_TASK_COUNTS = max(2, os.cpu_count() or 1)


class TestStressTests:
    @pytest.mark.stress
    @pytest.mark.parametrize(("channel_creator", "options", "read_delegate", "write_delegate"), read_write_variations_test_data())
    def test_ReadWriteVariations(
            self,
            channel_creator: Callable[[ChannelOptions], Channel[int]],
            options: ChannelOptions,
            read_delegate: ReadDelegate,
            write_delegate: WriteDelegate,
    ) -> None:
        channel = channel_creator(options)
        reader = channel.reader
        writer = channel.writer
        should_read_all_written_values = (
            not isinstance(options, BoundedChannelOptions) or options.full_mode is BoundedChannelFullMode.WAIT
        )

        task_list: list[Task[Any]] = []

        if options.single_reader:
            reader_tasks_count = 1
            writer_tasks_count = 1 if options.single_writer else MAX_TASK_COUNTS - 1
        elif options.single_writer:
            writer_tasks_count = 1
            reader_tasks_count = MAX_TASK_COUNTS - 1
        else:
            reader_tasks_count = MAX_TASK_COUNTS // 2
            writer_tasks_count = MAX_TASK_COUNTS - reader_tasks_count

        read_count = Counter()

        async def read() -> None:
            try:
                while True:
                    if not await read_delegate(reader):
                        break
                    read_count.increment()
            except ChannelClosedError:
                pass

        for _ in range(reader_tasks_count):
            task_list.append(Task.run(read))

        number_to_write_to_queue = Counter(-1)
        remaining_writers = Counter(writer_tasks_count)

        async def write() -> None:
            num = number_to_write_to_queue.increment()
            while num < MAX_NUMBER_TO_WRITE_TO_CHANNEL:
                await write_delegate(writer, num)
                num = number_to_write_to_queue.increment()

            if remaining_writers.decrement() == 0:
                writer.complete()

        for _ in range(writer_tasks_count):
            task_list.append(Task.run(write))

        Task.wait_all(task_list)

        if should_read_all_written_values:
            assert MAX_NUMBER_TO_WRITE_TO_CHANNEL == read_count.value
        else:
            assert 0 <= read_count.value <= MAX_NUMBER_TO_WRITE_TO_CHANNEL

    @pytest.mark.stress
    @pytest.mark.parametrize("channel_factory", [
        lambda: Channel.create_unbounded(),
        lambda: Channel.create_unbounded(UnboundedChannelOptions(single_reader=True, single_writer=True)),
        lambda: Channel.create_bounded(2**31 - 1),
    ])
    @async_test
    async def test_CanceledReads(self, channel_factory: Callable[[], Channel[int]]) -> None:
        attempts = 100
        writes = 1_000
        wait_timeout = 100.0

        for _ in range(attempts):
            cts = CancellationTokenSource()
            channel = channel_factory()

            # Create a bunch of reads, half of which are cancelable
            reads = [channel.reader.read_async(cts.token if i % 2 == 0 else None) for i in range(writes)]

            # Queue cancellation
            _ = Task.run(cts.cancel)

            # Write to complete the rest of the tasks
            for item in range(writes):
                assert channel.writer.try_write(item)
            channel.writer.complete()

            # Wait for all the reads to complete
            try:
                assert Task.wait_all(reads, timeout=wait_timeout)
            except AggregateError as ae:
                assert all(isinstance(e, OperationCanceledError) for e in ae.exceptions)

            # Validate all write data showed up
            expected = 0
            actual = 0
            for write in range(writes):
                expected += write
                if reads[write].status == Task.SUCCEEDED:
                    actual += reads[write].result()
            async for remaining in channel.reader.read_all_async():
                actual += remaining
            assert expected == actual
