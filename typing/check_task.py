from flpit.task import asyncio_task, Task
from typing import reveal_type, Protocol, Any, AsyncGenerator
from typing import assert_type, Callable

from flpit.task import task, Task


async def foo():
    # ========================================================
    # Task run - via lambda
    # ========================================================
    t1 = Task.run(lambda: 42)

    assert_type(t1, Task[int])
    assert_type(t1.result(), int)

    assert_type(await t1, int)

    # ========================================================
    # @task - on sync
    # ========================================================
    @task
    def sync1(x: int):
        return "I am sync"

    class ExpectedSync(Protocol):
        def __call__(self, x: int) -> Task[str]: ...

    assert_type(sync1, ExpectedSync)

    t2 = sync1(1)
    assert_type(t2.result(), str)
    assert_type(await t2, str)

    # ========================================================
    # @task - on async
    # ========================================================
    @task
    async def async1(y: str):
        return ["I am async"]

    class ExpectedAsync(Protocol):
        def __call__(self, y: str) -> Task[list[str]]: ...

    assert_type(async1, ExpectedAsync)

    t3 = async1("who are you?")
    assert_type(t3.result(), list[str])
    assert_type(await t3, list[str])

    # ========================================================
    # @asyncio_task - on sync
    # ========================================================
    @asyncio_task
    def async2(z: dict[str, int]):
        return {next(iter(z.values())): "I am async via io"}

    class ExpectedAsyncIo(Protocol):
        def __call__(self, z: dict[str, int]) -> Task[dict[int, str]]: ...

    assert_type(async2, ExpectedAsyncIo)

    t4 = async2({"who are you?": 1})
    assert_type(t4.result(), dict[int, str])
    assert_type(await t4, dict[int, str])

    # ========================================================
    # when_all 
    # ========================================================

    # todo: 0.2.4 finish when_all to pass type checks
    # wall: Task[list[Any]] = Task.when_all(sync1, async1, async2)

    # ========================================================
    # when_any
    # ========================================================

    # todo: 0.2.4 finish when_any to properly pass type checks
    wany: Task[Task[Any]] = Task.when_any(sync1, async1, async2)

    # ========================================================
    # collect
    # ========================================================

    # todo: 0.2.4 finish collect to pass type checks
    # coll: AsyncGenerator[Task[Any], Any] = Task.collect(sync1, async1, async2)

# ========================================================
# Main startup must not rais an "await missing"
# ========================================================
async def main():
    ...

Task.run(foo).result()