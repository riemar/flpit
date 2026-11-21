"""Threading primitives, in short."""
import time

# --8<-- [start:semaphore]
from flpit.task import Task
from flpit.threading import SemaphoreSlim

throttle = SemaphoreSlim(2)            # at most two at a time
running = peak = 0


def limited_work() -> None:
    global running, peak
    throttle.wait()                    # blocks until a slot is free
    try:
        running += 1
        peak = max(peak, running)
        time.sleep(0.02)
        running -= 1
    finally:
        throttle.release()             # always give the slot back


Task.wait_all([Task.run(limited_work) for _ in range(6)])
assert peak <= 2
# --8<-- [end:semaphore]

# --8<-- [start:async_semaphore]
async def fetch(n: int) -> int:
    await throttle.wait_async()        # the awaitable counterpart of wait()
    try:
        return n * 2
    finally:
        throttle.release()


assert Task.run(fetch, 21).result() == 42
# --8<-- [end:async_semaphore]

# --8<-- [start:thread_local]
from flpit.threading import ThreadLocal

counter = ThreadLocal(lambda: 0)       # each thread starts with its own 0
counter.value += 1

assert Task.run(lambda: counter.value).result() == 0   # a pool thread does not see this thread's value
assert counter.value == 1
# --8<-- [end:thread_local]
