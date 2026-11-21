"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Bounded channel tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/BoundedChannelTests.cs

``TestBoundedChannelTests`` also runs the shared ``ChannelTestBase`` suite. A failed
``TryRead(out int result)`` leaves ``result`` at ``default``; here the item is ``None``.
"""
from __future__ import annotations

import threading
from typing import override

import pytest

from flpit.channels import BoundedChannelFullMode, BoundedChannelOptions, Channel, ChannelClosedError
from flpit.task import CancellationToken, CancellationTokenSource, Task, TaskContinuationOptions

from nettests.channels.channel_helpers import (
    THREE_BOOLS,
    Counter,
    assert_canceled_async,
    assert_synchronous_success,
    async_test,
    not_portable,
)
from nettests.channels.channel_test_base import ChannelTestBase

CHANNEL_DROP_MODES = [mode for mode in BoundedChannelFullMode if mode is not BoundedChannelFullMode.WAIT]


class TestBoundedChannelTests(ChannelTestBase):
    @override
    def create_channel(self) -> Channel[int]:
        return Channel.create_bounded(BoundedChannelOptions(
            1, allow_synchronous_continuations=self.allow_synchronous_continuations,
        ))

    @override
    def create_full_channel(self) -> Channel[int] | None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(
            1, allow_synchronous_continuations=self.allow_synchronous_continuations,
        ))
        c.writer.write_async(0).wait()
        return c

    def test_Count_IncrementsDecrementsAsExpected(self) -> None:
        bound = 3

        c: Channel[int] = Channel.create_bounded(bound)
        assert c.reader.can_count

        for iteration in range(2):
            for i in range(bound):
                assert i == c.reader.count
                assert c.writer.try_write(i)
                assert i + 1 == c.reader.count

            assert not c.writer.try_write(42)
            assert bound == c.reader.count

            if iteration != 0:
                c.writer.complete()

            for i in range(bound):
                assert bound - i == c.reader.count
                ok, item = c.reader.try_read()
                assert ok
                assert i == item
                assert bound - (i + 1) == c.reader.count

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_TryWrite_TryRead_Many_Wait(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(buffered_capacity)

        for i in range(buffered_capacity):
            assert c.writer.try_write(i)
        assert not c.writer.try_write(buffered_capacity)

        for i in range(buffered_capacity):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_TryWrite_TryRead_Many_DropOldest(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_OLDEST)
        )

        for i in range(buffered_capacity * 2):
            assert c.writer.try_write(i)

        for i in range(buffered_capacity, buffered_capacity * 2):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_WriteAsync_TryRead_Many_DropOldest(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_OLDEST)
        )

        for i in range(buffered_capacity * 2):
            assert_synchronous_success(c.writer.write_async(i))

        for i in range(buffered_capacity, buffered_capacity * 2):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_TryWrite_TryRead_Many_DropNewest(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_NEWEST)
        )

        for i in range(buffered_capacity * 2):
            assert c.writer.try_write(i)

        for i in range(buffered_capacity - 1):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result
        ok, result = c.reader.try_read()
        assert ok
        assert buffered_capacity * 2 - 1 == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_WriteAsync_TryRead_Many_DropNewest(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_NEWEST)
        )

        for i in range(buffered_capacity * 2):
            assert_synchronous_success(c.writer.write_async(i))

        for i in range(buffered_capacity - 1):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result
        ok, result = c.reader.try_read()
        assert ok
        assert buffered_capacity * 2 - 1 == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @async_test
    async def test_TryWrite_DropNewest_WrappedAroundInternalQueue(self) -> None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(3, full_mode=BoundedChannelFullMode.DROP_NEWEST))

        # Move head of dequeue beyond the beginning
        assert c.writer.try_write(1)
        ok, item = c.reader.try_read()
        assert ok
        assert 1 == item

        # Add items to fill the capacity and put the tail at 0
        assert c.writer.try_write(2)
        assert c.writer.try_write(3)
        assert c.writer.try_write(4)

        # Add an item to overwrite the newest
        assert c.writer.try_write(5)

        # Verify current contents
        assert 2 == await c.reader.read_async()
        assert 3 == await c.reader.read_async()
        assert 5 == await c.reader.read_async()

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_TryWrite_TryRead_Many_Ignore(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_WRITE)
        )

        for i in range(buffered_capacity * 2):
            assert c.writer.try_write(i)

        for i in range(buffered_capacity):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_WriteAsync_TryRead_Many_Ignore(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(buffered_capacity, full_mode=BoundedChannelFullMode.DROP_WRITE)
        )

        for i in range(buffered_capacity * 2):
            assert_synchronous_success(c.writer.write_async(i))

        for i in range(buffered_capacity):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

        ok, result = c.reader.try_read()
        assert not ok
        assert result is None

    def test_DroppedDelegateNotCalledOnWaitMode_SyncWrites(self) -> None:
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            drop_delegate_called = True

        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(1, full_mode=BoundedChannelFullMode.WAIT), dropped)

        assert c.writer.try_write(1)
        assert not c.writer.try_write(1)

        assert not drop_delegate_called

    @async_test
    async def test_DroppedDelegateNotCalledOnWaitMode_AsyncWrites(self) -> None:
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            drop_delegate_called = True

        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(1, full_mode=BoundedChannelFullMode.WAIT), dropped)

        # First async write should pass
        await c.writer.write_async(1)

        # Second write should wait
        second_write_task = c.writer.write_async(2)
        assert not second_write_task.done()

        # Read from channel to free up space
        _read_item = await c.reader.read_async()
        # Second write should complete
        await second_write_task

        # No dropped delegate should be called
        assert not drop_delegate_called

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    def test_DroppedDelegateIsNull_SyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(1, full_mode=bounded_channel_full_mode), item_dropped=None,
        )

        assert c.writer.try_write(5)
        assert c.writer.try_write(5)

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    @async_test
    async def test_DroppedDelegateIsNull_AsyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(1, full_mode=bounded_channel_full_mode), item_dropped=None,
        )

        await c.writer.write_async(5)
        await c.writer.write_async(5)

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    def test_DroppedDelegateCalledOnChannelFull_SyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        dropped_items: set[int] = set()

        def add_dropped_item(item_dropped: int) -> None:
            assert item_dropped not in dropped_items
            dropped_items.add(item_dropped)

        channel_capacity = 10
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(channel_capacity, full_mode=bounded_channel_full_mode), add_dropped_item,
        )

        for i in range(channel_capacity):
            assert c.writer.try_write(i)

        # No dropped delegate should be called while channel is not full
        assert not dropped_items

        for i in range(channel_capacity, channel_capacity + 10):
            assert c.writer.try_write(i)

        # Assert expected number of dropped items delegate calls
        assert 10 == len(dropped_items)

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    def test_DroppedDelegateCalledAfterLockReleased_SyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] | None = None
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            if drop_delegate_called:
                # Prevent infinite callbacks being called
                return

            drop_delegate_called = True

            # Dropped delegate should not be called while holding the channel lock.
            # Verify this by trying to write into the channel from different thread.
            # If lock is held during callback, this should effectively cause deadlock.
            mres = threading.Event()

            def write() -> None:
                assert c is not None
                c.writer.try_write(3)
                mres.set()

            threading.Thread(target=write).start()

            assert mres.wait(30)

        c = Channel.create_bounded(BoundedChannelOptions(1, full_mode=bounded_channel_full_mode), dropped)

        assert c.writer.try_write(1)
        assert c.writer.try_write(2)

        assert drop_delegate_called

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    @async_test
    async def test_DroppedDelegateCalledAfterLockReleased_AsyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] | None = None
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            if drop_delegate_called:
                # Prevent infinite callbacks being called
                return

            drop_delegate_called = True

            # Dropped delegate should not be called while holding the channel synchronization lock.
            # Verify this by trying to write into the channel from different thread.
            # If lock is held during callback, this should effectively cause deadlock.
            mres = threading.Event()

            def write() -> None:
                assert c is not None
                c.writer.try_write(11)
                mres.set()

            threading.Thread(target=write).start()

            assert mres.wait(30)

        c = Channel.create_bounded(BoundedChannelOptions(1, full_mode=bounded_channel_full_mode), dropped)

        await c.writer.write_async(1)
        await c.writer.write_async(2)

        assert drop_delegate_called

    @pytest.mark.parametrize("bounded_channel_full_mode", CHANNEL_DROP_MODES)
    @async_test
    async def test_DroppedDelegateCalledOnChannelFull_AsyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        dropped_items: set[int] = set()

        def add_dropped_item(item_dropped: int) -> None:
            assert item_dropped not in dropped_items
            dropped_items.add(item_dropped)

        channel_capacity = 10
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(channel_capacity, full_mode=bounded_channel_full_mode), add_dropped_item,
        )

        for i in range(channel_capacity):
            await c.writer.write_async(i)

        # No dropped delegate should be called while channel is not full
        assert not dropped_items

        for i in range(channel_capacity, channel_capacity + 10):
            await c.writer.write_async(i)

        # Assert expected number of dropped items delegate calls
        assert 10 == len(dropped_items)

    @async_test
    async def test_CancelPendingWrite_Reading_DataTransferredFromCorrectWriter(self) -> None:
        c: Channel[int] = Channel.create_bounded(1)
        assert c.writer.write_async(42).status == Task.SUCCEEDED

        cts = CancellationTokenSource()

        write1 = c.writer.write_async(43, cts.token)
        assert not write1.done()

        cts.cancel()

        write2 = c.writer.write_async(44)

        assert 42 == await c.reader.read_async()
        assert 44 == await c.reader.read_async()

        await assert_canceled_async(cts.token, write1)
        await write2

    def test_AsyncOperation_SynchronousCancellationDuringRegistration_ReservesCompletion(self) -> None:
        not_portable("constructs the internal BlockedReadAsyncOperation through UnsafeAccessor")

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_TryWrite_TryRead_OneAtATime(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(buffered_capacity)

        num_items = 100000
        for i in range(num_items):
            assert c.writer.try_write(i)
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_SingleProducerConsumer_ConcurrentReadWrite_WithBufferedCapacity_Success(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(buffered_capacity)

        num_items = 10000

        async def write() -> None:
            for i in range(num_items):
                await c.writer.write_async(i)

        async def read() -> None:
            for i in range(num_items):
                assert i == await c.reader.read_async()

        Task.wait_all(Task.run(write), Task.run(read))

    @pytest.mark.parametrize("buffered_capacity", [1, 10, 10000])
    def test_ManyProducerConsumer_ConcurrentReadWrite_WithBufferedCapacity_Success(self, buffered_capacity: int) -> None:
        c: Channel[int] = Channel.create_bounded(buffered_capacity)

        num_writers = 10
        num_readers = 10
        num_items = 10000

        read_total = Counter()
        remaining_writers = Counter(num_writers)
        remaining_items = Counter(num_items)

        async def read() -> None:
            try:
                while True:
                    read_total.add(await c.reader.read_async())
            except ChannelClosedError:
                pass

        async def write() -> None:
            while True:
                value = remaining_items.decrement()
                if value < 0:
                    break
                await c.writer.write_async(value + 1)
            if remaining_writers.decrement() == 0:
                c.writer.complete()

        tasks = [Task.run(read) for _ in range(num_readers)] + [Task.run(write) for _ in range(num_writers)]

        Task.wait_all(tasks)
        assert (num_items * (num_items + 1)) // 2 == read_total.value

    @async_test
    async def test_WaitToWriteAsync_AfterFullThenRead_ReturnsTrue(self) -> None:
        c: Channel[int] = Channel.create_bounded(1)
        assert c.writer.try_write(1)

        write1 = c.writer.wait_to_write_async()
        assert not write1.done()

        write2 = c.writer.wait_to_write_async()
        assert not write2.done()

        assert 1 == await c.reader.read_async()

        assert await write1
        assert await write2

    @pytest.mark.parametrize(("allow_synchronous_continuations", "cancelable", "wait_to_read_async"), THREE_BOOLS)
    def test_AllowSynchronousContinuations_Reading_ContinuationsInvokedAccordingToSetting(
            self, allow_synchronous_continuations: bool, cancelable: bool, wait_to_read_async: bool,
    ) -> None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(
            1, allow_synchronous_continuations=allow_synchronous_continuations,
        ))

        ct = CancellationTokenSource().token if cancelable else CancellationToken.none()

        expected_id = threading.get_ident()

        def continuation(_: Task[object]) -> None:
            assert allow_synchronous_continuations == (expected_id == threading.get_ident())

        t: Task[object] = c.reader.wait_to_read_async(ct) if wait_to_read_async else c.reader.read_async(ct)
        r = t.continue_with(continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)

        assert c.writer.write_async(42).status == Task.SUCCEEDED
        r.wait()  # avoid inlining the continuation
        r.result()

    @pytest.mark.parametrize("allow_synchronous_continuations", [False, True])
    def test_AllowSynchronousContinuations_CompletionTask_ContinuationsInvokedAccordingToSetting(
            self, allow_synchronous_continuations: bool,
    ) -> None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(
            1, allow_synchronous_continuations=allow_synchronous_continuations,
        ))

        expected_id = threading.get_ident()

        def continuation(_: Task[None]) -> None:
            assert allow_synchronous_continuations == (expected_id == threading.get_ident())

        r = c.reader.completion.continue_with(continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)

        assert c.writer.try_complete()
        r.wait()  # avoid inlining the continuation
        r.result()

    @async_test
    async def test_TryWrite_NoBlockedReaders_WaitingReader_WaiterNotified(self) -> None:
        c = self.create_channel()

        r = c.reader.wait_to_read_async()
        assert c.writer.try_write(42)
        assert await r
