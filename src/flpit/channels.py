"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Channels: thread-safe producer/consumer queues with backpressure (.NET ``System.Threading.Channels``).

Ported from
https://github.com/dotnet/runtime/tree/main/src/libraries/System.Threading.Channels/src/System/Threading/Channels

A ``Channel[T]`` has a ``writer`` that producers write to and a ``reader`` that consumers read
from, from any thread and from flpit tasks alike::

    channel: Channel[int] = Channel.create_bounded(100)   # at most 100 items buffered

    async def produce():
        for i in range(1000):
            await channel.writer.write_async(i)            # waits while the channel is full
        channel.writer.complete()

    async def consume():
        async for item in channel.reader.read_all_async(): # ends when the writer completes
            ...

Asynchronous operations return ``flpit.task.Task`` objects (.NET's ``ValueTask``), take an
optional ``token`` and are canceled through it. ``read_all_async()`` returns an ``AsyncFlpIt``,
so the async LINQ operators work on a channel directly.

Kinds (all created through ``Channel``):

* ``create_unbounded()``: never full; ``single_reader=True`` selects the single-consumer variant.
* ``create_bounded(capacity)``: holds at most ``capacity`` items; ``full_mode`` decides what a
  write to a full channel does: wait (``WAIT``), or drop an item (``DROP_NEWEST``, ``DROP_OLDEST``,
  ``DROP_WRITE``) and report it to ``item_dropped``. A capacity of 0 creates a rendezvous channel:
  every write waits for a reader to take the item.
* ``create_unbounded_prioritized()``: never full; reads return the smallest item first.

Unless ``allow_synchronous_continuations=True``, code waiting on a channel operation never runs
inside the call that completed it (a write, a read, ``complete()``, ``cancel()``).

``try_read()`` / ``try_peek()`` return ``(True, item)`` or ``(False, None)`` (.NET ``out`` parameters).
"""
from __future__ import annotations

import heapq
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from enum import Enum
from functools import cmp_to_key
from itertools import count
from typing import Any, Literal, cast, override

from flpit.core.async_linq import AsyncFlpIt, async_flpit
from flpit.core.linq import ArgumentNullError, ArgumentOutOfRangeError, InvalidOperationError, NotSupportedError
from flpit.task import (
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskCanceledError,
    TaskCompletionSource,
)

__all__ = [
    "BoundedChannelFullMode",
    "BoundedChannelOptions",
    "Channel",
    "ChannelClosedError",
    "ChannelOptions",
    "ChannelReader",
    "ChannelWriter",
    "TryResult",
    "UnboundedChannelOptions",
    "UnboundedPrioritizedChannelOptions",
]

type TryResult[T] = tuple[Literal[True], T] | tuple[Literal[False], None]

_NONE_TOKEN = CancellationToken.none()
_FAILED_TRY: tuple[Literal[False], None] = (False, None)


# =============================================================================
# Errors and options
# =============================================================================

class ChannelClosedError(InvalidOperationError):
    """The channel has been completed (.NET ``ChannelClosedException``).

    ``ChannelClosedError()``, ``ChannelClosedError(message)``, ``ChannelClosedError(inner)`` and
    ``ChannelClosedError(message, inner)`` mirror the .NET constructors; ``inner_exception``
    (also ``__cause__``) is the error the writer completed the channel with.
    """

    DEFAULT_MESSAGE = "The channel has been closed."

    def __init__(
            self,
            message_or_inner: str | BaseException | None = None,
            inner_exception: BaseException | None = None,
    ) -> None:
        message = self.DEFAULT_MESSAGE
        if isinstance(message_or_inner, BaseException):
            inner_exception = message_or_inner
        elif message_or_inner is not None:
            message = message_or_inner
        super().__init__(message)
        self.inner_exception = inner_exception
        if inner_exception is not None:
            self.__cause__ = inner_exception

    def __reduce__(self) -> tuple[Any, ...]:
        # Keep the inner exception when pickled (.NET: serializable exceptions).
        return type(self), (str(self), self.inner_exception)


class BoundedChannelFullMode(Enum):
    """What a write to a full bounded channel does (.NET ``BoundedChannelFullMode``)."""

    WAIT = 0
    """Wait for space (``write_async``), or fail (``try_write`` returns False)."""
    DROP_NEWEST = 1
    """Remove the newest buffered item to make room."""
    DROP_OLDEST = 2
    """Remove the oldest buffered item to make room."""
    DROP_WRITE = 3
    """Drop the item being written."""


class ChannelOptions:
    """Options shared by every channel kind (.NET ``ChannelOptions``).

    ``single_writer`` / ``single_reader`` promise that at most one writer / reader uses the
    channel at a time, which lets it pick a cheaper implementation.
    ``allow_synchronous_continuations`` lets code waiting on an operation run inside the call
    that completed it.
    """

    def __init__(
            self,
            *,
            single_writer: bool = False,
            single_reader: bool = False,
            allow_synchronous_continuations: bool = False,
    ) -> None:
        self.single_writer = single_writer
        self.single_reader = single_reader
        self.allow_synchronous_continuations = allow_synchronous_continuations


def _out_of_range(argument: str) -> ArgumentOutOfRangeError:
    return ArgumentOutOfRangeError(argument, "Specified argument was out of the range of valid values.")


class BoundedChannelOptions(ChannelOptions):
    """Options for ``Channel.create_bounded`` (.NET ``BoundedChannelOptions``)."""

    def __init__(
            self,
            capacity: int,
            *,
            full_mode: BoundedChannelFullMode = BoundedChannelFullMode.WAIT,
            single_writer: bool = False,
            single_reader: bool = False,
            allow_synchronous_continuations: bool = False,
    ) -> None:
        super().__init__(
            single_writer=single_writer,
            single_reader=single_reader,
            allow_synchronous_continuations=allow_synchronous_continuations,
        )
        if capacity < 0:
            raise _out_of_range("capacity")
        self._capacity = capacity
        self._full_mode = BoundedChannelFullMode.WAIT
        self.full_mode = full_mode

    @property
    def capacity(self) -> int:
        return self._capacity

    @capacity.setter
    def capacity(self, value: int) -> None:
        if value < 0:
            raise _out_of_range("value")
        self._capacity = value

    @property
    def full_mode(self) -> BoundedChannelFullMode:
        return self._full_mode

    @full_mode.setter
    def full_mode(self, value: BoundedChannelFullMode) -> None:
        if not isinstance(value, BoundedChannelFullMode):
            raise _out_of_range("value")
        self._full_mode = value


class UnboundedChannelOptions(ChannelOptions):
    """Options for ``Channel.create_unbounded`` (.NET ``UnboundedChannelOptions``)."""


class UnboundedPrioritizedChannelOptions[T](ChannelOptions):
    """Options for ``Channel.create_unbounded_prioritized`` (.NET ``UnboundedPrioritizedChannelOptions<T>``).

    ``comparer(a, b)`` returns a negative number, zero or a positive number (.NET ``IComparer<T>``);
    reads return the smallest item first. Without one, items are compared with ``<``.
    """

    def __init__(
            self,
            *,
            comparer: Callable[[T, T], int] | None = None,
            single_writer: bool = False,
            single_reader: bool = False,
            allow_synchronous_continuations: bool = False,
    ) -> None:
        super().__init__(
            single_writer=single_writer,
            single_reader=single_reader,
            allow_synchronous_continuations=allow_synchronous_continuations,
        )
        self.comparer = comparer


# =============================================================================
# Readers, writers, channels
# =============================================================================

def _token(token: CancellationToken | None) -> CancellationToken:
    if token is None:
        return _NONE_TOKEN
    if not isinstance(token, CancellationToken):
        raise TypeError("token must be a CancellationToken or None")
    return token


class ChannelReader[T]:
    """The reading half of a channel (.NET ``ChannelReader<T>``).

    Subclasses implement ``try_read`` and ``wait_to_read_async``; the other members have
    defaults built on those two, as in .NET.
    """

    @property
    def completion(self) -> Task[None]:
        """Completes when no more data will ever be readable: the writer completed and the channel is empty."""
        return _never_completing()

    @property
    def can_count(self) -> bool:
        return False

    @property
    def can_peek(self) -> bool:
        return False

    @property
    def count(self) -> int:
        """The number of items available to read (when ``can_count``)."""
        raise NotSupportedError("This channel reader does not support counting.")

    def try_read(self) -> TryResult[T]:
        """Read an item if one is available: ``(True, item)``, otherwise ``(False, None)``."""
        raise NotImplementedError

    def try_peek(self) -> TryResult[T]:
        """Look at the next item without removing it (when ``can_peek``)."""
        return _FAILED_TRY

    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        """Complete with ``True`` when data is available, ``False`` once none ever will be."""
        raise NotImplementedError

    def read_async(self, token: CancellationToken | None = None) -> Task[T]:
        """Read the next item, waiting for one; raises ``ChannelClosedError`` once the channel is done."""
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        try:
            ok, item = self.try_read()
            if ok:
                return _completed(cast(T, item))
        except (ChannelClosedError, OperationCanceledError):
            raise
        except Exception as error:
            return _faulted(error)
        return Task.run(self._read_async_core, token)

    async def _read_async_core(self, token: CancellationToken) -> T:
        while True:
            if not await self.wait_to_read_async(token):
                raise ChannelClosedError()
            ok, item = self.try_read()
            if ok:
                return cast(T, item)

    def read_all_async(self, token: CancellationToken | None = None) -> AsyncFlpIt[T]:
        """Every item, as they arrive, until the channel is done (.NET ``ReadAllAsync``)."""
        if token is None:
            return _read_all(self)
        return _read_all(self, token=_token(token))


@async_flpit
async def _read_all[T](reader: ChannelReader[T], token: CancellationToken = _NONE_TOKEN) -> Any:
    while await reader.wait_to_read_async(token):
        while True:
            ok, item = reader.try_read()
            if not ok:
                break
            yield item


class ChannelWriter[T]:
    """The writing half of a channel (.NET ``ChannelWriter<T>``).

    Subclasses implement ``try_write`` and ``wait_to_write_async`` (and usually
    ``try_complete``); ``write_async`` and ``complete`` have defaults built on those.
    """

    def try_complete(self, error: BaseException | None = None) -> bool:
        """Mark the channel as done: no more writes. ``error`` is reported to readers."""
        return False

    def try_write(self, item: T) -> bool:
        """Write ``item`` if the channel accepts it right now."""
        raise NotImplementedError

    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        """Complete with ``True`` when space is available, ``False`` once no write will ever succeed."""
        raise NotImplementedError

    def write_async(self, item: T, token: CancellationToken | None = None) -> Task[None]:
        """Write ``item``, waiting for space; raises ``ChannelClosedError`` once the channel is done."""
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        try:
            if self.try_write(item):
                return Task.completed_task
        except Exception as error:
            return _faulted(error)
        return Task.run(self._write_async_core, item, token)

    async def _write_async_core(self, item: T, token: CancellationToken) -> None:
        while await self.wait_to_write_async(token):
            if self.try_write(item):
                return
        raise _invalid_completion_error()

    def complete(self, error: BaseException | None = None) -> None:
        """``try_complete``, raising ``ChannelClosedError`` if the channel was completed already."""
        if not self.try_complete(error):
            raise _invalid_completion_error()


class Channel[T]:
    """A channel: ``reader`` and ``writer`` over one buffer (.NET ``Channel<T>`` and ``Channel``).

    Create one with ``create_unbounded``, ``create_bounded`` or ``create_unbounded_prioritized``.
    Subclasses (for custom channels) set ``reader`` and ``writer`` themselves.
    """

    reader: ChannelReader[T]
    writer: ChannelWriter[T]

    @staticmethod
    def create_unbounded[U](options: UnboundedChannelOptions | None = None) -> Channel[U]:
        """A channel without a capacity limit (.NET ``Channel.CreateUnbounded``)."""
        if options is None:
            return _BufferedChannel(_FifoItems(), None, BoundedChannelFullMode.WAIT, False, None)
        if not isinstance(options, ChannelOptions):
            raise ArgumentNullError("options")
        allow = options.allow_synchronous_continuations
        if options.single_reader:
            return _SingleConsumerUnboundedChannel(allow)
        return _BufferedChannel(_FifoItems(), None, BoundedChannelFullMode.WAIT, allow, None)

    @staticmethod
    def create_bounded[U](
            capacity: int | BoundedChannelOptions,
            item_dropped: Callable[[U], Any] | None = None,
    ) -> Channel[U]:
        """A channel holding at most ``capacity`` items (.NET ``Channel.CreateBounded``).

        Pass an int, or ``BoundedChannelOptions`` for the full mode and the other options.
        ``item_dropped`` receives every item a drop mode removes. A capacity of 0 creates a
        rendezvous channel: a write completes only when a reader takes its item.
        """
        if capacity is None:
            raise ArgumentNullError("options")
        if isinstance(capacity, BoundedChannelOptions):
            options = capacity
        elif isinstance(capacity, int) and not isinstance(capacity, bool):
            if capacity < 0:
                raise _out_of_range("capacity")
            options = BoundedChannelOptions(capacity)
        else:
            raise TypeError("capacity must be an int or BoundedChannelOptions")
        allow = options.allow_synchronous_continuations
        if options.capacity == 0:
            return _RendezvousChannel(options.full_mode, allow, item_dropped)
        return _BufferedChannel(_FifoItems(), options.capacity, options.full_mode, allow, item_dropped)

    @staticmethod
    def create_unbounded_prioritized[U](
            options: UnboundedPrioritizedChannelOptions[U] | None = None,
    ) -> Channel[U]:
        """An unbounded channel whose reads return the smallest item first (.NET ``CreateUnboundedPrioritized``)."""
        if options is None:
            return _BufferedChannel(_PriorityItems(None), None, BoundedChannelFullMode.WAIT, False, None)
        if not isinstance(options, ChannelOptions):
            raise ArgumentNullError("options")
        return _BufferedChannel(
            _PriorityItems(options.comparer), None, BoundedChannelFullMode.WAIT,
            options.allow_synchronous_continuations, None,
        )


# =============================================================================
# Completed tasks and completion errors (.NET ChannelUtilities)
# =============================================================================

_DONE_WRITING = Exception("done writing")  # the writer completed without an error

_cached: dict[str, Task[Any]] = {}


def _never_completing() -> Task[None]:
    task = _cached.get("never")
    if task is None:
        task = _cached["never"] = TaskCompletionSource[None]().task
    return task


def _completed[R](value: R) -> Task[R]:
    if value is True or value is False:
        key = "true" if value else "false"
        task = _cached.get(key)
        if task is None:
            source: TaskCompletionSource[bool] = TaskCompletionSource()
            source.set_result(value)
            task = _cached[key] = source.task
        return cast(Task[R], task)
    source2: TaskCompletionSource[R] = TaskCompletionSource()
    source2.set_result(value)
    return source2.task


def _faulted[R](error: BaseException) -> Task[R]:
    source: TaskCompletionSource[R] = TaskCompletionSource()
    _fail(source, error)
    return source.task


def _canceled[R](token: CancellationToken) -> Task[R]:
    """A canceled task, as .NET's ``Task.FromCanceled`` (awaiting it raises ``TaskCanceledError``)."""
    source: TaskCompletionSource[R] = TaskCompletionSource()
    source._try_complete(Task.CANCELLED, exception=TaskCanceledError(source.task, token=token))
    return source.task


def _fail(source: TaskCompletionSource[Any], error: BaseException) -> None:
    """Fail ``source`` with ``error`` itself; a cancellation error cancels it."""
    if isinstance(error, OperationCanceledError):
        source._try_complete(Task.CANCELLED, exception=error)
    else:
        source._try_complete(Task.FAILED, exception=error)


def _complete_completion(source: TaskCompletionSource[None], error: BaseException | None) -> None:
    if isinstance(error, OperationCanceledError):
        source._try_complete(Task.CANCELLED, exception=error)
    elif error is not None and error is not _DONE_WRITING:
        source._try_complete(Task.FAILED, exception=error)
    else:
        source.try_set_result()


def _invalid_completion_error(inner: BaseException | None = None) -> BaseException:
    if isinstance(inner, OperationCanceledError):
        return inner
    if inner is not None and inner is not _DONE_WRITING:
        return ChannelClosedError(inner)
    return ChannelClosedError()


def _invalid_completion_task[R](done_writing: BaseException) -> Task[R]:
    if done_writing is _DONE_WRITING:
        return _faulted(ChannelClosedError())
    if isinstance(done_writing, OperationCanceledError):
        token = done_writing.token
        if token is None or not token.is_cancellation_requested:
            source = CancellationTokenSource()
            source.cancel()
            token = source.token
        return _canceled(token)
    return _faulted(ChannelClosedError(done_writing))


def _wait_result_when_done(done_writing: BaseException) -> Task[bool]:
    """``WaitToRead/WriteAsync`` once the writer is done: False, or the completion error itself."""
    if done_writing is _DONE_WRITING:
        return _completed(False)
    return _faulted(done_writing)


# =============================================================================
# Pending operations
# =============================================================================

class _Operation:
    """A pending read, write or wait; its task completes once, through whoever unlinks it."""

    __slots__ = ("source", "item")

    def __init__(self, async_continuations: bool, item: Any = None) -> None:
        self.source: TaskCompletionSource[Any] = TaskCompletionSource()
        if async_continuations:
            self.source.task._async_continuations = True
        self.item = item


type _OperationQueue = OrderedDict[_Operation, None]


def _take_all(queue: _OperationQueue) -> list[_Operation]:
    operations = list(queue)
    queue.clear()
    return operations


def _set_all(operations: list[_Operation], result: Any) -> None:
    for operation in operations:
        operation.source.try_set_result(result)


def _fail_all(operations: list[_Operation], error: BaseException) -> None:
    for operation in operations:
        _fail(operation.source, error)


def _set_or_fail_all(operations: list[_Operation], result: Any, error: BaseException | None) -> None:
    if error is not None:
        _fail_all(operations, error)
    else:
        _set_all(operations, result)


class _ChannelCore[T](Channel[T]):
    """Lock, completion and the cancellation of pending operations, shared by every kind."""

    def __init__(self, allow_synchronous_continuations: bool, item_dropped: Callable[[T], Any] | None) -> None:
        # Reentrant: a token cancelled while an operation registers runs its callback right
        # there, and the callback takes this lock too.
        self._lock = threading.RLock()
        self._async_continuations = not allow_synchronous_continuations
        self._item_dropped = item_dropped
        self._completion: TaskCompletionSource[None] = TaskCompletionSource()
        if self._async_continuations:
            self._completion.task._async_continuations = True
        self._done_writing: BaseException | None = None

    def _enqueue(
            self, queue: _OperationQueue, operation: _Operation, token: CancellationToken
    ) -> Task[Any]:
        """Add ``operation`` to ``queue``. Lock held."""
        queue[operation] = None
        if token.can_be_cancelled:
            # Disposed by the task when it completes.
            operation.source.task._token_registration = token.register(
                lambda: self._cancel(queue, operation, token)
            )
        return operation.source.task

    def _cancel(self, queue: _OperationQueue, operation: _Operation, token: CancellationToken) -> None:
        with self._lock:
            if queue.pop(operation, _MISSING) is _MISSING:
                return  # already completed by a read, write or completion
        operation.source.try_set_canceled(token)


_MISSING: Any = object()


# =============================================================================
# Item storage: FIFO (bounded and unbounded) and by priority
# =============================================================================

class _FifoItems[T]:
    __slots__ = ("_items",)

    def __init__(self) -> None:
        self._items: deque[T] = deque()

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: T) -> None:
        self._items.append(item)

    def take(self) -> T:
        return self._items.popleft()

    def take_newest(self) -> T:
        return self._items.pop()

    def peek(self) -> T:
        return self._items[0]

    def snapshot(self) -> list[T]:
        return list(self._items)


class _PriorityItems[T]:
    """A heap: smallest first; equal items in write order."""

    __slots__ = ("_heap", "_key", "_sequence")

    def __init__(self, comparer: Callable[[T, T], int] | None) -> None:
        self._heap: list[tuple[Any, int, T]] = []
        self._key: Callable[[T], Any] | None = None if comparer is None else cmp_to_key(comparer)
        self._sequence = count()

    def __len__(self) -> int:
        return len(self._heap)

    def add(self, item: T) -> None:
        key = item if self._key is None else self._key(item)
        heapq.heappush(self._heap, (key, next(self._sequence), item))

    def take(self) -> T:
        return heapq.heappop(self._heap)[2]

    def take_newest(self) -> T:  # never full: not used
        raise NotSupportedError

    def peek(self) -> T:
        return self._heap[0][2]

    def snapshot(self) -> list[T]:
        return [entry[2] for entry in sorted(self._heap)]


# =============================================================================
# Bounded, unbounded and prioritized channels
# =============================================================================

class _BufferedChannel[T](_ChannelCore[T]):
    """``capacity=None``: unbounded (.NET UnboundedChannel / UnboundedPrioritizedChannel);
    otherwise bounded (.NET BoundedChannel)."""

    def __init__(
            self,
            items: _FifoItems[T] | _PriorityItems[T],
            capacity: int | None,
            full_mode: BoundedChannelFullMode,
            allow_synchronous_continuations: bool,
            item_dropped: Callable[[T], Any] | None,
    ) -> None:
        super().__init__(allow_synchronous_continuations, item_dropped)
        self._items = items
        self._capacity = capacity
        self._full_mode = full_mode
        self._blocked_readers: _OperationQueue = OrderedDict()
        self._waiting_readers: _OperationQueue = OrderedDict()
        self._blocked_writers: _OperationQueue = OrderedDict()
        self._waiting_writers: _OperationQueue = OrderedDict()
        self.reader = _BufferedReader(self)
        self.writer = _BufferedWriter(self)

    def _dequeue_and_post_process(self) -> T:
        """Take the next item and let the channel react. Lock held."""
        item = self._items.take()
        if self._done_writing is not None:
            if not len(self._items):
                _complete_completion(self._completion, self._done_writing)
        elif self._capacity is not None:
            # A slot is free: move a blocked writer's item in, or wake the waiting writers.
            # Writer operations always continue asynchronously, so completing them here,
            # under the lock, runs no user code.
            while self._blocked_writers:
                writer, _ = self._blocked_writers.popitem(last=False)
                if writer.source.try_set_result(None):
                    self._items.add(writer.item)
                    return item
            _set_all(_take_all(self._waiting_writers), True)
        return item


class _BufferedReader[T](ChannelReader[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _BufferedChannel[T]) -> None:
        self._parent = parent

    @property
    @override
    def completion(self) -> Task[None]:
        return self._parent._completion.task

    @property
    @override
    def can_count(self) -> bool:
        return True

    @property
    @override
    def can_peek(self) -> bool:
        return True

    @property
    @override
    def count(self) -> int:
        with self._parent._lock:
            return len(self._parent._items)

    @override
    def try_read(self) -> TryResult[T]:
        parent = self._parent
        with parent._lock:
            if len(parent._items):
                return True, parent._dequeue_and_post_process()
        return _FAILED_TRY

    @override
    def try_peek(self) -> TryResult[T]:
        parent = self._parent
        with parent._lock:
            if len(parent._items):
                return True, parent._items.peek()
        return _FAILED_TRY

    @override
    def read_async(self, token: CancellationToken | None = None) -> Task[T]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if len(parent._items):
                return _completed(parent._dequeue_and_post_process())
            if parent._done_writing is not None:
                return _invalid_completion_task(parent._done_writing)
            reader = _Operation(parent._async_continuations)
            return parent._enqueue(parent._blocked_readers, reader, token)

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if len(parent._items):
                return _completed(True)
            if parent._done_writing is not None:
                return _wait_result_when_done(parent._done_writing)
            waiter = _Operation(parent._async_continuations)
            return parent._enqueue(parent._waiting_readers, waiter, token)


class _BufferedWriter[T](ChannelWriter[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _BufferedChannel[T]) -> None:
        self._parent = parent

    @override
    def try_complete(self, error: BaseException | None = None) -> bool:
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return False
            parent._done_writing = error if error is not None else _DONE_WRITING
            complete_task = not len(parent._items)
            blocked_readers = _take_all(parent._blocked_readers)
            blocked_writers = _take_all(parent._blocked_writers)
            waiting_readers = _take_all(parent._waiting_readers)
            waiting_writers = _take_all(parent._waiting_writers)
        if complete_task:
            _complete_completion(parent._completion, error)
        _fail_all(blocked_readers, _invalid_completion_error(error))
        _fail_all(blocked_writers, _invalid_completion_error(error))
        _set_or_fail_all(waiting_readers, False, error)
        _set_or_fail_all(waiting_writers, False, error)
        return True

    @override
    def try_write(self, item: T) -> bool:
        return self._write(item, None) is not None

    @override
    def write_async(self, item: T, token: CancellationToken | None = None) -> Task[None]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        task = self._write(item, token)
        assert task is not None
        return task

    def _write(self, item: T, token: CancellationToken | None) -> Task[None] | None:
        """``try_write`` (token None: returns None for "not written") and ``write_async``."""
        parent = self._parent
        blocked_reader: _Operation | None = None
        waiting_readers: list[_Operation] = []
        dropped: list[T] = []
        with parent._lock:
            if parent._done_writing is not None:
                if token is None:
                    return None
                return _faulted(_invalid_completion_error(parent._done_writing))
            items = parent._items
            size = len(items)
            capacity = parent._capacity
            if size == 0:
                if parent._blocked_readers:
                    blocked_reader, _ = parent._blocked_readers.popitem(last=False)
                else:
                    items.add(item)
                    waiting_readers = _take_all(parent._waiting_readers)
            elif capacity is None or size < capacity:
                items.add(item)
            elif parent._full_mode is BoundedChannelFullMode.WAIT:
                if token is None:
                    return None
                writer = _Operation(True, item)  # writers always continue asynchronously
                return parent._enqueue(parent._blocked_writers, writer, token)
            elif parent._full_mode is BoundedChannelFullMode.DROP_WRITE:
                dropped.append(item)
            else:
                dropped.append(
                    items.take_newest() if parent._full_mode is BoundedChannelFullMode.DROP_NEWEST else items.take()
                )
                items.add(item)
        if dropped:
            if parent._item_dropped is not None:
                parent._item_dropped(dropped[0])
        elif blocked_reader is not None:
            blocked_reader.source.try_set_result(item)
        else:
            _set_all(waiting_readers, True)
        return Task.completed_task

    @override
    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return _wait_result_when_done(parent._done_writing)
            capacity = parent._capacity
            if capacity is None or len(parent._items) < capacity or parent._full_mode is not BoundedChannelFullMode.WAIT:
                return _completed(True)
            waiter = _Operation(True)  # writers always continue asynchronously
            return parent._enqueue(parent._waiting_writers, waiter, token)


# =============================================================================
# Single-consumer unbounded channel
# =============================================================================

class _SingleConsumerUnboundedChannel[T](_ChannelCore[T]):
    """``create_unbounded(single_reader=True)`` (.NET SingleConsumerUnboundedChannel): one pending
    read or wait at a time; a new one cancels the previous one."""

    def __init__(self, allow_synchronous_continuations: bool) -> None:
        super().__init__(allow_synchronous_continuations, None)
        self._items: deque[T] = deque()
        self._blocked_reader: _Operation | None = None
        self._waiting_reader: _Operation | None = None
        self.reader = _SingleConsumerReader(self)
        self.writer = _SingleConsumerWriter(self)

    def _register(self, operation: _Operation, token: CancellationToken) -> None:
        if token.can_be_cancelled:
            operation.source.task._token_registration = token.register(
                lambda: self._cancel_slot(operation, token)
            )

    def _cancel_slot(self, operation: _Operation, token: CancellationToken) -> None:
        with self._lock:
            if self._blocked_reader is operation:
                self._blocked_reader = None
            elif self._waiting_reader is operation:
                self._waiting_reader = None
            else:
                return
        operation.source.try_set_canceled(token)

    def _complete_if_done(self) -> None:
        if self._done_writing is not None and not self._items:
            _complete_completion(self._completion, self._done_writing)


class _SingleConsumerReader[T](ChannelReader[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _SingleConsumerUnboundedChannel[T]) -> None:
        self._parent = parent

    @property
    @override
    def completion(self) -> Task[None]:
        return self._parent._completion.task

    @property
    @override
    def can_peek(self) -> bool:
        return True

    @override
    def try_read(self) -> TryResult[T]:
        parent = self._parent
        with parent._lock:
            if parent._items:
                item = parent._items.popleft()
                parent._complete_if_done()
                return True, item
        return _FAILED_TRY

    @override
    def try_peek(self) -> TryResult[T]:
        parent = self._parent
        with parent._lock:
            if parent._items:
                return True, parent._items[0]
        return _FAILED_TRY

    @override
    def read_async(self, token: CancellationToken | None = None) -> Task[T]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            ok, item = self.try_read()
            if ok:
                return _completed(cast(T, item))
            if parent._done_writing is not None:
                return _invalid_completion_task(parent._done_writing)
            previous = parent._blocked_reader
            reader = _Operation(parent._async_continuations)
            parent._blocked_reader = reader
            parent._register(reader, token)
        if previous is not None:
            previous.source.try_set_canceled()
        return reader.source.task

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if parent._items:
                return _completed(True)
            if parent._done_writing is not None:
                return _wait_result_when_done(parent._done_writing)
            previous = parent._waiting_reader
            waiter = _Operation(parent._async_continuations)
            parent._waiting_reader = waiter
            parent._register(waiter, token)
        if previous is not None:
            previous.source.try_set_canceled()
        return waiter.source.task


class _SingleConsumerWriter[T](ChannelWriter[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _SingleConsumerUnboundedChannel[T]) -> None:
        self._parent = parent

    @override
    def try_complete(self, error: BaseException | None = None) -> bool:
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return False
            parent._done_writing = error if error is not None else _DONE_WRITING
            complete_task = not parent._items
            blocked_reader, parent._blocked_reader = parent._blocked_reader, None
            waiting_reader, parent._waiting_reader = parent._waiting_reader, None
        if complete_task:
            _complete_completion(parent._completion, error)
        if blocked_reader is not None:
            _fail(blocked_reader.source, _invalid_completion_error(error))
        if waiting_reader is not None:
            _set_or_fail_all([waiting_reader], False, error)
        return True

    @override
    def try_write(self, item: T) -> bool:
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return False
            blocked_reader, parent._blocked_reader = parent._blocked_reader, None
            waiting_reader = None
            if blocked_reader is None:
                parent._items.append(item)
                waiting_reader, parent._waiting_reader = parent._waiting_reader, None
        if blocked_reader is not None:
            blocked_reader.source.try_set_result(item)
        elif waiting_reader is not None:
            waiting_reader.source.try_set_result(True)
        return True

    @override
    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        done_writing = self._parent._done_writing
        if done_writing is None:
            return _completed(True)
        return _wait_result_when_done(done_writing)

    @override
    def write_async(self, item: T, token: CancellationToken | None = None) -> Task[None]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        if self.try_write(item):
            return Task.completed_task
        return _faulted(_invalid_completion_error(self._parent._done_writing))


# =============================================================================
# Rendezvous channel (bounded, capacity 0)
# =============================================================================

class _RendezvousChannel[T](_ChannelCore[T]):
    """``create_bounded(0)`` (.NET RendezvousChannel): no buffer; a write completes when a reader
    takes its item. With a drop mode, a write that finds no reader is dropped."""

    def __init__(
            self, full_mode: BoundedChannelFullMode, allow_synchronous_continuations: bool,
            item_dropped: Callable[[T], Any] | None,
    ) -> None:
        super().__init__(allow_synchronous_continuations, item_dropped)
        self._drop_writes = full_mode is not BoundedChannelFullMode.WAIT
        self._blocked_readers: _OperationQueue = OrderedDict()
        self._waiting_readers: _OperationQueue = OrderedDict()
        self._blocked_writers: _OperationQueue = OrderedDict()
        self._waiting_writers: _OperationQueue = OrderedDict()
        self.reader = _RendezvousReader(self)
        self.writer = _RendezvousWriter(self)


class _RendezvousReader[T](ChannelReader[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _RendezvousChannel[T]) -> None:
        self._parent = parent

    @property
    @override
    def completion(self) -> Task[None]:
        return self._parent._completion.task

    @property
    @override
    def can_count(self) -> bool:
        return True

    @property
    @override
    def can_peek(self) -> bool:
        return True

    @property
    @override
    def count(self) -> int:
        return 0

    @override
    def try_read(self) -> TryResult[T]:
        parent = self._parent
        writer: _Operation | None = None
        with parent._lock:
            if parent._done_writing is None and parent._blocked_writers:
                writer, _ = parent._blocked_writers.popitem(last=False)
        if writer is not None:
            item = writer.item
            writer.source.try_set_result(None)
            return True, item
        return _FAILED_TRY

    @override
    def try_peek(self) -> TryResult[T]:
        parent = self._parent
        with parent._lock:
            if parent._done_writing is None and parent._blocked_writers:
                return True, next(iter(parent._blocked_writers)).item
        return _FAILED_TRY

    @override
    def read_async(self, token: CancellationToken | None = None) -> Task[T]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        writer: _Operation | None = None
        waiting_writers: list[_Operation] = []
        task: Task[T] | None = None
        with parent._lock:
            if parent._done_writing is not None:
                return _invalid_completion_task(parent._done_writing)
            if parent._blocked_writers:
                writer, _ = parent._blocked_writers.popitem(last=False)
            else:
                reader = _Operation(parent._async_continuations)
                task = parent._enqueue(parent._blocked_readers, reader, token)
                waiting_writers = _take_all(parent._waiting_writers)
        if writer is not None:
            item = writer.item
            writer.source.try_set_result(None)
            return _completed(item)
        _set_all(waiting_writers, True)
        assert task is not None
        return task

    @override
    def wait_to_read_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return _wait_result_when_done(parent._done_writing)
            if parent._blocked_writers:
                return _completed(True)
            waiter = _Operation(parent._async_continuations)
            return parent._enqueue(parent._waiting_readers, waiter, token)


class _RendezvousWriter[T](ChannelWriter[T]):
    __slots__ = ("_parent",)

    def __init__(self, parent: _RendezvousChannel[T]) -> None:
        self._parent = parent

    @override
    def try_complete(self, error: BaseException | None = None) -> bool:
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return False
            parent._done_writing = error if error is not None else _DONE_WRITING
            blocked_readers = _take_all(parent._blocked_readers)
            blocked_writers = _take_all(parent._blocked_writers)
            waiting_readers = _take_all(parent._waiting_readers)
            waiting_writers = _take_all(parent._waiting_writers)
        _complete_completion(parent._completion, error)
        _fail_all(blocked_readers, _invalid_completion_error(error))
        _fail_all(blocked_writers, _invalid_completion_error(error))
        _set_or_fail_all(waiting_readers, False, error)
        _set_or_fail_all(waiting_writers, False, error)
        return True

    @override
    def try_write(self, item: T) -> bool:
        parent = self._parent
        reader: _Operation | None = None
        with parent._lock:
            if parent._done_writing is None and parent._blocked_readers:
                reader, _ = parent._blocked_readers.popitem(last=False)
        if reader is not None:
            reader.source.try_set_result(item)
            return True
        if parent._drop_writes:
            if parent._item_dropped is not None:
                parent._item_dropped(item)
            return True
        return False

    @override
    def wait_to_write_async(self, token: CancellationToken | None = None) -> Task[bool]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        with parent._lock:
            if parent._done_writing is not None:
                return _wait_result_when_done(parent._done_writing)
            if parent._blocked_readers or parent._drop_writes:
                return _completed(True)
            waiter = _Operation(parent._async_continuations)
            return parent._enqueue(parent._waiting_writers, waiter, token)

    @override
    def write_async(self, item: T, token: CancellationToken | None = None) -> Task[None]:
        token = _token(token)
        if token.is_cancellation_requested:
            return _canceled(token)
        parent = self._parent
        reader: _Operation | None = None
        waiting_readers: list[_Operation] = []
        task: Task[None] | None = None
        with parent._lock:
            if parent._done_writing is not None:
                return _faulted(_invalid_completion_error(parent._done_writing))
            if parent._blocked_readers:
                reader, _ = parent._blocked_readers.popitem(last=False)
            elif not parent._drop_writes:
                writer = _Operation(parent._async_continuations, item)
                task = parent._enqueue(parent._blocked_writers, writer, token)
                waiting_readers = _take_all(parent._waiting_readers)
        if task is not None:
            _set_all(waiting_readers, True)
            return task
        if reader is not None:
            reader.source.try_set_result(item)
        elif parent._item_dropped is not None:
            parent._item_dropped(item)
        return Task.completed_task
