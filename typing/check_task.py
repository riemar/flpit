from datetime import timedelta

from flpit.task import asyncio_task, Task
from flpit.task import CancellationToken, TaskCanceledError, TaskContinuationOptions, TaskCreationOptions
from flpit import AsyncFlpIt, flp
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
    # @asyncio_task - on async
    # ========================================================
    @asyncio_task
    async def async2(z: dict[str, int]):
        return {next(iter(z.values())): "I am async via io"}

    class ExpectedAsyncIo(Protocol):
        def __call__(self, z: dict[str, int]) -> Task[dict[int, str]]: ...

    assert_type(async2, ExpectedAsyncIo)

    t4 = async2({"who are you?": 1})
    assert_type(t4.result(), dict[int, str])
    assert_type(await t4, dict[int, str])

    # ========================================================
    # when_all / when_any / collect
    # one T when the collection is homogeneous, Any otherwise (like .NET)
    # ========================================================
    same: list[Task[int]] = [Task.run(lambda: 1), Task.run(lambda: 2)]
    mixed: list[Task[Any]] = [sync1(1), async1("x")]

    assert_type(Task.when_all(same), Task[list[int]])
    assert_type(Task.when_all(mixed), Task[list[Any]])
    assert_type(Task.when_all(sync1(1), async1("x")), Task[list[Any]])

    assert_type(Task.when_any(same), Task[Task[int]])
    assert_type(Task.when_any(mixed), Task[Task[Any]])
    assert_type(Task.when_any(sync1(1), async1("x")), Task[Task[Any]])

    assert_type(Task.collect(same), AsyncFlpIt[Task[int]])
    assert_type(Task.collect(mixed), AsyncFlpIt[Task[Any]])
    assert_type(Task.collect(sync1(1), async1("x")), AsyncFlpIt[Task[Any]])

    assert_type(Task.when_each(same), AsyncFlpIt[Task[int]])
    assert_type(Task.when_each(mixed), AsyncFlpIt[Task[Any]])
    assert_type(Task.when_each(sync1(1), async1("x")), AsyncFlpIt[Task[Any]])

    # the query operator: a FlpIt / FlpList of tasks
    assert_type(flp.it(same).when_each(), AsyncFlpIt[Task[int]])
    assert_type(flp.it([1, 2]).select(lambda n: Task.run(lambda: n)).when_each(), AsyncFlpIt[Task[int]])
    assert_type(flp.lst(same).when_each(), AsyncFlpIt[Task[int]])

    # when_all / when_any as query operators
    assert_type(flp.it(same).when_all(), Task[list[int]])
    assert_type(flp.it(same).when_any(), Task[Task[int]])
    assert_type(flp.lst(same).when_all(), Task[list[int]])
    assert_type(flp.lst(same).when_any(), Task[Task[int]])
    assert_type(flp.it([1, 2]).select(lambda n: Task.run(lambda: n)).when_all(), Task[list[int]])
    assert_type(flp.it([1, 2]).select(lambda n: Task.run(lambda: n)).when_any(), Task[Task[int]])

    # select_await / where_await
    assert_type(flp.it(same).select_await(lambda t: t), AsyncFlpIt[int])
    assert_type(flp.lst(same).select_await(lambda t: t), AsyncFlpIt[int])
    assert_type(flp.it(same).when_each().select_await(lambda t: t), AsyncFlpIt[int])
    assert_type(flp.it(same).when_each().select_await(), AsyncFlpIt[int])
    assert_type(flp.it(same).select_await(), AsyncFlpIt[int])
    assert_type(flp.lst(same).select_await(), AsyncFlpIt[int])
    assert_type(flp.it([1, 2]).where_await(lambda n: Task.run(lambda: n > 1)), AsyncFlpIt[int])
    assert_type(flp.lst([1, 2]).where_await(lambda n: Task.run(lambda: n > 1)), AsyncFlpIt[int])

async def waits_and_continuations():
    t = Task.run(lambda: 42)

    # ========================================================
    # wait / wait_all / wait_any
    # ========================================================
    assert_type(t.wait(), bool)
    assert_type(t.wait(0.1), bool)
    assert_type(t.wait(timedelta(seconds=1), CancellationToken.none()), bool)
    assert_type(Task.wait_all(t, t), bool)
    assert_type(Task.wait_all([t, t], timeout=0.1), bool)
    assert_type(Task.wait_any([t], timeout=0.1), int)

    # ========================================================
    # continue_with - the antecedent is Task[T], the state keeps its type
    # ========================================================
    assert_type(t.continue_with(lambda a: str(a.result())), Task[str])
    assert_type(t.continue_with(lambda a, s: s.upper(), "state"), Task[str])

    async def async_continuation(a: Task[int]) -> float:
        return float(a.result())

    async def async_continuation_with_state(a: Task[int], s: bytes) -> list[bytes]:
        return [s]

    assert_type(t.continue_with(async_continuation), Task[float])  # awaited result, not Task[Task[float]]
    assert_type(t.continue_with(async_continuation_with_state, b"x"), Task[list[bytes]])
    assert_type(
        t.continue_with(
            lambda a: None,
            token=CancellationToken.none(),
            options=TaskContinuationOptions.ONLY_ON_RAN_TO_COMPLETION | TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY,
        ),
        Task[None],
    )
    assert_type(await t.continue_with(lambda a: a.result() * 2), int)

    # ========================================================
    # creation options, completed_task, TaskCanceledError
    # ========================================================
    assert_type(Task.run(lambda: "x", creation_options=TaskCreationOptions.LONG_RUNNING), Task[str])
    assert_type(t.creation_options, TaskCreationOptions)
    assert_type(Task.completed_task, Task[None])

    error = TaskCanceledError(t)
    assert_type(error.task, Task[Any] | None)
    assert_type(error.inner_exception, BaseException | None)

    # ========================================================
    # run_inline: same inference as Task.run, plus coroutine objects
    # ========================================================
    async def answer(x: int) -> str:
        return str(x)

    assert_type(Task.run_inline(answer, 1), Task[str])
    assert_type(Task.run_inline(answer(1)), Task[str])
    assert_type(Task.run_inline(lambda: 42), Task[int])
    assert_type(await Task.run_inline(answer(2)), str)

    # ========================================================
    # @task(inline=True) on async def, @task() as plain @task
    # ========================================================
    @task(inline=True)
    async def inline_answer(x: int) -> str:
        return str(x)

    class ExpectedInline(Protocol):
        def __call__(self, x: int) -> Task[str]: ...

    assert_type(inline_answer, ExpectedInline)
    assert_type(await inline_answer(3), str)

    @task()
    def queued(x: int) -> int:
        return x

    assert_type(queued(1), Task[int])


# ========================================================
# Main startup must not rais an "await missing"
# ========================================================
async def main():
    ...

Task.run(waits_and_continuations).result()
Task.run(foo).result()