"""flpit.asyncio_bridge: values per loop - Loop[T] parameters, PerLoop[T], provide() and warm loops."""
from __future__ import annotations

import asyncio
import select
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from flpit import asyncio_bridge
from flpit.asyncio_bridge import Loop, LoopStartError, PerLoop, injected, provide, run_asyncio
from flpit.task import AggregateError, Task, asyncio_task

BACKENDS = ["strands", "threads"] if hasattr(select, "epoll") else ["threads"]


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> Iterator[str]:
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=2, backend=request.param)
    yield str(request.param)
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=None, backend=asyncio_bridge._DEFAULT_BACKEND)
    asyncio_bridge._providers.clear()
    for per_loop in list(asyncio_bridge._warm_per_loops):
        per_loop.close()


def result_of(task: Task[Any], timeout: float = 10) -> Any:
    try:
        finished = task.wait(timeout)
    except AggregateError:
        finished = True
    assert finished, "timed out"
    return task.result()


class Client:
    """A loop-bound stand-in: remembers its loop and refuses to be used on another."""

    created: list[Client] = []

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.closed_on: asyncio.AbstractEventLoop | None = None
        Client.created.append(self)

    async def call(self) -> Client:
        assert asyncio.get_running_loop() is self.loop, "used on a foreign loop"
        await asyncio.sleep(0.001)
        return self

    async def aclose(self) -> None:
        self.closed_on = asyncio.get_running_loop()


@pytest.fixture(autouse=True)
def fresh_clients() -> None:
    Client.created = []


# -- Loop[T] parameters -----------------------------------------------------------------------------

def test_a_loop_parameter_receives_the_value_of_the_loop_the_call_runs_on(backend: str) -> None:
    provide(Client, Client)

    @asyncio_task
    async def use(client: Loop[Client] = injected) -> tuple[Client, asyncio.AbstractEventLoop]:
        return await client.call(), asyncio.get_running_loop()

    results = [result_of(t) for t in [use() for _ in range(40)]]
    assert all(client.loop is loop for client, loop in results)
    assert len(Client.created) == len({id(loop) for _, loop in results})  # one per loop, reused


def test_a_value_the_caller_passes_wins(backend: str) -> None:
    provide(Client, Client)
    mine = object()

    @asyncio_task
    async def use(client: Loop[Client] = injected) -> object:
        return client

    assert result_of(use(mine)) is mine
    assert result_of(use(client=mine)) is mine


def test_other_parameters_and_wrong_arguments(backend: str) -> None:
    provide(Client, Client)

    @asyncio_task
    async def use(a: int, client: Loop[Client] = injected, *, b: int = 0) -> int:
        await client.call()
        return a + b

    assert result_of(use(1, b=2)) == 3
    with pytest.raises(TypeError):
        use(1, 2, 3)  # wrong arguments fail in the caller, as for any function


def test_a_loop_parameter_without_a_provider_fails_the_call(backend: str) -> None:
    @asyncio_task
    async def use(client: Loop[Client] = injected) -> None:
        pass

    with pytest.raises(LookupError, match="provide"):
        result_of(use())


def test_providing_again_replaces_and_closes_the_old_values(backend: str) -> None:
    provide(Client, Client)

    @asyncio_task
    async def use(client: Loop[Client] = injected) -> Client:
        return await client.call()

    old = result_of(use())
    provide(Client, Client)
    new = result_of(use())
    assert new is not old
    deadline = time.monotonic() + 5
    while old.closed_on is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert old.closed_on is old.loop


def test_functions_without_loop_parameters_are_unchanged(backend: str) -> None:
    @asyncio_task
    async def plain(x: int) -> int:
        return x * 2

    assert result_of(plain(21)) == 42


# -- PerLoop[T] ---------------------------------------------------------------------------------------

class Singleton:
    def __init__(self, clients: PerLoop[Client]) -> None:
        self.clients = clients

    @asyncio_task
    async def call(self) -> Client:
        return await self.clients.current.call()


def test_a_singleton_uses_the_current_loops_value(backend: str) -> None:
    api = Singleton(PerLoop(Client))
    clients = [result_of(t) for t in [api.call() for _ in range(40)]]
    assert len({id(c) for c in clients}) == len(Client.created) <= 2


def test_current_outside_asyncio_code_fails() -> None:
    with pytest.raises(RuntimeError, match="asyncio event loop"):
        _ = PerLoop(Client).current


def test_an_async_factory_needs_warm_or_get(backend: str) -> None:
    async def make() -> Client:
        return Client()

    cold = PerLoop(make)

    async def read_current() -> Client:
        return cold.current

    with pytest.raises(RuntimeError, match="warm=True"):
        result_of(run_asyncio(read_current()))

    async def read_get() -> Client:
        return await cold.get()

    assert isinstance(result_of(run_asyncio(read_get())), Client)


def test_close_closes_every_loops_value_on_its_loop(backend: str) -> None:
    clients = PerLoop(Client)
    api = Singleton(clients)
    used = {id(c): c for c in [result_of(t) for t in [api.call() for _ in range(40)]]}
    clients.close()
    assert all(c.closed_on is c.loop for c in used.values())
    with pytest.raises(RuntimeError, match="closed"):
        result_of(api.call())


# -- warm loops ---------------------------------------------------------------------------------------

def test_warm_values_exist_before_the_first_call(backend: str) -> None:
    started = threading.Event()

    async def slow_factory() -> Client:
        started.set()
        await asyncio.sleep(0.05)
        return Client()

    clients = PerLoop(slow_factory, warm=True)

    async def first_call() -> Client:
        return clients.current  # an async factory: only works if the loop was warmed first

    values = [result_of(t) for t in [run_asyncio(first_call()) for _ in range(20)]]
    assert started.is_set()
    assert all(v.loop is not None for v in values)
    assert len(Client.created) == len({id(v) for v in values})


def test_warm_reaches_loops_that_exist_already(backend: str) -> None:
    result_of(Task.when_all(*[run_asyncio(asyncio.sleep(0.01)) for _ in range(10)]))
    existing = list(asyncio_bridge._get_pool().loops)

    async def make() -> Client:
        return Client()

    clients = PerLoop(make, warm=True)
    deadline = time.monotonic() + 5
    while len(Client.created) < len(existing) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert {id(c.loop) for c in Client.created} == {id(loop) for loop in existing}

    async def read() -> Client:
        return clients.current

    for _ in range(10):
        result_of(run_asyncio(read()))


def test_a_failing_warm_factory_fails_the_waiting_work_and_replaces_the_loop(backend: str) -> None:
    fail = [True]

    async def make() -> Client:
        if fail[0]:
            raise ConnectionError("database down")
        return Client()

    clients = PerLoop(make, warm=True)  # noqa: F841 - kept alive: an unreferenced PerLoop warms nothing
    with pytest.raises(LoopStartError) as caught:
        result_of(run_asyncio(asyncio.sleep(0)))
    assert isinstance(caught.value.__cause__, ConnectionError)
    deadline = time.monotonic() + 5
    while asyncio_bridge._get_pool().loops and time.monotonic() < deadline:
        time.sleep(0.01)
    assert asyncio_bridge._get_pool().loops == []  # taken out of service
    fail[0] = False
    assert result_of(run_asyncio(asyncio.sleep(0, "ok"))) == "ok"  # a new loop, warmed fine


def test_loops_created_after_shutdown_are_warmed_again(backend: str) -> None:
    clients = PerLoop(Client, warm=True)

    async def read() -> Client:
        return clients.current

    first = result_of(run_asyncio(read()))
    asyncio_bridge.shutdown()
    assert first.closed_on is first.loop  # closed with its loop
    second = result_of(run_asyncio(read()))
    assert second is not first and second.loop is not first.loop
