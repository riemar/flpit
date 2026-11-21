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


# --8<-- [start:collect]
async def main() -> None:
    tasks = [fetch(1, delay=0.3), fetch(2, delay=0.05)]

    # Tasks arrive as they complete, not in input order.
    finished = [t.result() async for t in Task.collect(tasks)]
    assert finished == ["page 2", "page 1"]


Task.run(main).result()
# --8<-- [end:collect]

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
