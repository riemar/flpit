"""Socket waits on both reactors: the epoll one (Linux) and the selectors one (everywhere)."""
from __future__ import annotations

import gc
import select
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

import flpit.task as task_module
from flpit.task import CancellationTokenSource, IO, OperationCanceledError, RuntimeShutdownError, Task

REACTORS = ["epoll", "selectors"] if hasattr(select, "epoll") else ["selectors"]


@pytest.fixture(params=REACTORS)
def reactor(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh runtime whose socket waits go through the requested reactor."""
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    if request.param == "selectors":
        original = task_module._Runtime.__init__

        def init(self: Any, **settings: Any) -> None:
            original(self, **settings)
            self._io = task_module._IOReactor(self)

        monkeypatch.setattr(task_module._Runtime, "__init__", init)
    yield str(request.param)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)


def expected_reactor(name: str) -> type:
    return task_module._EpollIOReactor if name == "epoll" else task_module._IOReactor


def settled(task: Task[Any], timeout: float = 5.0) -> Any:
    """The task's result, failing instead of hanging when it never completes."""
    deadline = time.monotonic() + timeout
    while not task.done():
        assert time.monotonic() < deadline, "the wait never completed"
        time.sleep(0.005)
    return task.result()


def pair() -> tuple[socket.socket, socket.socket]:
    a, b = socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)
    return a, b


async def read_some(sock: socket.socket, token: Any = None) -> bytes:
    while True:
        try:
            data = sock.recv(4096)
        except BlockingIOError:
            await IO.wait_readable(sock, token=token)
            continue
        return data


def test_the_platform_reactor_is_used(reactor: str) -> None:
    a, b = pair()
    with a, b:
        b.send(b"x")
        assert Task.run(read_some, a).result() == b"x"
    assert type(task_module._get_runtime()._io) is expected_reactor(reactor)


def test_many_waits_on_one_socket(reactor: str) -> None:
    # Each wait re-arms the same descriptor (one-shot on epoll).
    a, b = pair()

    def echo() -> None:
        b.setblocking(True)
        for _ in range(500):
            b.sendall(b.recv(64))

    helper = threading.Thread(target=echo)
    helper.start()

    async def ping_pong() -> int:
        done = 0
        for i in range(500):
            message = f"{i:04d}".encode()
            a.send(message)
            reply = b""
            while len(reply) < len(message):
                reply += await read_some(a)
            assert reply == message
            done += 1
        return done

    try:
        assert Task.run(ping_pong).result() == 500
    finally:
        helper.join(5)
        a.close()
        b.close()


def test_many_sockets_at_once(reactor: str) -> None:
    pairs = [pair() for _ in range(64)]
    try:
        tasks = [Task.run(read_some, a) for a, _ in pairs]
        time.sleep(0.05)  # let them all park
        for i, (_, b) in enumerate(pairs):
            b.send(str(i).encode())
        assert [settled(t) for t in tasks] == [str(i).encode() for i in range(64)]
    finally:
        for a, b in pairs:
            a.close()
            b.close()


def test_read_and_write_waits_on_one_socket(reactor: str) -> None:
    a, b = pair()
    # Fill a's send buffer so a write wait has to wait too.
    try:
        while True:
            a.send(b"\0" * 65536)
    except BlockingIOError:
        pass

    async def wait_writable() -> str:
        await IO.wait_writable(a)
        return "writable"

    try:
        reading = Task.run(read_some, a)
        writing = Task.run(wait_writable)
        time.sleep(0.05)
        assert not reading.done() and not writing.done()
        b.send(b"hello")  # the read side fires; the write side must stay armed
        assert settled(reading) == b"hello"
        assert not writing.done()
        # Unix sockets turn writable again only once most of the buffer drains.
        while True:
            try:
                b.recv(65536)
            except BlockingIOError:
                break
        assert settled(writing) == "writable"
    finally:
        a.close()
        b.close()


def test_a_cancelled_wait_leaves_the_socket_usable(reactor: str) -> None:
    a, b = pair()
    source = CancellationTokenSource()
    try:
        waiting = Task.run(read_some, a, source.token)
        time.sleep(0.05)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            settled(waiting)
        b.send(b"later")  # readiness for the cancelled wait: must be ignored
        time.sleep(0.05)
        assert Task.run(read_some, a).result() == b"later"
    finally:
        a.close()
        b.close()


def test_shutdown_fails_pending_waits(reactor: str) -> None:
    a, b = pair()
    try:
        waiting = Task.run(read_some, a)
        time.sleep(0.05)
        Task.shutdown(grace_timeout=0.2, worker_timeout=0.5)
        with pytest.raises((RuntimeShutdownError, OperationCanceledError)):
            settled(waiting)
    finally:
        a.close()
        b.close()


def test_a_reused_descriptor_works(reactor: str) -> None:
    a, b = pair()
    b.send(b"first")
    assert Task.run(read_some, a).result() == b"first"
    a.close()
    b.close()
    # The next sockets very likely get the same descriptor numbers.
    c, d = pair()
    try:
        d.send(b"second")
        assert Task.run(read_some, c).result() == b"second"
    finally:
        c.close()
        d.close()


def test_waiting_on_a_closed_socket_fails_at_once(reactor: str) -> None:
    a, b = pair()
    a.close()
    b.close()

    async def wait() -> None:
        await IO.wait_readable(a)

    with pytest.raises((ValueError, OSError)):
        Task.run(wait).result()


def test_a_dropped_socket_is_not_kept_alive(reactor: str) -> None:
    a, b = pair()
    b.send(b"x")
    assert Task.run(read_some, a).result() == b"x"
    import weakref

    ref = weakref.ref(a)
    a.close()
    del a
    gc.collect()
    assert ref() is None  # the reactor holds no strong reference to sockets it armed
    b.close()
