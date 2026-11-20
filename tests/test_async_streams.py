"""
Async streams on the flpit runtime: the three layers that give ``async for`` the
cleanup C#'s ``await foreach`` has.

1. Runtime hooks: an async generator left early (``break``, ``return``, an exception)
   is closed with ``aclose()`` on the pool, so awaiting ``finally`` blocks run.
2. ``@async_flpit``: an async generator function returning an ``AsyncFlpIt``.
3. Deterministic scopes: ``async with query.get_async_enumerator()`` (block) and
   ``@await_using`` (function).
"""
from __future__ import annotations

import sys
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import pytest

from flpit import AsyncEnumerator, AsyncFlpIt, async_flpit
from flpit.task import (
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskCreationOptions,
    await_using,
)

EVENTUALLY = 5.0  # seconds; background closing normally finishes within milliseconds


def run[T](body: Callable[[], Awaitable[T]]) -> T:
    """Run ``body`` (a coroutine function, or a lambda returning a Task) and wait for its result."""
    return cast(T, Task.run(body).result())


class Probe:
    """Records what a stream did; ``closed`` is set when its ``finally`` has completed."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.closed = threading.Event()

    async def stream(self, name: str, count: int = 10) -> AsyncIterator[int]:
        try:
            for i in range(1, count + 1):
                await Task.delay(0.001)
                yield i
        finally:
            await Task.delay(0.01)  # an *awaiting* finally: only aclose() can run it
            self.log.append(f"{name} closed")
            self.closed.set()


@pytest.fixture
def unraisable() -> Any:
    """Collect 'Exception ignored in ...' reports, e.g. 'async generator ignored GeneratorExit'."""
    seen: list[Any] = []
    previous = sys.unraisablehook
    sys.unraisablehook = seen.append
    try:
        yield seen
    finally:
        sys.unraisablehook = previous


# =============================================================================
# 1. Runtime hooks
# =============================================================================

def test_break_closes_the_generator_and_runs_an_awaiting_finally(unraisable: list[Any]) -> None:
    probe = Probe()

    async def consume() -> None:
        async for i in probe.stream("s"):
            if i == 3:
                break

    run(consume)
    assert probe.closed.wait(EVENTUALLY)
    assert probe.log == ["s closed"]
    assert unraisable == []


def test_exception_in_the_loop_body_closes_the_generator(unraisable: list[Any]) -> None:
    probe = Probe()

    async def consume() -> None:
        async for i in probe.stream("s"):
            if i == 2:
                raise ValueError("stop")

    with pytest.raises(ValueError, match="stop"):
        run(consume)
    assert probe.closed.wait(EVENTUALLY)
    assert unraisable == []


def test_generator_on_a_long_running_thread_is_closed_too(unraisable: list[Any]) -> None:
    probe = Probe()

    async def consume() -> None:
        async for i in probe.stream("s"):
            if i == 2:
                break

    Task.run(consume, creation_options=TaskCreationOptions.LONG_RUNNING).result()
    assert probe.closed.wait(EVENTUALLY)
    assert unraisable == []


def test_error_while_closing_in_the_background_reaches_the_exception_handler() -> None:
    reported: list[dict[str, Any]] = []
    done = threading.Event()

    def handler(context: dict[str, Any]) -> None:
        reported.append(context)
        done.set()

    async def failing() -> AsyncIterator[int]:
        try:
            yield 1
            yield 2
        finally:
            await Task.delay(0.001)
            raise RuntimeError("cleanup failed")

    async def consume() -> None:
        async for _ in failing():
            break

    Task.set_exception_handler(handler)
    try:
        run(consume)
        assert done.wait(EVENTUALLY)
    finally:
        Task.set_exception_handler(None)
    assert "closing async generator" in reported[0]["message"]
    assert isinstance(reported[0]["exception"], RuntimeError)


def test_shutdown_closes_suspended_generators() -> None:
    probe = Probe()
    keep: list[Any] = []

    async def park() -> None:
        stream = probe.stream("parked")
        keep.append(stream)  # still referenced: only shutdown can close it
        await stream.__anext__()

    run(park)
    assert not probe.closed.is_set()
    report = Task.shutdown(grace_timeout=2.0, worker_timeout=1.0)
    assert probe.log == ["parked closed"]
    assert not report.timed_out


# =============================================================================
# 2. @async_flpit
# =============================================================================

def test_async_flpit_returns_a_cold_reenumerable_AsyncFlpIt() -> None:
    calls: list[int] = []

    @async_flpit
    async def numbers(n: int) -> AsyncIterator[int]:
        calls.append(n)
        for i in range(n):
            yield i

    query = numbers(3)
    assert isinstance(query, AsyncFlpIt)
    assert calls == []  # cold: nothing runs before enumeration

    async def body() -> tuple[list[int], list[int]]:
        return [i async for i in query], [i async for i in query]

    assert run(body) == ([0, 1, 2], [0, 1, 2])
    assert calls == [3, 3]  # each enumeration calls the generator function anew


def test_async_flpit_keeps_name_and_doc_and_checks_arguments_at_call_time() -> None:
    @async_flpit
    async def numbers(n: int) -> AsyncIterator[int]:
        """Docs."""
        yield n

    assert numbers.__name__ == "numbers"
    assert numbers.__doc__ == "Docs."
    with pytest.raises(TypeError):
        numbers()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        numbers(1, 2)  # type: ignore[call-arg]


def test_async_flpit_rejects_functions_that_are_not_async_generators() -> None:
    async def coroutine() -> int:
        return 1

    def generator() -> Any:
        yield 1

    for function in (coroutine, generator, lambda: None):
        with pytest.raises(TypeError, match="async generator"):
            async_flpit(function)  # type: ignore[arg-type]


def test_async_flpit_passes_the_enumeration_token() -> None:
    seen: list[CancellationToken] = []

    @async_flpit
    async def numbers(token: CancellationToken = CancellationToken.none()) -> AsyncIterator[int]:
        seen.append(token)
        yield 1

    cts = CancellationTokenSource()

    async def body() -> None:
        async for _ in numbers():
            pass
        async for _ in numbers().with_cancellation(cts.token):
            pass
        await numbers().to_list(token=cts.token)

    run(body)
    assert seen[0] is CancellationToken.none()
    assert seen[1] is cts.token
    assert seen[2] is cts.token


def test_async_flpit_links_an_explicit_token_with_the_enumeration_token() -> None:
    @async_flpit
    async def forever(token: CancellationToken = CancellationToken.none()) -> AsyncIterator[int]:
        while True:
            await Task.delay(0.01, token=token)
            yield 1

    for cancel_explicit in (True, False):
        explicit = CancellationTokenSource()
        enumeration = CancellationTokenSource()

        async def body() -> None:
            async for _ in forever(token=explicit.token).with_cancellation(enumeration.token):
                (explicit if cancel_explicit else enumeration).cancel()

        with pytest.raises(OperationCanceledError):
            run(body)


def test_async_flpit_uses_an_explicit_token_alone_when_the_enumeration_has_none() -> None:
    seen: list[CancellationToken] = []

    @async_flpit
    async def numbers(token: CancellationToken = CancellationToken.none()) -> AsyncIterator[int]:
        seen.append(token)
        yield 1

    cts = CancellationTokenSource()
    run(lambda: numbers(token=cts.token).to_list())
    assert seen == [cts.token]


def test_linq_operators_close_an_async_flpit_source_before_completing() -> None:
    probe = Probe()

    @async_flpit
    async def numbers() -> AsyncIterator[int]:
        async for i in probe.stream("source"):
            yield i

    assert run(lambda: numbers().where(lambda i: i % 2 == 0).first()) == 2
    assert probe.log == ["source closed"]  # closed before first() returned


def test_async_flpit_closes_streams_its_body_iterated_first_then_itself() -> None:
    probe = Probe()

    @async_flpit
    async def outer() -> AsyncIterator[int]:
        try:
            async for i in probe.stream("inner"):  # C#: await foreach inside the iterator
                yield i
        finally:
            probe.log.append("outer finally")

    assert run(lambda: outer().first()) == 1
    assert probe.log == ["inner closed", "outer finally"]  # C# order: inner disposed first


def test_async_flpit_owns_streams_started_by_coroutines_it_awaits() -> None:
    probe = Probe()

    async def first_two(stream: AsyncIterator[int]) -> list[int]:
        items = []
        async for i in stream:
            items.append(i)
            if len(items) == 2:
                break
        return items

    @async_flpit
    async def outer() -> AsyncIterator[list[int]]:
        yield await first_two(probe.stream("helper"))  # started inside a helper coroutine
        yield [99]

    assert run(lambda: outer().first()) == [1, 2]
    assert probe.log == ["helper closed"]


# =============================================================================
# 3a. Block scope: async with query.get_async_enumerator()
# =============================================================================

def test_get_async_enumerator_returns_an_AsyncEnumerator() -> None:
    enumerator = AsyncFlpIt([1, 2]).get_async_enumerator()
    assert isinstance(enumerator, AsyncEnumerator)
    assert run(lambda: _drain(enumerator)) == [1, 2]


async def _drain(enumerator: AsyncEnumerator[int]) -> list[int]:
    try:
        return [i async for i in enumerator]
    finally:
        await enumerator.aclose()


def test_async_with_closes_before_the_next_statement() -> None:
    probe = Probe()

    @async_flpit
    async def numbers() -> AsyncIterator[int]:
        async for i in probe.stream("s"):
            yield i

    async def body() -> list[str]:
        async with numbers().get_async_enumerator() as items:
            async for i in items:
                if i == 3:
                    break
        return list(probe.log)  # what had happened by the statement after the block

    assert run(body) == ["s closed"]


def test_async_with_closes_when_the_block_raises() -> None:
    probe = Probe()

    @async_flpit
    async def numbers() -> AsyncIterator[int]:
        async for i in probe.stream("s"):
            yield i

    async def body() -> None:
        async with numbers().get_async_enumerator() as items:
            async for _ in items:
                raise ValueError("stop")

    with pytest.raises(ValueError, match="stop"):
        run(body)
    assert probe.log == ["s closed"]


# =============================================================================
# 3b. Function scope: @await_using
# =============================================================================

def test_await_using_closes_every_stream_last_first_before_returning() -> None:
    probe = Probe()

    @await_using
    async def consume() -> str:
        a = probe.stream("a")  # still referenced: layer 1 alone could not close it
        async for i in a:
            if i == 2:
                break
        async for i in probe.stream("b"):
            if i == 2:
                break
        return "result"

    async def body() -> tuple[str, list[str]]:
        result = await consume()
        return result, list(probe.log)

    assert run(body) == ("result", ["b closed", "a closed"])


def test_await_using_closes_streams_when_the_body_raises() -> None:
    probe = Probe()

    @await_using
    async def consume() -> None:
        async for _ in probe.stream("s"):
            raise ValueError("stop")

    async def body() -> list[str]:
        with pytest.raises(ValueError, match="stop"):
            await consume()
        return list(probe.log)

    assert run(body) == ["s closed"]


def test_await_using_raises_an_error_from_closing() -> None:
    async def failing() -> AsyncIterator[int]:
        try:
            yield 1
            yield 2
        finally:
            raise RuntimeError("cleanup failed")

    @await_using
    async def consume() -> None:
        async for _ in failing():
            break

    with pytest.raises(RuntimeError, match="cleanup failed"):
        run(consume)


def test_await_using_leaves_streams_of_other_tasks_and_earlier_streams_alone() -> None:
    probe = Probe()
    started_before = probe.stream("before")
    child_stream: list[Any] = []

    async def child() -> None:
        stream = probe.stream("child")
        child_stream.append(stream)
        await stream.__anext__()

    @await_using
    async def consume() -> None:
        await started_before.__anext__()  # first iterated before the call: not ours
        await Task.run(child)  # first iterated by another task: not ours

    async def body() -> list[str]:
        await started_before.__anext__()
        await consume()
        return list(probe.log)

    assert run(body) == []
    assert child_stream[0].ag_frame is not None  # still suspended, not closed


def test_await_using_rejects_functions_that_are_not_coroutines() -> None:
    def plain() -> None:
        pass

    async def generator() -> AsyncIterator[int]:
        yield 1

    for function in (plain, generator):
        with pytest.raises(TypeError, match="async def"):
            await_using(function)  # type: ignore[arg-type]
