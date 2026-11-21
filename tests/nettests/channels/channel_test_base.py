"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

The shared channel suite, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/ChannelTestBase.cs

``ChannelTestBase`` is abstract (pytest does not collect it); every channel kind runs it through
a ``Test<UpstreamClass>`` subclass that overrides ``create_channel`` / ``create_full_channel``
and the flags, as the upstream subclasses override ``CreateChannel<T>`` and the virtuals.
Upstream tests keep their names with a ``test_`` prefix. See ``channel_helpers`` for the mapping.

Skipped (each upstream theory collapsed into one skipped test, since no case of it can run):

* ``*_MultipleContinuations_Throws``, ``*_AwaitThenGetResult_Throws``, ``ValueTask_*``: they
  check the single-use rules of an ``IValueTaskSource``-backed ``ValueTask``. flpit returns a
  ``Task``: awaitable any number of times, ``result()`` blocks instead of throwing.
* ``Reader_ContinuesOn*IfDesired``: Python has no ``SynchronizationContext`` / ``TaskScheduler``
  and no ``OnCompleted`` / ``UnsafeOnCompleted`` awaiter callbacks to flow them through.
* ``ValidateDebuggerAttributes``: debugger display attributes do not exist in Python.
* ``Cast_MatchesInOut``: the implicit ``Channel<T>`` to reader/writer conversion operators have no
  Python counterpart (use ``channel.reader`` / ``channel.writer``).
"""
from __future__ import annotations

import pytest

from flpit.channels import Channel, ChannelClosedError
from flpit.core.linq import InvalidOperationError, NotSupportedError
from flpit.task import CancellationTokenSource, OperationCanceledError, Task

from nettests.channels.channel_helpers import (
    AsyncEnumeratorSteps,
    Counter,
    FormatError,
    assert_canceled_async,
    assert_synchronous_success,
    assert_synchronous_true,
    async_test,
    canceled_token,
    not_portable,
)

_VALUE_TASK = "single-use IValueTaskSource ValueTask semantics (flpit returns a multi-await Task)"
_CONTEXTS = "SynchronizationContext / TaskScheduler and awaiter OnCompleted callbacks"


class ChannelTestBase:
    """Abstract: subclasses set the channel factories and the flags."""

    allow_synchronous_continuations = False
    requires_single_reader = False
    requires_single_writer = False
    buffers_items = True
    has_debugger_type_proxy = True

    def create_channel(self) -> Channel[int]:
        raise NotImplementedError

    def create_full_channel(self) -> Channel[int] | None:
        raise NotImplementedError

    def test_ValidateDebuggerAttributes(self) -> None:
        not_portable("debugger display attributes")

    def test_Cast_MatchesInOut(self) -> None:
        not_portable("implicit Channel<T> -> ChannelReader<T> / ChannelWriter<T> conversions")

    def test_Completion_Idempotent(self) -> None:
        c = self.create_channel()

        completion = c.reader.completion
        assert completion.status == Task.PENDING

        assert completion is c.reader.completion
        c.writer.complete()
        assert completion is c.reader.completion

        assert completion.status == Task.SUCCEEDED

    @async_test
    async def test_Complete_AfterEmpty_NoWaiters_TriggersCompletion(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        await c.reader.completion

    @async_test
    async def test_Complete_AfterEmpty_WaitingReader_TriggersCompletion(self) -> None:
        c = self.create_channel()
        r = c.reader.read_async()
        c.writer.complete()
        await c.reader.completion
        with pytest.raises(InvalidOperationError):
            await r

    @async_test
    async def test_Complete_BeforeEmpty_WaitingReaders_TriggersCompletion(self) -> None:
        c = self.create_channel()
        read = c.reader.read_async()
        c.writer.complete()
        await c.reader.completion
        with pytest.raises(InvalidOperationError):
            await read

    def test_Complete_Twice_ThrowsInvalidOperationException(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        with pytest.raises(InvalidOperationError):
            c.writer.complete()

    def test_TryComplete_Twice_ReturnsTrueThenFalse(self) -> None:
        c = self.create_channel()
        assert c.writer.try_complete()
        assert not c.writer.try_complete()
        assert not c.writer.try_complete()

    @async_test
    async def test_TryComplete_ErrorsPropagate(self) -> None:
        # Success
        c = self.create_channel()
        assert c.writer.try_complete()
        await c.reader.completion

        # Error
        c = self.create_channel()
        assert c.writer.try_complete(FormatError())
        with pytest.raises(FormatError):
            await c.reader.completion

        # Canceled
        c = self.create_channel()
        cts = CancellationTokenSource()
        cts.cancel()
        assert c.writer.try_complete(OperationCanceledError(token=cts.token))
        await assert_canceled_async(cts.token, c.reader.completion)

    def test_Count_ThrowsIfUnsupported(self) -> None:
        c = self.create_channel()
        if not c.reader.can_count:
            with pytest.raises(NotSupportedError):
                _ = c.reader.count
        else:
            assert 0 <= c.reader.count <= 2**31 - 1

    def test_SingleProducerConsumer_ConcurrentReadWrite_Success(self) -> None:
        c = self.create_channel()

        num_items = 100000

        async def write() -> None:
            for i in range(num_items):
                await c.writer.write_async(i)

        async def read() -> None:
            for i in range(num_items):
                assert i == await c.reader.read_async()

        Task.wait_all(Task.run(write), Task.run(read))

    def test_SingleProducerConsumer_PingPong_Success(self) -> None:
        c1 = self.create_channel()
        c2 = self.create_channel()

        num_items = 100000

        async def ping() -> None:
            for i in range(num_items):
                assert i == await c1.reader.read_async()
                await c2.writer.write_async(i)

        async def pong() -> None:
            for i in range(num_items):
                await c1.writer.write_async(i)
                assert i == await c2.reader.read_async()

        Task.wait_all(Task.run(ping), Task.run(pong))

    @pytest.mark.parametrize(("num_readers", "num_writers"), [(1, 1), (1, 10), (10, 1), (10, 10)])
    def test_ManyProducerConsumer_ConcurrentReadWrite_Success(self, num_readers: int, num_writers: int) -> None:
        if self.requires_single_reader and num_readers > 1:
            return

        if self.requires_single_writer and num_writers > 1:
            return

        c = self.create_channel()

        num_items = 10000

        read_total = Counter()
        remaining_writers = Counter(num_writers)
        remaining_items = Counter(num_items)

        async def read() -> None:
            while await c.reader.wait_to_read_async():
                while True:
                    ok, value = c.reader.try_read()
                    if not ok:
                        break
                    read_total.add(value)

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

    def test_WaitToReadAsync_DataAvailableBefore_CompletesSynchronously(self) -> None:
        c = self.create_channel()
        c.writer.write_async(42)
        read = c.reader.wait_to_read_async()
        assert read.status == Task.SUCCEEDED

    def test_WaitToReadAsync_DataAvailableAfter_CompletesAsynchronously(self) -> None:
        c = self.create_channel()
        read = c.reader.wait_to_read_async()
        assert not read.done()
        c.writer.write_async(42)
        assert read.result()

    def test_WaitToReadAsync_AfterComplete_SynchronouslyCompletes(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        read = c.reader.wait_to_read_async()
        assert read.status == Task.SUCCEEDED
        assert not read.result()

    def test_WaitToReadAsync_BeforeComplete_AsynchronouslyCompletes(self) -> None:
        c = self.create_channel()
        read = c.reader.wait_to_read_async()
        assert not read.done()
        c.writer.complete()
        assert not read.result()

    def test_WaitToWriteAsync_AfterComplete_SynchronouslyCompletes(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        write = c.writer.wait_to_write_async()
        assert write.status == Task.SUCCEEDED
        assert not write.result()

    def test_WaitToWriteAsync_EmptyChannel_SynchronouslyCompletes(self) -> None:
        if not self.buffers_items:
            return

        c = self.create_channel()
        write = c.writer.wait_to_write_async()
        assert write.status == Task.SUCCEEDED
        assert write.result()

    @async_test
    async def test_WaitToWriteAsync_ManyConcurrent_SatisfiedByReaders(self) -> None:
        if self.requires_single_reader or self.requires_single_writer:
            return

        c = self.create_channel()

        writers = [c.writer.wait_to_write_async() for _ in range(100)]
        _readers = [c.reader.read_async() for _ in range(100)]

        await Task.when_all(writers)

    def test_WaitToWriteAsync_BlockedReader_ReturnsTrue(self) -> None:
        c = self.create_channel()
        _reader = c.reader.read_async()
        assert_synchronous_success(c.writer.wait_to_write_async())

    @async_test
    async def test_TryRead_DataAvailable_Success(self) -> None:
        c = self.create_channel()
        write = c.writer.write_async(42)
        ok, result = c.reader.try_read()
        assert ok
        assert result == 42
        await write

    def test_TryRead_AfterComplete_ReturnsFalse(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        ok, _ = c.reader.try_read()
        assert not ok

    @async_test
    async def test_TryPeek_SucceedsWhenDataAvailable(self) -> None:
        c = self.create_channel()

        assert c.reader.can_peek  # all built-in readers support peeking

        for _ in range(3):
            # Write a value
            write = c.writer.write_async(42)

            # Can peek at the written value
            ok, peeked_result = c.reader.try_peek()
            assert ok
            assert peeked_result == 42

            # Can still read out that value
            ok, read_result = c.reader.try_read()
            assert ok
            assert read_result == 42
            await write

            # Peeking no longer finds it
            ok, no_result = c.reader.try_peek()
            assert not ok
            assert no_result is None

        if not self.buffers_items:
            return

        # Write another value
        assert c.writer.write_async(84).status == Task.SUCCEEDED

        # Mark as completed
        c.writer.complete()

        # Can peek at the written value
        ok, last_peeked_result = c.reader.try_peek()
        assert ok
        assert last_peeked_result == 84

        # Can still read out that value
        ok, last_read_result = c.reader.try_read()
        assert ok
        assert last_read_result == 84

        # Peeking no longer finds it
        ok, last_no_result = c.reader.try_peek()
        assert not ok
        assert last_no_result is None

    def test_TryWrite_AfterComplete_ReturnsFalse(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        assert not c.writer.try_write(42)

    @async_test
    async def test_WriteAsync_AfterComplete_ThrowsException(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        with pytest.raises(InvalidOperationError):
            await c.writer.write_async(42)

    @async_test
    async def test_Complete_WithException_PropagatesToCompletion(self) -> None:
        c = self.create_channel()
        exc = FormatError()
        c.writer.complete(exc)
        with pytest.raises(FormatError) as raised:
            await c.reader.completion
        assert raised.value is exc

    @async_test
    async def test_Complete_WithCancellationException_PropagatesToCompletion(self) -> None:
        c = self.create_channel()
        cts = CancellationTokenSource()
        cts.cancel()

        exc: BaseException | None = None
        try:
            cts.token.throw_if_cancellation_requested()
        except OperationCanceledError as e:
            exc = e

        c.writer.complete(exc)
        await assert_canceled_async(cts.token, c.reader.completion)

    @async_test
    async def test_Complete_WithException_PropagatesToExistingWriter(self) -> None:
        c = self.create_full_channel()
        if c is not None:
            write = c.writer.write_async(42)
            exc = FormatError()
            c.writer.complete(exc)
            with pytest.raises(ChannelClosedError) as raised:
                await write
            assert raised.value.inner_exception is exc

    @async_test
    async def test_Complete_WithException_PropagatesToNewWriter(self) -> None:
        c = self.create_channel()
        exc = FormatError()
        c.writer.complete(exc)
        write = c.writer.write_async(42)
        with pytest.raises(ChannelClosedError) as raised:
            await write
        assert raised.value.inner_exception is exc

    @async_test
    async def test_Complete_WithException_PropagatesToExistingWaitingReader(self) -> None:
        c = self.create_channel()
        read = c.reader.wait_to_read_async()
        exc = FormatError()
        c.writer.complete(exc)
        with pytest.raises(FormatError):
            await read

    @async_test
    async def test_Complete_WithException_PropagatesToNewWaitingReader(self) -> None:
        c = self.create_channel()
        exc = FormatError()
        c.writer.complete(exc)
        read = c.reader.wait_to_read_async()
        with pytest.raises(FormatError):
            await read

    @async_test
    async def test_Complete_WithException_PropagatesToNewWaitingWriter(self) -> None:
        c = self.create_channel()
        exc = FormatError()
        c.writer.complete(exc)
        write = c.writer.wait_to_write_async()
        with pytest.raises(FormatError):
            await write

    def test_ManyWriteAsync_ThenManyTryRead_Success(self) -> None:
        if self.requires_single_reader or self.requires_single_writer:
            return

        c = self.create_channel()

        num_items = 2000

        writers = [c.writer.write_async(i) for i in range(num_items)]

        for i in range(num_items):
            ok, result = c.reader.try_read()
            assert ok
            assert result == i

        assert all(w.done() for w in writers)

    def test_Precancellation_Writing_ReturnsImmediately(self) -> None:
        c = self.create_channel()

        write_task = c.writer.write_async(42, canceled_token())
        assert write_task.cancelled()

        wait_task = c.writer.wait_to_write_async(canceled_token())
        assert wait_task.cancelled()

    def test_Write_WaitToReadAsync_CompletesSynchronously(self) -> None:
        c = self.create_channel()
        c.writer.write_async(42)
        assert_synchronous_true(c.reader.wait_to_read_async())

    @pytest.mark.parametrize("data_available", [False, True])
    @async_test
    async def test_Precancellation_WaitToReadAsync_ReturnsImmediately(self, data_available: bool) -> None:
        c = self.create_channel()

        write = Task.completed_task
        if data_available:
            write = c.writer.write_async(42)

        wait_task = c.reader.wait_to_read_async(canceled_token())
        assert wait_task.cancelled()

        if self.buffers_items:
            await write

    @pytest.mark.parametrize("cancelable", [False, True])
    @async_test
    async def test_WaitToReadAsync_DataWritten_CompletesSuccessfully(self, cancelable: bool) -> None:
        c = self.create_channel()
        token = CancellationTokenSource().token if cancelable else None

        read = c.reader.wait_to_read_async(token)
        assert not read.done()

        _write = c.writer.write_async(42, token)
        assert await read

    @async_test
    async def test_WaitToReadAsync_NoDataWritten_Canceled_CompletesAsCanceled(self) -> None:
        c = self.create_channel()
        cts = CancellationTokenSource()

        read = c.reader.wait_to_read_async(cts.token)
        assert not read.done()
        cts.cancel()
        with pytest.raises(OperationCanceledError):
            await read

    @async_test
    async def test_ReadAsync_ThenWriteAsync_Succeeds(self) -> None:
        c = self.create_channel()

        r = c.reader.read_async()
        assert not r.done()

        w = c.writer.write_async(42)
        assert_synchronous_success(w)

        assert 42 == await r

    @async_test
    async def test_WriteAsync_ReadAsync_Succeeds(self) -> None:
        c = self.create_channel()

        w = c.writer.write_async(42)
        r = c.reader.read_async()

        await Task.when_all(w, r)
        assert 42 == await r

    @pytest.mark.parametrize("data_available", [False, True])
    def test_Precancellation_ReadAsync_ReturnsImmediately(self, data_available: bool) -> None:
        c = self.create_channel()
        if data_available:
            c.writer.write_async(42)

        read_task = c.reader.read_async(canceled_token())
        assert read_task.cancelled()

    @async_test
    async def test_ReadAsync_Canceled_CanceledAsynchronously(self) -> None:
        c = self.create_channel()
        cts = CancellationTokenSource()

        r = c.reader.read_async(cts.token)
        assert not r.done()

        cts.cancel()

        await assert_canceled_async(cts.token, r)

        vt = c.writer.write_async(42)
        assert 42 == await c.reader.read_async()
        await vt

    @async_test
    async def test_ReadAsync_WriteAsync_ManyConcurrentReaders_SerializedWriters_Success(self) -> None:
        if self.requires_single_reader:
            return

        c = self.create_channel()
        items = 100

        readers = [c.reader.read_async() for _ in range(items)]
        for i in range(items):
            await c.writer.write_async(i)
        assert (items * (items - 1)) // 2 == sum(await Task.when_all(readers))

    @async_test
    async def test_ReadAsync_TryWrite_ManyConcurrentReaders_SerializedWriters_Success(self) -> None:
        if self.requires_single_reader:
            return

        c = self.create_channel()
        items = 100

        readers = [c.reader.read_async() for _ in range(items)]
        remaining_readers = list(readers)
        for i in range(items):
            assert c.writer.try_write(i), f"Failed to write at {i}"
            r = await Task.when_any(remaining_readers)
            await r
            remaining_readers.remove(r)

        assert (items * (items - 1)) // 2 == sum(await Task.when_all(readers))

    @async_test
    async def test_ReadAsync_AlreadyCompleted_Throws(self) -> None:
        c = self.create_channel()
        c.writer.complete()
        with pytest.raises(ChannelClosedError):
            await c.reader.read_async()

    @async_test
    async def test_ReadAsync_SubsequentlyCompleted_Throws(self) -> None:
        c = self.create_channel()
        r = c.reader.read_async()
        assert not r.done()
        c.writer.complete()
        with pytest.raises(ChannelClosedError):
            await r

    @async_test
    async def test_ReadAsync_AfterFaultedChannel_Throws(self) -> None:
        c = self.create_channel()

        e = FormatError()
        c.writer.complete(e)
        assert c.reader.completion.status == Task.FAILED

        with pytest.raises(ChannelClosedError) as raised:
            await c.reader.read_async()
        assert raised.value.inner_exception is e

    @async_test
    async def test_ReadAsync_AfterCanceledChannel_Throws(self) -> None:
        c = self.create_channel()

        e = OperationCanceledError()
        c.writer.complete(e)
        assert c.reader.completion.cancelled()

        with pytest.raises(OperationCanceledError):
            await c.reader.read_async()

    @async_test
    async def test_ReadAsync_Canceled_WriteAsyncCompletesNextReader(self) -> None:
        c = self.create_channel()

        for _ in range(5):
            cts = CancellationTokenSource()
            r = c.reader.read_async(cts.token)
            cts.cancel()
            await assert_canceled_async(cts.token, r)

        for i in range(7):
            r = c.reader.read_async()
            await c.writer.write_async(i)
            assert i == await r

    @async_test
    async def test_ReadAsync_ConsecutiveReadsSucceed(self) -> None:
        c = self.create_channel()
        for i in range(5):
            r = c.reader.read_async()
            await c.writer.write_async(i)
            assert i == await r

    def test_ReadAllAsync_NotIdempotent(self) -> None:
        c = self.create_channel()
        e = c.reader.read_all_async()
        assert e is not None
        assert e is not c.reader.read_all_async()

    @pytest.mark.parametrize("complete_while_pending", [False, True])
    @async_test
    async def test_ReadAllAsync_UseMoveNextAsyncAfterCompleted_ReturnsFalse(self, complete_while_pending: bool) -> None:
        c = self.create_channel()
        e = AsyncEnumeratorSteps(c.reader.read_all_async().get_async_enumerator())

        if complete_while_pending:
            c.writer.complete()
            vt = e.move_next_async()
            assert vt.is_completed_successfully
            assert not vt.result
        else:
            vt = e.move_next_async()
            assert not vt.is_completed
            c.writer.complete()
            assert not await vt

        vt = e.move_next_async()
        assert vt.is_completed_successfully
        assert not vt.result

    @async_test
    async def test_ReadAllAsync_AvailableDataCompletesSynchronously(self) -> None:
        c = self.create_channel()

        e = AsyncEnumeratorSteps(c.reader.read_all_async().get_async_enumerator())
        try:
            for i in range(100, 110):
                write = c.writer.write_async(i)
                vt = e.move_next_async()
                assert vt.is_completed_successfully
                assert vt.result
                assert i == e.current
                await write
        finally:
            dvt = e.dispose_async()
            assert dvt.is_completed_successfully
            _ = dvt.result

    @async_test
    async def test_ReadAllAsync_UnavailableDataCompletesAsynchronously(self) -> None:
        c = self.create_channel()

        e = AsyncEnumeratorSteps(c.reader.read_all_async().get_async_enumerator())
        try:
            for i in range(100, 110):
                vt = e.move_next_async()
                assert not vt.is_completed

                async def produce(item: int = i) -> None:
                    await c.writer.write_async(item)

                producer = Task.run(produce)
                assert await vt
                await producer
                assert i == e.current
        finally:
            dvt = e.dispose_async()
            assert dvt.is_completed_successfully
            _ = dvt.result

    @pytest.mark.parametrize("items", [0, 1, 128])
    @async_test
    async def test_ReadAllAsync_ProducerConsumer_ConsumesAllData(self, items: int) -> None:
        c = self.create_channel()

        produced_total = 0
        consumed_total = 0

        async def produce() -> None:
            nonlocal produced_total
            for i in range(items):
                await c.writer.write_async(i)
                produced_total += i
            c.writer.complete()

        async def consume() -> None:
            nonlocal consumed_total
            e = c.reader.read_all_async().get_async_enumerator()
            try:
                async for item in e:
                    consumed_total += item
            finally:
                await e.aclose()

        await Task.when_all(Task.run(produce), Task.run(consume))

        assert produced_total == consumed_total

    @async_test
    async def test_ReadAllAsync_MultipleEnumerationsToEnd(self) -> None:
        c = self.create_channel()

        write = c.writer.write_async(42)

        enumerable = c.reader.read_all_async()
        e = AsyncEnumeratorSteps(enumerable.get_async_enumerator())

        assert await e.move_next_async()
        assert 42 == e.current

        await write
        c.writer.complete()

        assert not await e.move_next_async()
        assert not await e.move_next_async()

        await e.dispose_async()

        e = AsyncEnumeratorSteps(enumerable.get_async_enumerator())
        # Upstream: Assert.Same(enumerable, e). C# iterator objects reuse themselves as their
        # first enumerator; a Python async generator is always a new object. Not portable.

        assert not await e.move_next_async()
        assert not await e.move_next_async()

    @pytest.mark.parametrize(("same_enumerable", "dispose"), [(False, False), (False, True), (True, False), (True, True)])
    @async_test
    async def test_ReadAllAsync_MultipleSingleElementEnumerations_AllItemsEnumerated(
            self, same_enumerable: bool, dispose: bool,
    ) -> None:
        c = self.create_channel()
        enumerable = c.reader.read_all_async()

        for i in range(10):
            write = c.writer.write_async(i)
            e = AsyncEnumeratorSteps((enumerable if same_enumerable else c.reader.read_all_async()).get_async_enumerator())
            vt = e.move_next_async()
            await write
            assert vt.is_completed_successfully
            assert vt.result
            assert i == e.current
            if dispose:
                dvt = e.dispose_async()
                assert dvt.is_completed_successfully
                _ = dvt.result

    @pytest.mark.parametrize("same_enumerable", [False, True])
    @async_test
    async def test_ReadAllAsync_DualConcurrentEnumeration_AllItemsEnumerated(self, same_enumerable: bool) -> None:
        if self.requires_single_reader:
            return

        c = self.create_channel()

        enumerable = c.reader.read_all_async()

        e1 = AsyncEnumeratorSteps(enumerable.get_async_enumerator())
        e2 = AsyncEnumeratorSteps((enumerable if same_enumerable else c.reader.read_all_async()).get_async_enumerator())
        assert e1.enumerator is not e2.enumerator

        producer_total = 0
        consumer_total = 0
        for i in range(10):
            vt1 = e1.move_next_async()
            vt2 = e2.move_next_async()

            await c.writer.write_async(i)
            producer_total += i
            await c.writer.write_async(i * 2)
            producer_total += i * 2

            assert await vt1
            assert await vt2
            consumer_total += e1.current
            consumer_total += e2.current

        vt1 = e1.move_next_async()
        vt2 = e2.move_next_async()
        c.writer.complete()
        assert not await vt1
        assert not await vt2

        assert producer_total == consumer_total

    @pytest.mark.parametrize("data_available", [False, True])
    @async_test
    async def test_ReadAllAsync_CanceledBeforeMoveNextAsync_Throws(self, data_available: bool) -> None:
        c = self.create_channel()

        if data_available:
            _ = c.writer.write_async(42)

        cts = CancellationTokenSource()
        cts.cancel()

        e = AsyncEnumeratorSteps(c.reader.read_all_async(cts.token).get_async_enumerator())
        vt = e.move_next_async()
        assert vt.is_completed
        assert not vt.is_completed_successfully
        with pytest.raises(OperationCanceledError) as raised:
            await vt
        assert raised.value.token is cts.token

    @async_test
    async def test_ReadAllAsync_CanceledAfterMoveNextAsync_Throws(self) -> None:
        c = self.create_channel()
        cts = CancellationTokenSource()

        e = AsyncEnumeratorSteps(c.reader.read_all_async(cts.token).get_async_enumerator())
        vt = e.move_next_async()
        assert not vt.is_completed

        cts.cancel()
        with pytest.raises(OperationCanceledError) as raised:
            await vt
        assert raised.value.token is cts.token

        vt = e.move_next_async()
        assert vt.is_completed_successfully
        assert not vt.result

    @async_test
    async def test_WaitToReadAsync_ConsecutiveReadsSucceed(self) -> None:
        c = self.create_channel()
        for i in range(5):
            r = c.reader.wait_to_read_async()
            write = c.writer.write_async(i)
            assert await r
            ok, item = c.reader.try_read()
            assert ok
            assert i == item
            await write

    def test_WaitToReadAsync_MultipleContinuations_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_ReadAsync_MultipleContinuations_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_WaitToReadAsync_AwaitThenGetResult_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_ReadAsync_AwaitThenGetResult_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_WaitToWriteAsync_AwaitThenGetResult_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_WriteAsync_AwaitThenGetResult_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_WaitToWriteAsync_MultipleContinuations_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_WriteAsync_MultipleContinuations_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_Reader_ContinuesOnCurrentSynchronizationContextIfDesired(self) -> None:
        not_portable(_CONTEXTS)

    def test_Reader_ContinuesOnCurrentTaskSchedulerIfDesired(self) -> None:
        not_portable(_CONTEXTS)

    def test_ValueTask_GetResultWhenNotCompleted_Throws(self) -> None:
        not_portable(_VALUE_TASK)

    def test_ValueTask_MultipleContinuations_Throws(self) -> None:
        not_portable(_VALUE_TASK)
