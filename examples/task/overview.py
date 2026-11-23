"""Short Task runtime snippets, included by docs/task/index.md."""
import time

# --8<-- [start:when_all]
from flpit.task import Task, task


@task                                    # a plain blocking function becomes a Task factory
def fetch(page: int, delay: float = 0.1) -> str:
    time.sleep(delay)
    return f"page {page}"


# Five calls start at once on the worker pool: about 0.1 s in total, not 0.5 s.
pages = Task.when_all([fetch(n) for n in range(5)]).result()
assert pages == ["page 0", "page 1", "page 2", "page 3", "page 4"]   # in input order
# --8<-- [end:when_all]

# --8<-- [start:when_any]
winner = Task.when_any(fetch(1, delay=0.5), fetch(2, delay=0.05)).result()
assert winner.result() == "page 2"       # the first Task to complete
# --8<-- [end:when_any]


# --8<-- [start:when_each]
async def main() -> None:
    tasks = [fetch(1, delay=0.3), fetch(2, delay=0.05)]

    # Tasks arrive as they complete, not in input order.
    finished = [t.result() async for t in Task.when_each(tasks)]
    assert finished == ["page 2", "page 1"]


Task.run(main).result()
# --8<-- [end:when_each]

# --8<-- [start:operators]
from flpit import flp


@task
def nap(seconds: float) -> float:
    time.sleep(seconds)
    return seconds


# A query of tasks ends in the wait, the same way it would in .NET.
results = flp.it([0.2, 0.1, 0.05]).select(nap).when_all().result()      # in query order
first = flp.it([0.5, 0.05]).select(nap).when_any().result()             # the first Task to complete
# --8<-- [end:operators]
assert results == [0.2, 0.1, 0.05]
assert first.result() == 0.05

# --8<-- [start:select_await]
async def await_each() -> None:
    # One at a time, like .NET SelectAwait: nap(0.1) is not called until nap(0.05) has returned.
    in_order = await flp.it([0.05, 0.1]).select_await(nap).to_list()

    # All at once: select starts the tasks, when_each() hands them over as they finish,
    # and select_await awaits each one.
    as_finished = await flp.it([0.2, 0.05]).select(nap).when_each().select_await().to_list()
# --8<-- [end:select_await]
    assert in_order == [0.05, 0.1]
    assert as_finished == [0.05, 0.2]


Task.run(await_each).result()

# --8<-- [start:cancel]
from flpit.task import CancellationTokenSource, OperationCanceledError

cts = CancellationTokenSource()
cts.cancel_after(0.05)

delay = Task.delay(5, token=cts.token)
try:
    delay.result()
except OperationCanceledError:
    pass

assert delay.status == "cancelled"       # cut short after 50 ms
# --8<-- [end:cancel]

# --8<-- [start:continue_with]
squared = fetch(3).continue_with(lambda antecedent: len(antecedent.result()))
assert squared.result() == 6                 # len("page 3"), computed when fetch(3) completed
# --8<-- [end:continue_with]

# --8<-- [start:wait]
slow = fetch(1, delay=0.3)
assert slow.wait(0.01) is False              # timed out; the task keeps running
assert Task.wait_all([slow], timeout=2)      # True once everything has completed
# --8<-- [end:wait]

# --8<-- [start:long_running]
from flpit.task import TaskCreationOptions

# Blocking work that runs for a long time gets its own thread instead of occupying a pool worker.
dedicated = Task.run(time.sleep, 0.05, creation_options=TaskCreationOptions.LONG_RUNNING)
dedicated.result()
# --8<-- [end:long_running]

# --8<-- [start:run_inline]
async def handle(request: str, cache: dict[str, str]) -> str:
    if request in cache:
        return cache[request]               # never suspends: done before run_inline returns
    await Task.delay(0.01)                  # a real suspension: the rest runs on the pool
    cache[request] = f"fresh {request}"
    return cache[request]


def on_worker() -> None:                    # e.g. a web framework handling a request
    cache = {"home": "cached home"}

    hit = Task.run_inline(handle, "home", cache)
    assert hit.status == Task.SUCCEEDED      # ran right here, no queue hop, no wake-up

    miss = Task.run_inline(handle("about", cache))   # a coroutine object works too
    assert not miss.done()                   # suspended in Task.delay; the caller goes on
    assert miss.result() == "fresh about"


Task.run(on_worker).result()
# --8<-- [end:run_inline]
