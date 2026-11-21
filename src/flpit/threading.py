"""Threading and logical execution-context primitives."""

from __future__ import annotations

import math
import threading as _threading
import time as _time
from collections.abc import Callable
from contextvars import Context, ContextVar
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from flpit.core.linq import ArgumentNullError, ArgumentOutOfRangeError, InvalidOperationError

# flpit.task imports this module, so it is bound here as a (possibly partially
# initialized) module object and its attributes are resolved at call time.
from flpit import task as _task

if TYPE_CHECKING:
    from flpit.task import CancellationToken, CancellationTokenRegistration, Task


@dataclass(frozen=True, slots=True)
class AsyncLocalValueChangedArgs[T]:
    previous_value: T | None
    current_value: T | None
    thread_context_changed: bool


class AsyncLocal[T]:
    """A value that follows the logical flow of a task (.NET ``AsyncLocal<T>``).

    Unlike ``ThreadLocal``, the value does not belong to an OS thread: a task that resumes
    on another pool worker after an ``await`` still sees its own value. A task inherits the
    value of the flow that started it, and changes made inside the task do not reach its parent.
    Built on ``contextvars.ContextVar``.

    ``value_changed_handler`` is called with an ``AsyncLocalValueChangedArgs`` when the value
    changes; ``thread_context_changed`` is true when the change comes from switching to another
    flow and not from an assignment.

    Example:
        ```python
        request_id = AsyncLocal[str]()
        request_id.value = "req-1"   # visible to this task and to the tasks it starts
        ```
    """

    def __init__(
            self,
            value_changed_handler: (
                    Callable[[AsyncLocalValueChangedArgs[T]], None] | None
            ) = None,
            *,
            default: T | None = None,
    ) -> None:
        self._value: ContextVar[T | None] = ContextVar(
            f"flpit.AsyncLocal.{id(self):x}",
            default=default,
        )
        self._default = default
        self._value_changed_handler = value_changed_handler

        if value_changed_handler is not None:
            # Context-transition notifications cost several context lookups
            # per switch. They are only paid for once a handler exists.
            global _notifications_enabled
            _notifications_enabled = True

    @property
    def value(self) -> T | None:
        return self._value.get()

    @value.setter
    def value(self, value: T | None) -> None:
        previous_value = self._value.get()

        if previous_value is value:
            return

        self._value.set(value)

        if self._value_changed_handler is None:
            return

        registered = _async_local_change_notifications.get()

        if self not in registered:
            _async_local_change_notifications.set((*registered, self))

        self._notify_change(
            previous_value,
            value,
            thread_context_changed=False,
        )

    def _notify_change(
            self,
            previous_value: T | None,
            current_value: T | None,
            *,
            thread_context_changed: bool,
    ) -> None:
        if previous_value is current_value:
            return

        if self._value_changed_handler is not None:
            self._value_changed_handler(
                AsyncLocalValueChangedArgs(
                    previous_value=previous_value,
                    current_value=current_value,
                    thread_context_changed=thread_context_changed,
                )
            )


# False until the first AsyncLocal with a change handler is created.
_notifications_enabled = False

# Equivalent to .NET's per-ExecutionContext IAsyncLocal notification list.
_async_local_change_notifications: ContextVar[
    tuple[AsyncLocal[Any], ...]
] = ContextVar(
    "flpit.async_local_change_notifications",
    default=(),
)


def _merge_async_locals(
        previous: tuple[AsyncLocal[Any], ...],
        current: tuple[AsyncLocal[Any], ...],
) -> tuple[AsyncLocal[Any], ...]:
    return tuple(dict.fromkeys((*previous, *current)))


def _notify_context_transition(
        async_locals: tuple[AsyncLocal[Any], ...],
        previous_values: dict[AsyncLocal[Any], Any],
        current_values: dict[AsyncLocal[Any], Any],
) -> None:
    for local in async_locals:
        local._notify_change(
            previous_values[local],
            current_values[local],
            thread_context_changed=True,
        )


def _context_value(context: Context, local: AsyncLocal[Any]) -> Any:
    # Reads the value without entering the context, so it also works for a
    # context that is currently entered elsewhere.
    return context.get(local._value, local._default)


def _run_with_context[R](
        context: Context,
        callback: Callable[..., R],
        /,
        *args: Any,
        **kwargs: Any,
) -> R:
    """Run ``callback(*args, **kwargs)`` in ``context`` with AsyncLocal notifications.

    This sits on the hot path of the task runtime (once per coroutine step),
    so the common case of "no AsyncLocal has a change handler" is a plain
    ``Context.run``.
    """
    if not _notifications_enabled:
        try:
            return context.run(callback, *args, **kwargs)
        finally:
            # A handler may have been installed while the callback ran.
            if _notifications_enabled:
                _notify_context_exit(context)

    # Capture the currently active execution context.
    previous_locals = _async_local_change_notifications.get()

    # Obtain the notification registrations belonging to the target context.
    incoming_locals = context.get(_async_local_change_notifications, ())

    if not previous_locals and not incoming_locals:
        try:
            return context.run(callback, *args, **kwargs)
        finally:
            _notify_context_exit(context)

    transition_locals = _merge_async_locals(
        previous_locals,
        incoming_locals,
    )

    previous_values = {
        local: local.value
        for local in transition_locals
    }

    incoming_values = {
        local: _context_value(context, local)
        for local in transition_locals
    }

    def enter_context() -> R:
        _notify_context_transition(
            transition_locals,
            previous_values,
            incoming_values,
        )
        return callback(*args, **kwargs)

    try:
        return context.run(enter_context)

    finally:
        _notify_context_exit(context)


def _notify_context_exit(context: Context) -> None:
    # The target context has now exited. Inspect its final values,
    # including AsyncLocal instances registered during callback execution.
    outgoing_locals = context.get(_async_local_change_notifications, ())

    restored_locals = _async_local_change_notifications.get()

    if not outgoing_locals and not restored_locals:
        return

    exit_locals = _merge_async_locals(
        outgoing_locals,
        restored_locals,
    )

    outgoing_values = {
        local: _context_value(context, local)
        for local in exit_locals
    }

    restored_values = {
        local: local.value
        for local in exit_locals
    }

    _notify_context_transition(
        exit_locals,
        outgoing_values,
        restored_values,
    )


# =============================================================================
# ThreadLocal (System.Threading.ThreadLocal<T>)
# =============================================================================

_NO_FACTORY: Any = object()


class _ThreadLocalSlot:
    """One thread's value of one ThreadLocal; also what ``values`` tracks."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


class ThreadLocal[T]:
    """Per-OS-thread storage (.NET ``System.Threading.ThreadLocal<T>``).

    Unlike ``AsyncLocal``, the value belongs to the thread, not the logical flow:
    a coroutine that resumes on another pool worker after ``await`` sees that
    worker's value. ``value_factory`` lazily creates each thread's first value;
    without one, a thread starts with ``default`` (.NET ``default(T)``).

    With ``track_all_values=True``, ``values`` lists every thread's value, including
    values of threads that have exited, until ``dispose()``. Untracked values are
    released when their thread exits. Like .NET, ``ThreadLocal(True)`` is accepted
    as the ``trackAllValues`` overload::

        counter = ThreadLocal(lambda: 0)
        counter.value += 1          # per-thread, no locking needed
    """

    __slots__ = ("_local", "_factory", "_default", "_tracked", "_lock", "__weakref__")

    def __init__(
            self,
            value_factory: Callable[[], T] | bool = _NO_FACTORY,
            track_all_values: bool = False,
            *,
            default: T | None = None,
    ) -> None:
        if isinstance(value_factory, bool):  # ThreadLocal(bool trackAllValues)
            value_factory, track_all_values = _NO_FACTORY, value_factory
        if value_factory is None:
            raise ArgumentNullError("valueFactory")
        if value_factory is not _NO_FACTORY and not callable(value_factory):
            raise TypeError("value_factory must be callable")
        self._local: _threading.local | None = _threading.local()
        self._factory: Callable[[], T] | None = None if value_factory is _NO_FACTORY else value_factory
        self._default = default
        self._tracked: list[_ThreadLocalSlot] | None = [] if track_all_values else None
        self._lock = _threading.Lock()

    def _storage(self) -> _threading.local:
        local = self._local
        if local is None:
            raise ObjectDisposedError(type(self).__name__)
        return local

    @property
    def value(self) -> T:
        """This thread's value; created by ``value_factory`` on first access."""
        slot = getattr(self._storage(), "slot", None)
        if slot is not None:
            return slot.value
        if self._factory is None:
            value = self._default
        else:
            value = self._factory()
            if self.is_value_created:
                raise InvalidOperationError(
                    "ValueFactory attempted to access the Value property of this instance."
                )
        self.value = cast(T, value)
        return cast(T, value)

    @value.setter
    def value(self, value: T) -> None:
        local = self._storage()
        slot = getattr(local, "slot", None)
        if slot is not None:
            slot.value = value
            return
        slot = _ThreadLocalSlot(value)
        tracked = self._tracked
        if tracked is not None:
            with self._lock:
                if self._local is None:
                    raise ObjectDisposedError(type(self).__name__)
                tracked.append(slot)  # kept after the thread exits, as in .NET
        local.slot = slot

    @property
    def is_value_created(self) -> bool:
        """Whether this thread's value has been created or set."""
        return getattr(self._storage(), "slot", None) is not None

    @property
    def values(self) -> list[T]:
        """Every thread's value (requires ``track_all_values=True``)."""
        if self._tracked is None:
            raise InvalidOperationError(
                "The ThreadLocal object is not tracking values. To use the Values property, "
                "use a ThreadLocal constructor that accepts the trackAllValues parameter and set the parameter to true."
            )
        with self._lock:
            if self._local is None:
                raise ObjectDisposedError(type(self).__name__)
            return [slot.value for slot in self._tracked]

    def dispose(self) -> None:
        """Release every thread's value; further access raises ``ObjectDisposedError``."""
        with self._lock:
            self._local = None  # drops every thread's slot with the threading.local
            if self._tracked is not None:
                self._tracked.clear()

    close = dispose

    def __enter__(self) -> ThreadLocal[T]:
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()

    def __str__(self) -> str:
        """``str()`` of this thread's value, creating it if needed (.NET ``ToString``)."""
        return str(self.value)


# =============================================================================
# Wait handles, timeouts and SemaphoreSlim (System.Threading)
# =============================================================================

class SemaphoreFullError(Exception):
    """Raised when ``release`` would exceed the maximum count (.NET ``SemaphoreFullException``)."""

    def __init__(
            self,
            message: str = "Adding the specified count to the semaphore would cause it to exceed its maximum count.",
    ) -> None:
        super().__init__(message)


class ObjectDisposedError(InvalidOperationError):
    """Raised when a disposed object is used (.NET ``ObjectDisposedException``)."""

    def __init__(self, object_name: str) -> None:
        self.object_name = object_name
        super().__init__(f"Cannot access a disposed object.\nObject name: '{object_name}'.")


class Timeout:
    """Infinite-timeout constants (.NET ``System.Threading.Timeout``).

    flpit timeouts are float seconds: ``-1`` (or ``None``) waits forever. A
    ``timedelta`` is accepted where .NET takes a ``TimeSpan``; like .NET it is
    truncated to whole milliseconds, so ``INFINITE_TIMESPAN`` (-1 ms) waits forever.
    """

    INFINITE: Final = -1
    INFINITE_TIMESPAN: Final = timedelta(milliseconds=-1)


# Condition/lock waits reject timeouts above this; longer waits are capped and re-armed.
_MAX_WAIT: Final = min(_threading.TIMEOUT_MAX, 24 * 60 * 60.0)


_INT_MAX: Final = 2_147_483_647


def _to_seconds(
        timeout: float | timedelta | None, name: str = "timeout", *, bounded: bool = False
) -> float | None:
    """Validate a timeout and return seconds, or ``None`` for infinite.

    ``bounded`` rejects timeouts above ``Int32.MaxValue`` milliseconds, as .NET does for
    the APIs that take an ``int`` timeout underneath (``Task.Wait``, ``WaitAll``, ...).
    """
    if timeout is None:
        return None
    message = "The timeout must represent a value between -1 and Int32.MaxValue, inclusive."
    if isinstance(timeout, timedelta):
        milliseconds = int(timeout / timedelta(milliseconds=1))  # truncates like (long)TotalMilliseconds
        if milliseconds == -1:
            return None
        if milliseconds < -1 or (bounded and milliseconds > _INT_MAX):
            raise ArgumentOutOfRangeError(name, message)
        return timeout.total_seconds() if milliseconds else 0.0
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(f"{name} must be a number of seconds, a timedelta or None")
    if timeout == -1 or (timeout == math.inf and not bounded):
        return None
    if not timeout >= 0 or (bounded and timeout * 1000 > _INT_MAX):  # also rejects NaN
        raise ArgumentOutOfRangeError(name, message)
    return float(timeout)


def _blocking_wait(wait: Callable[[float | None], bool], timeout: float | None) -> bool:
    """Run a blocking OS-level wait, telling the flpit pool when a worker blocks.

    Mirrors ``Task.result()``: a blocked worker lets the pool inject a replacement,
    as the .NET thread pool does for threads blocked in ``Monitor.Wait``.
    """
    state = _task._thread_state
    pool = state.pool
    if pool is None:
        return wait(timeout)
    pool._worker_blocked()
    try:
        return wait(timeout)
    finally:
        pool._worker_unblocked()


class WaitHandle:
    """Minimal OS-style wait handle (.NET ``System.Threading.WaitHandle``)."""

    __slots__ = ("_event", "_disposed")

    def __init__(self, initial_state: bool = False) -> None:
        self._event = _threading.Event()
        self._disposed = False
        if initial_state:
            self._event.set()

    def wait_one(self, timeout: float | timedelta | None = None) -> bool:
        """Block until signaled; ``False`` when ``timeout`` (seconds) elapses first."""
        seconds = _to_seconds(timeout)
        self._check_disposed()
        if seconds == 0 or self._event.is_set():
            return self._event.is_set()
        if seconds is not None and seconds > _MAX_WAIT:
            deadline = _time.perf_counter() + seconds
            while not _blocking_wait(self._event.wait, min(_MAX_WAIT, deadline - _time.perf_counter())):
                if _time.perf_counter() >= deadline:
                    return False
            return True
        return _blocking_wait(self._event.wait, seconds)

    def dispose(self) -> None:
        self._disposed = True

    close = dispose

    def __enter__(self) -> WaitHandle:
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()

    def _check_disposed(self) -> None:
        if self._disposed:
            raise ObjectDisposedError(type(self).__name__)


class ManualResetEvent(WaitHandle):
    """Event that stays signaled until reset (.NET ``ManualResetEvent``)."""

    __slots__ = ()

    def set(self) -> bool:
        self._check_disposed()
        self._event.set()
        return True

    def reset(self) -> bool:
        self._check_disposed()
        self._event.clear()
        return True


class _AsyncWaiter:
    """Node in the FIFO list of asynchronous waiters (.NET ``SemaphoreSlim.TaskNode``)."""

    __slots__ = ("prev", "next", "source", "timer", "registration")

    def __init__(self) -> None:
        self.prev: _AsyncWaiter | None = None
        self.next: _AsyncWaiter | None = None
        self.source: _task.TaskCompletionSource[bool] = _task.TaskCompletionSource()
        self.timer: Any = None
        self.registration: CancellationTokenRegistration | None = None

    def release_handles(self) -> None:
        timer, self.timer = self.timer, None
        registration, self.registration = self.registration, None
        if timer is not None:
            timer.cancel()
        if registration is not None:
            registration.dispose()


def _completed(value: bool) -> Task[bool]:
    source: _task.TaskCompletionSource[bool] = _task.TaskCompletionSource()
    source.set_result(value)
    return source.task


class SemaphoreSlim:
    """Lightweight semaphore limiting concurrent access (.NET ``System.Threading.SemaphoreSlim``).

    Usable from plain threads (``wait``) and from flpit tasks (``await wait_async()``)
    at the same time. Asynchronous waiters are served in FIFO order; a synchronous
    ``wait`` that finds asynchronous waiters queued gets in line behind them.
    Completing an asynchronous wait never runs the awaiting coroutine on the thread
    that called ``release`` or cancelled the token: it is resumed on the pool.

    Timeouts are in seconds; ``-1`` or ``None`` waits forever, and a ``timedelta``
    is accepted where .NET takes a ``TimeSpan``::

        throttle = SemaphoreSlim(4)

        async def fetch(url):
            await throttle.wait_async()
            try:
                return await download(url)
            finally:
                throttle.release()
    """

    NO_MAXIMUM: Final = 2_147_483_647  # int.MaxValue

    __slots__ = (
        "_lock", "_max_count", "_current_count", "_wait_count", "_pulsed_to_wake",
        "_async_head", "_async_tail", "_wait_handle", "_disposed", "__weakref__",
    )

    def __init__(self, initial_count: int, max_count: int = NO_MAXIMUM) -> None:
        if initial_count < 0 or initial_count > max_count:
            raise ArgumentOutOfRangeError(
                "initialCount", "The initialCount argument must be non-negative and less than or equal to the maximumCount."
            )
        if max_count <= 0:
            raise ArgumentOutOfRangeError("maxCount", "The maximumCount argument must be a positive number.")
        # .NET's Monitor: the lock guarding all state plus the sync waiters' wait queue.
        self._lock = _threading.Condition(_threading.Lock())
        self._max_count = max_count
        self._current_count = initial_count
        self._wait_count = 0  # synchronous waiters inside the lock / blocked on it
        self._pulsed_to_wake = 0  # synchronous waiters notified but not yet woken
        self._async_head: _AsyncWaiter | None = None
        self._async_tail: _AsyncWaiter | None = None
        self._wait_handle: ManualResetEvent | None = None
        self._disposed = False

    # --- properties ----------------------------------------------------------------------------

    @property
    def current_count(self) -> int:
        """The number of remaining threads that can enter the semaphore."""
        return self._current_count

    @property
    def available_wait_handle(self) -> WaitHandle:
        """A handle that is signaled while ``current_count`` is above zero (created lazily)."""
        self._check_disposed()
        handle = self._wait_handle
        if handle is None:
            with self._lock:
                handle = self._wait_handle
                if handle is None:
                    handle = self._wait_handle = ManualResetEvent(self._current_count != 0)
        return handle

    # --- synchronous wait ----------------------------------------------------------------------

    def wait(
            self,
            timeout: float | timedelta | CancellationToken | None = None,
            token: CancellationToken | None = None,
    ) -> bool:
        """Block until the semaphore can be entered.

        Returns ``False`` if ``timeout`` elapses first (always ``True`` for an infinite
        wait). Raises ``OperationCanceledError`` when ``token`` is cancelled. Like .NET,
        ``wait(token)`` is accepted as the token-only overload.
        """
        if isinstance(timeout, _task.CancellationToken):
            timeout, token = None, timeout
        seconds = _to_seconds(timeout)
        token = _token(token)
        self._check_disposed()
        token.throw_if_cancellation_requested()

        if seconds == 0 and self._current_count == 0:
            return False  # pessimistic fail fast, outside the lock

        start = _time.perf_counter()
        async_wait: Task[bool] | None = None
        waiter: _AsyncWaiter | None = None
        wait_successful = False
        # Registered outside the lock: the callback takes the lock (.NET does the same).
        registration = token.register(self._pulse_all) if token.can_be_cancelled else None
        try:
            with self._lock:
                self._wait_count += 1
                try:
                    if self._async_head is not None:
                        # Async waiters are queued: for fairness, get in line behind them by
                        # turning this wait into an asynchronous one and blocking on it below.
                        async_wait, waiter = self._wait_async_locked(seconds, token)
                    else:
                        cancelled: _task.OperationCanceledError | None = None
                        if self._current_count == 0:
                            if seconds == 0:
                                return False
                            try:
                                wait_successful = self._wait_until_count_or_timeout(seconds, start, token)
                            except _task.OperationCanceledError as error:
                                cancelled = error
                        # Acquisition wins over cancellation/timeout so no count is lost.
                        if self._current_count > 0:
                            wait_successful = True
                            self._current_count -= 1
                        elif cancelled is not None:
                            raise cancelled
                        if self._wait_handle is not None and self._current_count == 0:
                            self._wait_handle.reset()
                finally:
                    self._wait_count -= 1
        finally:
            if registration is not None:
                registration.dispose()

        if async_wait is None:
            return wait_successful
        if waiter is not None:
            self._watch(waiter, seconds, token)
        return async_wait.result()

    def _wait_until_count_or_timeout(
            self, seconds: float | None, start: float, token: CancellationToken
    ) -> bool:
        """Wait on the lock's condition while the count is zero. Lock held."""
        while self._current_count == 0:
            token.throw_if_cancellation_requested()
            capped = False
            if seconds is None:
                wait_for: float | None = None
            else:
                remaining = seconds - (_time.perf_counter() - start)
                if remaining <= 0:
                    return False
                wait_for = remaining
            if wait_for is None or wait_for > _MAX_WAIT:
                # A capped wait that returns False is not a timeout; loop and wait again.
                capped = wait_for is not None
                wait_for = _MAX_WAIT if capped else None
            signaled = _blocking_wait(self._lock.wait, wait_for)
            # No per-thread pulse state: count any wake-up against the pulsed waiters.
            if self._pulsed_to_wake:
                self._pulsed_to_wake -= 1
            if wait_for is not None and not capped and not signaled:
                return False
        return True

    def _pulse_all(self) -> None:
        """Cancellation callback for synchronous waits: wake every waiter to re-check its token."""
        with self._lock:
            self._lock.notify_all()

    # --- asynchronous wait ---------------------------------------------------------------------

    def wait_async(
            self,
            timeout: float | timedelta | CancellationToken | None = None,
            token: CancellationToken | None = None,
    ) -> Task[bool]:
        """Asynchronously wait to enter the semaphore.

        The returned task completes with ``True`` once entered, ``False`` if ``timeout``
        elapses first, or is cancelled when ``token`` is. Argument errors are raised
        eagerly. ``wait_async(token)`` is accepted as the token-only overload.
        """
        if isinstance(timeout, _task.CancellationToken):
            timeout, token = None, timeout
        seconds = _to_seconds(timeout)
        token = _token(token)
        self._check_disposed()
        if token.is_cancellation_requested:
            source: _task.TaskCompletionSource[bool] = _task.TaskCompletionSource()
            source.set_canceled(token)
            return source.task
        with self._lock:
            task, waiter = self._wait_async_locked(seconds, token)
        if waiter is not None:
            self._watch(waiter, seconds, token)
        return task

    def _wait_async_locked(
            self, seconds: float | None, token: CancellationToken
    ) -> tuple[Task[bool], _AsyncWaiter | None]:
        """Lock held. Returns the task and, if it needs a timer/cancellation watch, its waiter."""
        if self._current_count > 0:
            self._current_count -= 1
            if self._wait_handle is not None and self._current_count == 0:
                self._wait_handle.reset()
            return _completed(True), None
        if seconds == 0:
            return _completed(False), None
        waiter = _AsyncWaiter()
        tail = self._async_tail
        if tail is None:
            self._async_head = self._async_tail = waiter
        else:
            tail.next = waiter
            waiter.prev = tail
            self._async_tail = waiter
        needs_watch = seconds is not None or token.can_be_cancelled
        return waiter.source.task, (waiter if needs_watch else None)

    def _watch(self, waiter: _AsyncWaiter, seconds: float | None, token: CancellationToken) -> None:
        """Arm the timeout and cancellation of an async waiter. Called outside the lock.

        Whoever removes the waiter from the list first decides its outcome: ``release``
        (entered), the timer (``False``) or the token (cancelled). That race is what
        keeps a timed-out or cancelled waiter from swallowing a released count.
        """
        if seconds is not None:
            waiter.timer = _task._timers.schedule(seconds, lambda: self._abandon(waiter, None))
        if token.can_be_cancelled:
            # Runs synchronously if the token was cancelled meanwhile.
            waiter.registration = token.register(lambda: self._cancel_later(waiter, token))
        if waiter.source.task.done():
            waiter.release_handles()  # completed while the handles were being attached

    def _cancel_later(self, waiter: _AsyncWaiter, token: CancellationToken) -> None:
        """Resolve a cancelled async wait on the pool, never on the thread calling ``cancel()``.

        .NET forces this step to yield (``ConfigureAwait(ForceYielding)``), so the
        cancelled waiter's continuations never run inside ``cancel()``, and a later
        cancellation callback (one that calls ``release()``, say) still runs first.
        """
        try:
            _task.Task.run(self._abandon, waiter, token)
        except RuntimeError:  # the runtime is shutting down: resolve here instead
            self._abandon(waiter, token)

    def _abandon(self, waiter: _AsyncWaiter, token: CancellationToken | None) -> None:
        """Timer or cancellation fired for ``waiter``."""
        with self._lock:
            won = self._remove_async_waiter(waiter)
        if not won:
            return  # release() already handed this waiter a count
        if token is None:
            waiter.source.try_set_result(False)
        else:
            waiter.source.try_set_canceled(token)
        waiter.release_handles()

    def _remove_async_waiter(self, waiter: _AsyncWaiter) -> bool:
        """Unlink ``waiter``. Lock held. ``True`` if it was still in the list."""
        was_in_list = self._async_head is waiter or waiter.prev is not None
        if waiter.next is not None:
            waiter.next.prev = waiter.prev
        if waiter.prev is not None:
            waiter.prev.next = waiter.next
        if self._async_head is waiter:
            self._async_head = waiter.next
        if self._async_tail is waiter:
            self._async_tail = waiter.prev
        waiter.next = waiter.prev = None
        return was_in_list

    # --- release ---------------------------------------------------------------------------------

    def release(self, release_count: int = 1) -> int:
        """Exit the semaphore ``release_count`` times; returns the previous count."""
        self._check_disposed()
        if release_count < 1:
            raise ArgumentOutOfRangeError("releaseCount", "The releaseCount argument must be greater than zero.")
        granted: list[_AsyncWaiter] = []
        with self._lock:
            current_count = return_count = self._current_count
            if self._max_count - current_count < release_count:
                raise SemaphoreFullError()
            current_count += release_count

            # Wake synchronous waiters first, minus those already pulsed but not yet awake.
            wait_count = self._wait_count
            to_notify = min(current_count, wait_count) - self._pulsed_to_wake
            if to_notify > 0:
                to_notify = min(to_notify, release_count)
                self._pulsed_to_wake += to_notify
                self._lock.notify(to_notify)

            # Hand the rest to async waiters, assuming every sync waiter will take a count.
            budget = current_count - wait_count
            while budget > 0 and self._async_head is not None:
                waiter = self._async_head
                self._remove_async_waiter(waiter)
                current_count -= 1
                budget -= 1
                # Continuations go to the pool: no awaiting code runs on this thread.
                waiter.source.try_set_result(True)
                granted.append(waiter)

            self._current_count = current_count
            if self._wait_handle is not None and return_count == 0 and current_count > 0:
                self._wait_handle.set()
        for waiter in granted:
            waiter.release_handles()
        return return_count

    # --- disposal ----------------------------------------------------------------------------------

    def dispose(self) -> None:
        """Release the wait handle; further waits and releases raise ``ObjectDisposedError``."""
        handle = self._wait_handle
        if handle is not None:
            handle.dispose()
            self._wait_handle = None
        self._disposed = True
        self._async_head = self._async_tail = None

    close = dispose

    def __enter__(self) -> SemaphoreSlim:
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()

    def _check_disposed(self) -> None:
        if self._disposed:
            raise ObjectDisposedError(type(self).__name__)

    def __repr__(self) -> str:
        return f"SemaphoreSlim(current_count={self._current_count})"


def _token(token: CancellationToken | None) -> CancellationToken:
    if token is None:
        return _task._NONE_TOKEN
    if not isinstance(token, _task.CancellationToken):
        raise TypeError("token must be a CancellationToken or None")
    return token
