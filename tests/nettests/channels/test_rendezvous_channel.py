"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Rendezvous channel (bounded, capacity 0) tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/RendezvousChannelTests.cs

``TestRendezvousChannelTests`` also runs the shared ``ChannelTestBase`` suite. A failed
``TryRead(out int item)`` leaves ``item`` at ``default``; here the item is ``None``.
"""
from __future__ import annotations

import threading
from typing import override

import pytest

from flpit.channels import BoundedChannelFullMode, BoundedChannelOptions, Channel
from flpit.task import CancellationToken, CancellationTokenSource, Task, TaskContinuationOptions

from nettests.channels.channel_helpers import (
    THREE_BOOLS,
    assert_canceled_async,
    assert_synchronous_success,
    async_test,
)
from nettests.channels.channel_test_base import ChannelTestBase

DROP_MODES = [BoundedChannelFullMode.DROP_WRITE, BoundedChannelFullMode.DROP_OLDEST, BoundedChannelFullMode.DROP_NEWEST]


class TestRendezvousChannelTests(ChannelTestBase):
    buffers_items = False
    has_debugger_type_proxy = False

    @override
    def create_channel(self) -> Channel[int]:
        return Channel.create_bounded(0)

    @override
    def create_full_channel(self) -> Channel[int] | None:
        return self.create_channel()

    @async_test
    async def test_Count_AlwaysZero(self) -> None:
        c = self.create_channel()

        assert c.reader.can_count
        assert 0 == c.reader.count

        write1 = c.writer.write_async(1)
        write2 = c.writer.write_async(2)

        assert 0 == c.reader.count
        assert not write1.done()
        assert not write2.done()

        assert 1 == await c.reader.read_async()

        await write1
        assert 0 == c.reader.count
        assert not write2.done()

        assert 2 == await c.reader.read_async()

        await write2
        assert 0 == c.reader.count

    def test_TryWrite_TryRead_NoPairing_ReturnsFalse(self) -> None:
        c = self.create_channel()

        for _ in range(3):
            assert not c.writer.try_write(42)
            ok, item = c.reader.try_read()
            assert not ok
            assert item is None

    @pytest.mark.parametrize("mode", DROP_MODES)
    @async_test
    async def test_TryWrite_DropXx_DropsWrite(self, mode: BoundedChannelFullMode) -> None:
        dropped: int | None = None

        def item_dropped(item: int) -> None:
            nonlocal dropped
            dropped = item

        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(0, full_mode=mode), item_dropped)

        for i in range(42, 52):
            waiter = c.writer.wait_to_write_async()
            assert_synchronous_success(waiter)
            assert await waiter

            assert c.writer.try_write(i)
            assert i == dropped

            dropped = None
            assert_synchronous_success(c.writer.write_async(i))
            assert i == dropped

    @pytest.mark.parametrize("mode", DROP_MODES)
    @async_test
    async def test_TryWrite_DropXx_ReaderTakesPriority(self, mode: BoundedChannelFullMode) -> None:
        dropped: int | None = None

        def item_dropped(item: int) -> None:
            nonlocal dropped
            dropped = item

        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(0, full_mode=mode), item_dropped)

        for i in range(42, 52):
            reader = c.reader.read_async()
            assert c.writer.try_write(i)
            assert dropped is None
            assert i == await reader

            reader = c.reader.read_async()
            assert_synchronous_success(c.writer.write_async(i))
            assert dropped is None
            assert i == await reader

    @async_test
    async def test_DroppedDelegateNotCalledOnWaitMode_SyncWrites(self) -> None:
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            drop_delegate_called = True

        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(0, full_mode=BoundedChannelFullMode.WAIT), dropped)

        reader = c.reader.read_async()
        assert c.writer.try_write(42)
        assert 42 == await reader

        reader = c.reader.read_async()
        assert_synchronous_success(c.writer.write_async(43))
        assert 43 == await reader

        _ = c.writer.write_async(44)

        assert not drop_delegate_called

    @pytest.mark.parametrize("bounded_channel_full_mode", DROP_MODES)
    def test_DroppedDelegateIsNull_SyncAndAsyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] = Channel.create_bounded(
            BoundedChannelOptions(0, full_mode=bounded_channel_full_mode), item_dropped=None,
        )

        assert c.writer.try_write(1)
        assert_synchronous_success(c.writer.write_async(2))

        ok, item = c.reader.try_read()
        assert not ok
        assert item is None

    @pytest.mark.parametrize("bounded_channel_full_mode", DROP_MODES)
    def test_DroppedDelegateCalledAfterLockReleased_SyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] | None = None
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            if drop_delegate_called:
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

        c = Channel.create_bounded(BoundedChannelOptions(0, full_mode=bounded_channel_full_mode), dropped)

        assert c.writer.try_write(1)
        assert c.writer.try_write(2)

        assert drop_delegate_called

    @pytest.mark.parametrize("bounded_channel_full_mode", DROP_MODES)
    @async_test
    async def test_DroppedDelegateCalledAfterLockReleased_AsyncWrites(self, bounded_channel_full_mode: BoundedChannelFullMode) -> None:
        c: Channel[int] | None = None
        drop_delegate_called = False

        def dropped(_: int) -> None:
            nonlocal drop_delegate_called
            if drop_delegate_called:
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

        c = Channel.create_bounded(BoundedChannelOptions(0, full_mode=bounded_channel_full_mode), dropped)

        await c.writer.write_async(1)
        await c.writer.write_async(2)

        assert drop_delegate_called

    @async_test
    async def test_CancelPendingWrite_Reading_DataTransferredFromCorrectWriter(self) -> None:
        c = self.create_channel()

        cts = CancellationTokenSource()

        write1 = c.writer.write_async(42)
        write2 = c.writer.write_async(43, cts.token)
        write3 = c.writer.write_async(44)

        cts.cancel()

        assert 42 == await c.reader.read_async()
        assert 44 == await c.reader.read_async()

        await write1
        await assert_canceled_async(cts.token, write2)
        await write3

    @async_test
    async def test_WaitToWriteAsync_AfterRead_ReturnsTrue(self) -> None:
        c = self.create_channel()

        write1 = c.writer.wait_to_write_async()
        write2 = c.writer.wait_to_write_async()
        assert not write1.done()
        assert not write2.done()

        _ = c.reader.read_async()

        assert await write1
        assert await write2

        write3 = c.writer.wait_to_write_async()
        assert_synchronous_success(write3)
        assert await write3

    @pytest.mark.parametrize(("allow_synchronous_continuations", "cancelable", "wait_to_read_async"), THREE_BOOLS)
    def test_AllowSynchronousContinuations_Reading_ContinuationsInvokedAccordingToSetting(
            self, allow_synchronous_continuations: bool, cancelable: bool, wait_to_read_async: bool,
    ) -> None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(
            0, allow_synchronous_continuations=allow_synchronous_continuations,
        ))

        ct = CancellationTokenSource().token if cancelable else CancellationToken.none()

        expected_id = threading.get_ident()

        def continuation(_: Task[object]) -> None:
            assert allow_synchronous_continuations == (expected_id == threading.get_ident())

        t: Task[object] = c.reader.wait_to_read_async(ct) if wait_to_read_async else c.reader.read_async(ct)
        r = t.continue_with(continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)

        write = c.writer.write_async(42)
        if not wait_to_read_async:
            assert_synchronous_success(write)

        r.wait()  # avoid inlining the continuation
        r.result()

    @pytest.mark.parametrize("allow_synchronous_continuations", [False, True])
    def test_AllowSynchronousContinuations_CompletionTask_ContinuationsInvokedAccordingToSetting(
            self, allow_synchronous_continuations: bool,
    ) -> None:
        c: Channel[int] = Channel.create_bounded(BoundedChannelOptions(
            0, allow_synchronous_continuations=allow_synchronous_continuations,
        ))

        expected_id = threading.get_ident()

        def continuation(_: Task[None]) -> None:
            assert allow_synchronous_continuations == (expected_id == threading.get_ident())

        r = c.reader.completion.continue_with(continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)

        assert c.writer.try_complete()
        r.wait()  # avoid inlining the continuation
        r.result()
