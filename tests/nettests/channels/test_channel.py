"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Channel factory, options and base-class tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/ChannelTests.cs

The custom readers and writers override only ``try_read`` / ``wait_to_read_async`` and
``try_write`` / ``wait_to_write_async``, so they run the ``ChannelReader`` / ``ChannelWriter``
defaults, as upstream. ``Random(42)`` is ``random.Random(42)`` (a different sequence; the tests
do not depend on it). ``AssertExtensions.Throws<T>("name", ...)`` checks the parameter name
in the message. Upstream's unused ``CanReadFalseStream`` helper is not ported.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Iterator
from typing import override

import pytest

from flpit.channels import (
    BoundedChannelOptions,
    Channel,
    ChannelClosedError,
    ChannelReader,
    ChannelWriter,
    TryResult,
    UnboundedChannelOptions,
)
from flpit.core.linq import ArgumentNullError, ArgumentOutOfRangeError, InvalidOperationError
from flpit.task import CancellationToken, Task, TaskCanceledError, TaskCompletionSource

from nettests.channels.channel_helpers import FormatError, async_test, canceled_token


class FieldAccessError(Exception):
    """.NET ``FieldAccessException``."""


class InvalidDataError(Exception):
    """.NET ``InvalidDataException``."""


class DriveNotFoundError(Exception):
    """.NET ``DriveNotFoundException``."""


def _from_result[R](value: R) -> Task[R]:
    """.NET ``Task.FromResult``."""
    source: TaskCompletionSource[R] = TaskCompletionSource()
    source.set_result(value)
    return source.task


def _true_after_delay() -> Task[bool]:
    return Task.delay(0.001).continue_with(lambda _: True)


class TestChannelTests:
    def test_ChannelOptimizations_Properties_Roundtrip(self) -> None:
        co = UnboundedChannelOptions()

        assert not co.single_reader
        assert not co.single_writer

        co.single_reader = True
        assert co.single_reader
        assert not co.single_writer
        co.single_reader = False
        assert not co.single_reader

        co.single_writer = True
        assert not co.single_reader
        assert co.single_writer
        co.single_writer = False
        assert not co.single_writer

        co.single_reader = True
        co.single_writer = True
        assert co.single_reader
        assert co.single_writer

        assert not co.allow_synchronous_continuations
        co.allow_synchronous_continuations = True
        assert co.allow_synchronous_continuations
        co.allow_synchronous_continuations = False
        assert not co.allow_synchronous_continuations

    def test_Create_ValidInputs_ProducesValidChannels(self) -> None:
        assert Channel.create_bounded(1) is not None
        assert Channel.create_bounded(BoundedChannelOptions(1)) is not None

        assert Channel.create_unbounded() is not None
        assert Channel.create_unbounded(UnboundedChannelOptions()) is not None

    def test_Create_NullOptions_ThrowsArgumentException(self) -> None:
        # Deviation: create_unbounded(None) is create_unbounded(), since None is the default
        # (.NET has a separate parameterless overload). Anything else that is not options throws.
        with pytest.raises(ArgumentNullError, match="'options'"):
            Channel.create_unbounded(object())  # type: ignore[arg-type]
        with pytest.raises(ArgumentNullError, match="'options'"):
            Channel.create_bounded(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("capacity", [-1, -2])
    def test_CreateBounded_InvalidBufferSizes_ThrowArgumentExceptions(self, capacity: int) -> None:
        with pytest.raises(ArgumentOutOfRangeError, match="'capacity'"):
            Channel.create_bounded(capacity)
        with pytest.raises(ArgumentOutOfRangeError, match="'capacity'"):
            BoundedChannelOptions(capacity)

    @pytest.mark.parametrize("mode", [-1, 4])
    def test_BoundedChannelOptions_InvalidModes_ThrowArgumentExceptions(self, mode: int) -> None:
        options = BoundedChannelOptions(1)
        with pytest.raises(ArgumentOutOfRangeError, match="'value'"):
            options.full_mode = mode  # type: ignore[assignment]

    @pytest.mark.parametrize("capacity", [-1, -2])
    def test_BoundedChannelOptions_InvalidCapacity_ThrowArgumentExceptions(self, capacity: int) -> None:
        options = BoundedChannelOptions(1)
        with pytest.raises(ArgumentOutOfRangeError, match="'value'"):
            options.capacity = capacity

    @pytest.mark.parametrize("buffered_capacity", [1])
    def test_CreateBounded_ValidBufferSizes_Success(self, buffered_capacity: int) -> None:
        assert Channel.create_bounded(buffered_capacity) is not None

    @async_test
    async def test_DefaultWriteAsync_UsesWaitToWriteAsyncAndTryWrite(self) -> None:
        c = TestChannelWriter[int](10)
        assert not c.try_complete()
        assert c.write_async(42, canceled_token()).status == Task.CANCELLED

        count = 0
        try:
            while True:
                count += 1
                await c.write_async(count - 1)
        except ChannelClosedError:
            pass
        assert 11 == count

    def test_DefaultCompletion_NeverCompletes(self) -> None:
        t = TestChannelReader[int]([]).completion
        assert not t.done()

    @async_test
    async def test_DefaultWriteAsync_CatchesTryWriteExceptions(self) -> None:
        w = TryWriteThrowingWriter[int]()
        t = w.write_async(42)
        assert t.status == Task.FAILED
        with pytest.raises(FormatError):
            await t

    @async_test
    async def test_DefaultReadAsync_CatchesTryWriteExceptions(self) -> None:
        r = TryReadThrowingReader[int]()
        t = r.read_async()
        assert t.status == Task.FAILED
        with pytest.raises(FieldAccessError):
            await t

    @async_test
    async def test_TestBaseClassReadAsync(self) -> None:
        channel = WrapperChannel[int](10)
        reader = channel.reader
        writer = channel.writer

        # 1- do it through synchronous TryRead()
        writer.try_write(50)
        assert 50 == await reader.read_async()

        # 2- do it through async
        read_task = reader.read_async()
        writer.try_write(100)
        assert 100 == await read_task

        # 3- use cancellation token
        ct = canceled_token()  # cancelled token
        with pytest.raises(TaskCanceledError):
            await reader.read_async(ct)

        # 4- throw during reading
        read_task = reader.read_async()
        assert isinstance(reader, WrapperChannelReader)
        reader.force_throwing = True
        writer.try_write(200)
        with pytest.raises(InvalidOperationError):
            await read_task

        # 5- close the channel while waiting reading
        reader.force_throwing = False
        assert 200 == await reader.read_async()
        read_task = reader.read_async()
        channel.writer.try_complete()
        with pytest.raises(ChannelClosedError):
            await read_task

    def test_TestBaseClassTryPeek(self) -> None:
        reader = TryPeekNoOverrideReader[int]()
        assert not reader.can_peek
        ok, item = reader.try_peek()
        assert not ok
        assert item is None


class WrapperChannelReader[T](ChannelReader[T]):
    """This reader doesn't override read_async to force using the base class read_async method."""

    def __init__(self, channel: Channel[T]) -> None:
        self._reader = channel.reader
        self.force_throwing = False

    @override
    def try_read(self) -> TryResult[T]:
        if self.force_throwing:
            raise InvalidOperationError()

        return self._reader.try_read()

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        return self._reader.wait_to_read_async(token)


class WrapperChannel[T](Channel[T]):
    def __init__(self, capacity: int) -> None:
        channel: Channel[T] = Channel.create_bounded(capacity)
        self.writer = channel.writer
        self.reader = WrapperChannelReader(channel)


class TestChannelWriter[T](ChannelWriter[T]):
    __test__ = False  # not a pytest class

    def __init__(self, max_count: int) -> None:
        self._rand = random.Random(42)
        self._max = max_count
        self._count = 0

    @override
    def try_write(self, item: T) -> bool:
        # succeed if we're under our limit, and add random failures
        if self._rand.randrange(2) != 0:
            return False
        self._count += 1
        return self._count - 1 < self._max

    @override
    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        if self._count >= self._max:
            return _from_result(False)
        if self._rand.randrange(2) == 0:
            return _true_after_delay()  # randomly introduce delays
        return _from_result(True)


class TestChannelReader[T](ChannelReader[T]):
    __test__ = False  # not a pytest class

    def __init__(self, enumerable: Iterable[T]) -> None:
        self._rand = random.Random(42)
        self._enumerator: Iterator[T] = iter(enumerable)
        self._closed = False

    @override
    def try_read(self) -> TryResult[T]:
        # Randomly fail to read
        if self._rand.randrange(2) == 0:
            return False, None

        # If the enumerable is closed, fail the read.
        try:
            item = next(self._enumerator)
        except StopIteration:
            self._closed = True
            return False, None

        # Otherwise return the next item.
        return True, item

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        if self._closed:
            return _from_result(False)
        if self._rand.randrange(2) == 0:
            return _true_after_delay()  # randomly introduce delays
        return _from_result(True)


class TryWriteThrowingWriter[T](ChannelWriter[T]):
    @override
    def try_write(self, item: T) -> bool:
        raise FormatError()

    @override
    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        raise InvalidDataError()


class TryReadThrowingReader[T](ChannelReader[T]):
    @override
    def try_read(self) -> TryResult[T]:
        raise FieldAccessError()

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        raise DriveNotFoundError()


class TryPeekNoOverrideReader[T](ChannelReader[T]):
    @override
    def try_read(self) -> TryResult[T]:
        return False, None

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        return _from_result(False)
