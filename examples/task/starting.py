"""Ways to start work, included by docs/task/starting-work.md."""
import threading
import time

from flpit.task import Task, task
from flpit.threading import ThreadPool


# --8<-- [start:await]
async def load(key: str) -> str:
    return f"value of {key}"


async def handler() -> str:
    return await load("a")        # runs right here, no Task: the same as C# `await LoadAsync()`


assert Task.run(handler).result() == "value of a"
# --8<-- [end:await]


# --8<-- [start:cold]
async def side_effect(log: list[str]) -> None:
    log.append("ran")


log: list[str] = []
coroutine = side_effect(log)      # Python: nothing runs yet (C#: it would already have run)
assert log == []
Task.run(coroutine).wait()        # started only now
assert log == ["ran"]
# --8<-- [end:cold]


# --8<-- [start:run]
def resize(image: str) -> str:
    time.sleep(0.05)              # blocking or CPU-heavy work
    return f"small {image}"


# Queued to the pool, whatever kind of function it is: the caller is free at once.
thumbnails = Task.when_all([Task.run(resize, name) for name in ("a", "b", "c")]).result()
assert thumbnails == ["small a", "small b", "small c"]   # about 0.05 s, not 0.15 s
# --8<-- [end:run]


# --8<-- [start:task]
@task                             # every call is Task.run(resize_task, ...)
def resize_task(image: str) -> str:
    time.sleep(0.05)
    return f"small {image}"


@task                             # the same for async def: the whole body runs on the pool
async def checksum(data: bytes) -> int:
    total = sum(data)             # CPU work before the first await runs in parallel, too
    await Task.yield_now()
    return total


assert Task.when_all(resize_task("a"), resize_task("b")).result() == ["small a", "small b"]
assert checksum(bytes(range(10))).result() == 45
# --8<-- [end:task]


# --8<-- [start:inline]
cache = {"home": "<h1>cached</h1>"}


@task(inline=True)                # every call is Task.run_inline(render, ...)
async def render(page: str) -> str:
    if page in cache:
        return cache[page]        # never suspends: done when render() returns
    await Task.delay(0.01)        # first real suspension: the rest runs on the pool
    cache[page] = f"<h1>{page}</h1>"
    return cache[page]


def on_worker() -> None:
    hit = render("home")
    assert hit.done()             # no queue hop, no wake-up
    miss = render("about")
    assert not miss.done()        # suspended in Task.delay; the caller goes on
    assert miss.result() == "<h1>about</h1>"

    started = Task.run_inline(render("contact"))   # the same for a single call or a coroutine object
    assert started.result() == "<h1>contact</h1>"


Task.run(on_worker).result()
# --8<-- [end:inline]


# --8<-- [start:order]
def start_order() -> list[str]:
    log: list[str] = []

    @task(inline=True)
    async def foo() -> None:
        log.append("foo: before await")
        await Task.delay(0.02)
        log.append("foo: after await")

    @task(inline=True)
    async def bar() -> None:
        log.append("bar: before await")
        await Task.delay(0.01)
        log.append("bar: after await")

    a = foo()                     # foo runs to its first await, then returns
    b = bar()                     # only now does bar start
    log.append("caller: both started")
    Task.when_all(a, b).wait()    # after their first await they overlap
    return log


assert Task.run(start_order).result() == [
    "foo: before await", "bar: before await", "caller: both started",
    "bar: after await", "foo: after await",
]
# --8<-- [end:order]


# --8<-- [start:work_item]
done = threading.Event()
ThreadPool.queue(lambda request: done.set(), "GET /")   # no Task at all
assert done.wait(5)
# --8<-- [end:work_item]
