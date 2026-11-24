"""flpit.asyncio_bridge: asyncio code on shared loops (strand and thread backends)."""
from __future__ import annotations

import asyncio
import contextvars
import gc
import select
import socket
import threading
import time

import pytest

from flpit import asyncio_bridge
from flpit.asyncio_bridge import LoopLocal, run_asyncio
from flpit.task import (
    AggregateError,
    AsyncLocal,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    asyncio_task,
)

BACKENDS = ["strands", "threads"] if hasattr(select, "epoll") else ["threads"]


@pytest.fixture(params=BACKENDS)
def backend(request):
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=2, backend=request.param)
    yield request.param
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=None, backend=asyncio_bridge._DEFAULT_BACKEND)


def result_of(task: Task, timeout: float):
    """``task.result()`` that fails the test instead of hanging it."""
    try:
        finished = task.wait(timeout)
    except AggregateError:
        finished = True  # failed or cancelled: result() raises the original error
    assert finished, "timed out"
    return task.result()


def loop_count() -> int:
    pool = asyncio_bridge._pool
    return 0 if pool is None else len(pool.loops)


# -- basics ----------------------------------------------------------------------------------------

def test_result_and_shared_loops(backend):
    @asyncio_task
    async def work(i):
        await asyncio.sleep(0.01)
        return i, asyncio.get_running_loop()

    results = [result_of(t, 10) for t in [work(i) for i in range(40)]]
    assert [i for i, _ in results] == list(range(40))
    loops = {id(loop) for _, loop in results}
    assert 1 <= len(loops) <= 2  # shared, never one per call
    assert loop_count() <= 2


def test_lazy_no_loops_until_used(backend):
    assert asyncio_bridge._pool is None
    result_of(run_asyncio(asyncio.sleep(0)), 5)
    assert loop_count() >= 1


def test_exception_propagates(backend):
    @asyncio_task
    async def boom():
        await asyncio.sleep(0)
        raise ValueError("boom")

    t = boom()
    with pytest.raises(ValueError, match="boom"):
        result_of(t, 5)
    assert t.status == "failed"


class _CustomBaseError(BaseException):
    pass


@pytest.mark.parametrize("error", [_CustomBaseError("custom"), KeyboardInterrupt(), SystemExit(3)],
                         ids=["BaseException", "KeyboardInterrupt", "SystemExit"])
def test_non_exception_errors_fail_the_task_and_the_loop_serves_on(backend, error):
    asyncio_bridge.configure(loops=1)

    async def raise_it():
        await asyncio.sleep(0)
        raise error

    t = run_asyncio(raise_it())
    with pytest.raises(type(error)):
        result_of(t, 5)
    assert t.status == "failed"
    assert result_of(run_asyncio(asyncio.sleep(0.01, "still serving")), 5) == "still serving"


def test_awaitable_that_is_not_a_coroutine(backend):
    async def make():
        future = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_later(0.01, future.set_result, 7)
        return await run_asyncio(future)

    assert result_of(run_asyncio(make()), 5) == 7


def test_sockets_timers_and_getaddrinfo(backend):
    async def echo():
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        infos = await asyncio.get_running_loop().getaddrinfo("localhost", port, type=socket.SOCK_STREAM)
        assert infos
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"ping\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 5)
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        return line

    async def handle(reader, writer):
        data = await reader.readline()
        await asyncio.sleep(0.01)
        writer.write(data.upper())
        await writer.drain()
        writer.close()

    assert result_of(run_asyncio(echo()), 10) == b"PING\n"


def test_run_in_executor_uses_flpit_pool(backend):
    async def offload():
        return await asyncio.get_running_loop().run_in_executor(None, lambda: threading.current_thread().name)

    name = result_of(run_asyncio(offload()), 5)
    assert "unused" not in name  # never a thread of asyncio's ThreadPoolExecutor


def test_asyncio_primitives_across_calls_on_one_loop(backend):
    async def scenario():
        queue: asyncio.Queue[int] = asyncio.Queue()
        event = asyncio.Event()

        async def producer():
            for i in range(100):
                await queue.put(i)
            event.set()

        async def consumer():
            await event.wait()
            return [queue.get_nowait() for _ in range(queue.qsize())]

        _, items = await asyncio.gather(producer(), consumer())
        return items

    assert result_of(run_asyncio(scenario()), 5) == list(range(100))


# -- caller's loop -------------------------------------------------------------------------------

def test_inside_asyncio_runs_on_callers_loop(backend):
    @asyncio_task
    async def where():
        return asyncio.get_running_loop()

    async def outer():
        return asyncio.get_running_loop(), await where()

    outer_loop, inner_loop = result_of(run_asyncio(outer()), 5)
    assert outer_loop is inner_loop


def test_foreign_loop_stays_its_own(backend):
    @asyncio_task
    async def where():
        return asyncio.get_running_loop()

    async def main():
        return asyncio.get_running_loop(), await where()

    mine, used = asyncio.run(main())
    assert mine is used
    assert asyncio_bridge._pool is None  # nothing created for code already on a loop


def test_nested_calls(backend):
    @asyncio_task
    async def leaf(i):
        await asyncio.sleep(0)
        return i

    @asyncio_task
    async def branch(n):
        return sum(await asyncio.gather(*(leaf(i) for i in range(n))))

    assert result_of(branch(20), 5) == sum(range(20))


def test_flpit_task_awaits_asyncio_task(backend):
    @asyncio_task
    async def fetch():
        await asyncio.sleep(0.01)
        return 3

    async def flpit_code():  # pure flpit coroutine on the pool
        return await fetch() + await Task.run(lambda: 4)

    assert result_of(Task.run(flpit_code), 5) == 7


# -- context -------------------------------------------------------------------------------------

def test_context_flows_in(backend):
    var: contextvars.ContextVar[str] = contextvars.ContextVar("var", default="unset")
    local: AsyncLocal[str] = AsyncLocal()

    async def read():
        await asyncio.sleep(0)
        return var.get(), local.value

    var.set("caller")
    local.value = "flpit"
    assert result_of(run_asyncio(read()), 5) == ("caller", "flpit")


# -- cancellation --------------------------------------------------------------------------------

def test_token_cancels_and_finally_runs(backend):
    ran_finally = threading.Event()

    @asyncio_task
    async def slow(token):
        try:
            await asyncio.sleep(30)
        finally:
            ran_finally.set()

    source = CancellationTokenSource()
    t = slow(source.token)
    time.sleep(0.05)
    source.cancel()
    with pytest.raises(OperationCanceledError):
        result_of(t, 5)
    assert t.status == "cancelled"
    assert ran_finally.wait(5)


def test_token_keyword_argument(backend):
    @asyncio_task
    async def slow(*, token):
        await asyncio.sleep(30)

    source = CancellationTokenSource()
    t = slow(token=source.token)
    source.cancel()
    with pytest.raises(OperationCanceledError):
        result_of(t, 5)


def test_already_cancelled_token_starts_nothing(backend):
    started = threading.Event()

    @asyncio_task
    async def body(token):
        started.set()

    source = CancellationTokenSource()
    source.cancel()
    t = body(source.token)
    assert t.status == "cancelled"
    assert not started.is_set()
    assert asyncio_bridge._pool is None


def test_swallowed_cancellation_completes_normally(backend):
    @asyncio_task
    async def stubborn(token):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return "kept going"

    source = CancellationTokenSource()
    t = stubborn(source.token)
    time.sleep(0.05)
    source.cancel()
    assert result_of(t, 5) == "kept going"


def test_no_registrations_or_tasks_left(backend):
    source = CancellationTokenSource()

    @asyncio_task
    async def quick(token):
        await asyncio.sleep(0)
        return 1

    assert sum(result_of(t, 10) for t in [quick(source.token) for _ in range(1000)]) == 1000

    async def leftovers():
        return len(asyncio.all_tasks()) - 1

    pool = asyncio_bridge._get_pool()
    for loop in list(pool.loops):
        assert asyncio.run_coroutine_threadsafe(leftovers(), loop).result(5) == 0
    assert all(load == 0 for load in pool.load.values())
    source.cancel()  # no registrations left to run (would raise on closed tasks otherwise)


# -- LoopLocal -----------------------------------------------------------------------------------

class _Resource:
    instances: list[_Resource] = []

    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.closed = False
        _Resource.instances.append(self)

    async def aclose(self):
        self.closed = True


def test_loop_local_one_per_loop_closed_at_shutdown(backend):
    _Resource.instances.clear()
    local: LoopLocal[_Resource] = LoopLocal(_Resource)

    @asyncio_task
    async def use():
        resource = await local.get()
        assert resource.loop is asyncio.get_running_loop()
        assert resource is local.value
        await asyncio.sleep(0.01)
        return id(resource)

    ids = {result_of(t, 5) for t in [use() for _ in range(50)]}
    assert len(ids) == len(_Resource.instances) <= 2
    asyncio_bridge.shutdown()
    assert all(r.closed for r in _Resource.instances)


def test_loop_local_async_factory(backend):
    async def make():
        await asyncio.sleep(0)
        return object()

    local = LoopLocal(make)

    async def twice():
        return await local.get() is await local.get()

    assert result_of(run_asyncio(twice()), 5)

    async def sync_access():
        return local.value

    # A value exists for this loop now, so .value works; a fresh LoopLocal with an async factory doesn't.
    fresh = LoopLocal(make)

    async def fresh_access():
        return fresh.value

    with pytest.raises(TypeError):
        result_of(run_asyncio(fresh_access()), 5)


def test_loop_local_outside_a_loop():
    with pytest.raises(RuntimeError):
        LoopLocal(object).value


# -- async generators and shutdown ---------------------------------------------------------------

def test_abandoned_async_generator_finalized_on_its_loop(backend):
    closed_on: list[asyncio.AbstractEventLoop | None] = []

    async def gen():
        try:
            yield 1
            yield 2
        finally:
            closed_on.append(asyncio.get_running_loop())

    async def abandon():
        g = gen()
        await g.__anext__()
        del g
        gc.collect()
        for _ in range(5):
            await asyncio.sleep(0.01)
        return asyncio.get_running_loop()

    loop = result_of(run_asyncio(abandon()), 5)
    assert closed_on == [loop]


def test_shutdown_cancels_running_work_and_restarts(backend):
    @asyncio_task
    async def forever():
        await asyncio.sleep(60)

    t = forever()
    time.sleep(0.05)
    asyncio_bridge.shutdown(timeout=2)
    with pytest.raises(OperationCanceledError):
        result_of(t, 5)
    assert asyncio_bridge._pool is None
    assert result_of(run_asyncio(asyncio.sleep(0, "again")), 5) == "again"


def test_task_shutdown_stops_the_loops(backend):
    result_of(run_asyncio(asyncio.sleep(0)), 5)
    assert asyncio_bridge._pool is not None
    Task.shutdown(grace_timeout=0.5, worker_timeout=0.5)
    assert asyncio_bridge._pool is None
    assert result_of(run_asyncio(asyncio.sleep(0, 1)), 5) == 1


# -- configuration -------------------------------------------------------------------------------

def test_configure_validates():
    with pytest.raises(ValueError):
        asyncio_bridge.configure(loops=0)
    with pytest.raises(ValueError):
        asyncio_bridge.configure(backend="uvloop")


@pytest.mark.skipif("strands" not in BACKENDS, reason="needs epoll")
def test_strands_use_no_thread_per_loop():
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=4, backend="strands")
    try:
        before = threading.active_count()

        async def spread():
            await asyncio.sleep(0.02)

        for t in [run_asyncio(spread()) for _ in range(40)]:
            result_of(t, 5)
        names = {th.name for th in threading.enumerate()}
        assert "Task-asyncio-loop" not in names
        assert threading.active_count() - before <= 1 + 4  # the reactor (+ pool growth at most)
    finally:
        asyncio_bridge.shutdown()
        asyncio_bridge.configure(loops=None, backend=asyncio_bridge._DEFAULT_BACKEND)


# -- a real asyncio library ----------------------------------------------------------------------

def test_httpx_client_per_loop(backend):
    httpx = pytest.importorskip("httpx")
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = self.path.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(http.server.ThreadingHTTPServer):
        request_queue_size = 256  # the default backlog of 5 drops SYNs under 100 parallel connects
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    clients: LoopLocal[httpx.AsyncClient] = LoopLocal(lambda: httpx.AsyncClient(trust_env=False))

    @asyncio_task
    async def fetch(i):
        client = await clients.get()
        return (await client.get(f"{base}/{i}")).text

    try:
        assert [result_of(t, 10) for t in [fetch(i) for i in range(100)]] == [f"/{i}" for i in range(100)]
        values = list(clients._values.values())
        assert 1 <= len(values) <= 2
        asyncio_bridge.shutdown()
        assert all(client.is_closed for client in values)
    finally:
        server.shutdown()
