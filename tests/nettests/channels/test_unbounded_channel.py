"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Unbounded channel tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/UnboundedChannelTests.cs

Every concrete class also runs the shared ``ChannelTestBase`` suite. ``[OuterLoop]`` tests and
``Stress_TryWrite_TryRead`` (3 million items) are marked ``stress`` and excluded by default.
"""
from __future__ import annotations

import threading
from typing import override

import pytest

from flpit.channels import Channel, UnboundedChannelOptions
from flpit.task import CancellationTokenSource, OperationCanceledError, Task, TaskContinuationOptions

from nettests.channels.channel_helpers import assert_synchronous_true, async_test, not_portable
from nettests.channels.channel_test_base import ChannelTestBase


class UnboundedChannelTests(ChannelTestBase):
    @override
    def create_channel(self) -> Channel[int]:
        return Channel.create_unbounded(UnboundedChannelOptions(
            single_reader=self.requires_single_reader,
            allow_synchronous_continuations=self.allow_synchronous_continuations,
        ))

    @override
    def create_full_channel(self) -> Channel[int] | None:
        return None

    def test_Count_IncrementsDecrementsAsExpected(self) -> None:
        c = self.create_channel()

        if self.requires_single_reader:
            assert not c.reader.can_count
            return

        assert c.reader.can_count

        items_to_add = 5
        for iteration in range(2):
            for i in range(items_to_add):
                assert i == c.reader.count
                assert c.writer.try_write(i)
                assert i + 1 == c.reader.count

            if iteration != 0:
                c.writer.complete()

            while True:
                ok, item = c.reader.try_read()
                if not ok:
                    break
                assert items_to_add - (item + 1) == c.reader.count

            assert 0 == c.reader.count

    @async_test
    async def test_Complete_BeforeEmpty_NoWaiters_TriggersCompletion(self) -> None:
        c = self.create_channel()
        assert c.writer.try_write(42)
        c.writer.complete()
        assert not c.reader.completion.done()
        assert 42 == await c.reader.read_async()
        await c.reader.completion

    def test_TryWrite_TryRead_Many(self) -> None:
        c = self.create_channel()

        num_items = 100000
        for i in range(num_items):
            assert c.writer.try_write(i)
        for i in range(num_items):
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

    def test_TryWrite_TryRead_OneAtATime(self) -> None:
        c = self.create_channel()

        for i in range(10):
            assert c.writer.try_write(i)
            ok, result = c.reader.try_read()
            assert ok
            assert i == result

    def test_WaitForReadAsync_DataAvailable_CompletesSynchronously(self) -> None:
        c = self.create_channel()
        assert c.writer.try_write(42)
        assert_synchronous_true(c.reader.wait_to_read_async())

    @pytest.mark.parametrize("read_mode", [0, 1])
    @async_test
    async def test_WriteMany_ThenComplete_SuccessfullyReadAll(self, read_mode: int) -> None:
        c = self.create_channel()
        for i in range(10):
            assert c.writer.try_write(i)

        c.writer.complete()
        assert not c.reader.completion.done()

        for i in range(10):
            assert not c.reader.completion.done()
            match read_mode:
                case 0:
                    ok, result = c.reader.try_read()
                    assert ok
                    assert i == result
                case 1:
                    assert i == await c.reader.read_async()

        await c.reader.completion

    def test_AllowSynchronousContinuations_WaitToReadAsync_ContinuationsInvokedAccordingToSetting(self) -> None:
        c = self.create_channel()

        expected_id = threading.get_ident()

        def continuation(_: Task[bool]) -> None:
            assert self.allow_synchronous_continuations == (expected_id == threading.get_ident())

        r = c.reader.wait_to_read_async().continue_with(
            continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY,
        )

        assert c.writer.write_async(42).status == Task.SUCCEEDED
        r.wait()  # avoid inlining the continuation
        r.result()

    def test_AllowSynchronousContinuations_CompletionTask_ContinuationsInvokedAccordingToSetting(self) -> None:
        c = self.create_channel()

        expected_id = threading.get_ident()

        def continuation(_: Task[None]) -> None:
            assert self.allow_synchronous_continuations == (expected_id == threading.get_ident())

        r = c.reader.completion.continue_with(continuation, options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY)

        assert c.writer.try_complete()
        r.wait()  # avoid inlining the continuation
        r.result()

    @pytest.mark.stress  # [OuterLoop]
    @async_test
    async def test_Completion_CompletesAfterConcurrentTryReadAndTryComplete(self) -> None:
        for _ in range(100_000):
            channel = self.create_channel()

            channel.writer.try_write(1)
            channel.writer.try_write(2)

            channel.reader.try_read()

            barrier = threading.Barrier(2)

            def read() -> None:
                barrier.wait()
                channel.reader.try_read()

            def complete() -> None:
                barrier.wait()
                channel.writer.try_complete()

            await Task.when_all(Task.run(read), Task.run(complete))

            channel.reader.try_read()

            completion_task = channel.reader.completion
            await completion_task.wait_async(10)


class SingleReaderUnboundedChannelTests(UnboundedChannelTests):
    requires_single_reader = True

    def test_ValidateInternalDebuggerAttributes(self) -> None:
        not_portable("debugger display attributes")

    @async_test
    async def test_MultipleWaiters_CancelsPreviousWaiter(self) -> None:
        c = self.create_channel()
        t1 = c.reader.wait_to_read_async()
        t2 = c.reader.wait_to_read_async()
        with pytest.raises(OperationCanceledError):
            await t1
        assert c.writer.try_write(42)
        assert await t2

    @async_test
    async def test_MultipleReaders_CancelsPreviousReader(self) -> None:
        c = self.create_channel()
        t1 = c.reader.read_async()
        t2 = c.reader.read_async()
        with pytest.raises(OperationCanceledError):
            await t1
        assert c.writer.try_write(42)
        assert 42 == await t2

    @async_test
    async def test_WaitToReadAsync_ReturnsFalse_WhenReadAsyncWasCanceledAndChannelCompleted(self) -> None:
        c = self.create_channel()

        with CancellationTokenSource() as cts:
            read_task = c.reader.read_async(cts.token)
            cts.cancel()
            with pytest.raises(OperationCanceledError):
                await read_task

            wait_task = c.reader.wait_to_read_async(None)

            c.writer.complete()

            assert not await wait_task

    @pytest.mark.stress  # 3M items: about 20 s per class in CPython
    def test_Stress_TryWrite_TryRead(self) -> None:
        num_items = 3000000
        c = self.create_channel()

        async def read() -> None:
            received = 0
            while await c.reader.wait_to_read_async():
                while True:
                    ok, i = c.reader.try_read()
                    if not ok:
                        break
                    assert received == i
                    received += 1

        def write() -> None:
            for i in range(num_items):
                assert c.writer.try_write(i)
            c.writer.complete()

        Task.wait_all(Task.run(read), Task.run(write))


class TestSyncMultiReaderUnboundedChannelTests(UnboundedChannelTests):
    allow_synchronous_continuations = True


class TestAsyncMultiReaderUnboundedChannelTests(UnboundedChannelTests):
    allow_synchronous_continuations = False


class TestSyncSingleReaderUnboundedChannelTests(SingleReaderUnboundedChannelTests):
    allow_synchronous_continuations = True


class TestAsyncSingleReaderUnboundedChannelTests(SingleReaderUnboundedChannelTests):
    allow_synchronous_continuations = False
