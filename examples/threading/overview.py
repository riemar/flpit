"""Threading primitives, in short."""
import time

# --8<-- [start:semaphore]
from flpit.task import Task
from flpit.threading import SemaphoreSlim

throttle = SemaphoreSlim(2)            # at most two at a time


def limited_work() -> None:
    throttle.wait()                    # blocks until a slot is free
    try:
        time.sleep(0.05)
    finally:
        throttle.release()             # always give the slot back


start = time.perf_counter()
Task.wait_all([Task.run(limited_work) for _ in range(6)])

# Six 50 ms jobs, two at a time, need at least three rounds (0.14 leaves slack for the timer).
assert time.perf_counter() - start >= 0.14
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

# --8<-- [start:event]
from flpit.threading import ManualResetEvent

start = ManualResetEvent()             # not signaled yet
started: list[int] = []


def runner(n: int) -> None:
    start.wait_one()                   # blocks until the event is set
    started.append(n)


runners = [Task.run(runner, n) for n in range(3)]
time.sleep(0.05)
assert started == []                   # everyone is still waiting

start.set()                            # one signal releases all of them
Task.wait_all(runners)
assert sorted(started) == [0, 1, 2]

start.reset()
assert start.wait_one(0.01) is False   # unsignaled again: a wait with a timeout gives up
# --8<-- [end:event]

# --8<-- [start:async_local]
from flpit.threading import AsyncLocal

request_id = AsyncLocal[str]()


async def handle(rid: str) -> str:
    request_id.value = rid             # set once ...
    await Task.delay(0.02)             # ... the task may resume on another pool worker
    return request_id.value            # ... and still sees its own value


async def serve() -> None:
    request_id.value = "main"
    a, b = Task.run(handle, "a"), Task.run(handle, "b")

    assert await Task.when_all(a, b) == ["a", "b"]   # each task kept its own value
    assert request_id.value == "main"                # and nothing leaked back


Task.run(serve).result()
# --8<-- [end:async_local]
