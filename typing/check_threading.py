"""Static inference checks for flpit.threading (run: uv run pyrefly check typing/check_threading.py)."""
from datetime import timedelta
from typing import assert_type

from flpit.task import CancellationToken, Task
from flpit.threading import (
    ManualResetEvent,
    SemaphoreSlim,
    ThreadLocal,
    Timeout,
    WaitHandle,
)

# --- SemaphoreSlim ------------------------------------------------------------------------------
SEMAPHORE = SemaphoreSlim(10, 10)  # enough slots for every call below, so the file also runs

assert_type(SEMAPHORE.current_count, int)
assert_type(SEMAPHORE.wait(), bool)
assert_type(SEMAPHORE.wait(0.1), bool)
assert_type(SEMAPHORE.wait(timedelta(milliseconds=10), CancellationToken.none()), bool)
assert_type(SEMAPHORE.wait(CancellationToken.none()), bool)  # the token-only overload
assert_type(SEMAPHORE.wait_async(), Task[bool])
assert_type(SEMAPHORE.wait_async(Timeout.INFINITE, CancellationToken.none()), Task[bool])
assert_type(SEMAPHORE.release(), int)
assert_type(SEMAPHORE.release(1), int)
assert_type(SEMAPHORE.available_wait_handle, WaitHandle)

with SemaphoreSlim(1) as scoped:
    assert_type(scoped, SemaphoreSlim)


async def throttled() -> None:
    entered = await SEMAPHORE.wait_async(0.1)
    assert_type(entered, bool)


# --- WaitHandle / ManualResetEvent --------------------------------------------------------------
EVENT = ManualResetEvent(False)

assert_type(EVENT.set(), bool)
assert_type(EVENT.reset(), bool)
assert_type(EVENT.wait_one(0), bool)
assert_type(EVENT.wait_one(timedelta(seconds=1)), bool)

# --- ThreadLocal --------------------------------------------------------------------------------
COUNTER = ThreadLocal(lambda: 0)  # T inferred from the value factory
assert_type(COUNTER, ThreadLocal[int])
assert_type(COUNTER.value, int)
assert_type(COUNTER.is_value_created, bool)

TRACKED = ThreadLocal(lambda: "x", track_all_values=True)
assert_type(TRACKED.values, list[str])

NAMES: ThreadLocal[str] = ThreadLocal()  # no factory: the declared type
assert_type(NAMES.value, str)

COUNTS: ThreadLocal[int] = ThreadLocal(default=0)
assert_type(COUNTS.value, int)

COUNTER.value = 1
COUNTER.value += 1

with ThreadLocal(lambda: 1.5) as scoped_local:
    assert_type(scoped_local, ThreadLocal[float])
