"""The pool replaces workers that wait rather than compute (burst_workers).

Nothing outside flpit is patched: a worker stalled on one item while the process leaves CPU
unused is waiting, whatever it waits on. The checks count how many calls wait at the same
time, not wall-clock time, so a slow or loaded machine cannot make them flaky.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import flpit.task as task_module
from flpit.task import Task


HAS_THREAD_CLOCKS = hasattr(time, "pthread_getcpuclockid")


@pytest.fixture(params=["thread-cpu", "process-cpu"] if HAS_THREAD_CLOCKS else ["process-cpu"])
def detection(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run a test with per-thread CPU clocks (where they exist) and with the process-CPU fallback."""
    if request.param == "process-cpu":
        monkeypatch.delattr(time, "pthread_getcpuclockid", raising=False)
    return str(request.param)


@pytest.fixture
def pool() -> Iterator[Callable[..., None]]:
    """A runtime of its own with the settings a test asks for."""
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)

    def configure(**settings: Any) -> None:
        Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
        Task.configure(**settings)

    yield configure
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


def run_all(work: Callable[[], Any], n: int) -> None:
    for t in [Task.run(work) for _ in range(n)]:
        t.result()


def live_workers() -> int:
    return task_module._get_runtime()._pool._count


class InFlight:
    """How many calls wait at the same time."""

    def __init__(self) -> None:
        self.now = 0
        self.most = 0
        self._lock = threading.Lock()

    def wrap(self, work: Callable[[], Any]) -> Callable[[], Any]:
        def counted() -> Any:
            with self._lock:
                self.now += 1
                self.most = max(self.most, self.now)
            try:
                return work()
            finally:
                with self._lock:
                    self.now -= 1

        return counted


class Peak:
    """The largest number of live workers seen while the block runs."""

    def __init__(self) -> None:
        self.value = 0
        self._stop = threading.Event()

    def __enter__(self) -> Peak:
        def watch() -> None:
            while not self._stop.is_set():
                self.value = max(self.value, live_workers())
                time.sleep(0.001)

        self._thread = threading.Thread(target=watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def spin(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        pass


# -- waiting workers are replaced, whatever they wait on ---------------------------------------

def test_sleeping_workers_are_replaced(pool, detection) -> None:
    pool(min_workers=4)
    waiting = InFlight()
    run_all(waiting.wrap(lambda: time.sleep(0.5)), 24)
    assert waiting.most >= 8  # twice min_workers; without replacement it stays at 4 (+1)


def test_workers_waiting_on_an_event_are_replaced(pool, detection) -> None:
    pool(min_workers=4)
    release = threading.Event()
    threading.Timer(1.0, release.set).start()
    waiting = InFlight()
    run_all(waiting.wrap(lambda: release.wait(5)), 24)
    assert waiting.most >= 8


def test_workers_blocked_on_a_socket_are_replaced(pool, detection) -> None:
    pool(min_workers=4)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve() -> None:
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return

            def answer(c: socket.socket = connection) -> None:
                with c:
                    c.recv(16)
                    time.sleep(0.5)
                    c.sendall(b"ok")

            threading.Thread(target=answer, daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()

    def call() -> bytes:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
            c.sendall(b"ping")
            return c.recv(16)

    waiting = InFlight()
    try:
        results = [t.result() for t in [Task.run(waiting.wrap(call)) for _ in range(24)]]
    finally:
        listener.close()
    assert results == [b"ok"] * 24
    assert waiting.most >= 8


# -- what must not add workers -----------------------------------------------------------------

def slack(detection: str) -> int:
    # Without per-thread CPU clocks (macOS, Windows), a computing thread that other processes
    # squeeze below half a core looks like a waiting one: under external CPU pressure that
    # fallback may add a few workers for CPU work. Per-thread clocks are not fooled by it.
    return 3 if detection == "thread-cpu" else 6


def test_cpu_bound_work_adds_no_workers(pool, detection) -> None:
    pool(min_workers=2)
    with Peak() as peak:
        run_all(lambda: spin(0.05), 30)
    assert peak.value <= 2 + slack(detection)  # replacement would reach far more


@pytest.mark.skipif(not getattr(sys, "_is_gil_enabled", lambda: True)(), reason="the GIL case")
def test_with_the_gil_cpu_work_on_several_workers_adds_none(pool, detection) -> None:
    # With the GIL, workers waiting for it look idle to the OS. One core busy is saturation.
    pool(min_workers=4)
    with Peak() as peak:
        run_all(lambda: spin(0.05), 30)
    assert peak.value <= 4 + slack(detection)


def test_short_items_add_no_workers(pool) -> None:
    pool(min_workers=2)
    with Peak() as peak:
        run_all(lambda: time.sleep(0.0005), 300)  # each over well within a gate tick
    assert peak.value <= 2 + 3


def test_asyncio_bridge_calls_add_no_workers(pool) -> None:
    pool(min_workers=2)
    from flpit import asyncio_bridge

    asyncio_bridge.shutdown()
    try:
        @task_module.asyncio_task
        async def nap() -> None:
            await asyncio.sleep(0.01)

        with Peak() as peak:
            for t in [nap() for _ in range(100)]:
                t.result()
        assert peak.value <= 2 + 3
    finally:
        asyncio_bridge.shutdown()


@pytest.mark.skipif(not HAS_THREAD_CLOCKS, reason="no per-thread CPU clocks on this platform")
def test_a_thread_cpu_clock_tells_waiting_from_computing() -> None:
    release = threading.Event()
    stop = threading.Event()

    def compute() -> None:
        while not stop.is_set():
            pass

    sleeper = threading.Thread(target=release.wait)
    spinner = threading.Thread(target=compute)
    sleeper.start()
    spinner.start()
    try:
        clocks = [time.pthread_getcpuclockid(t.ident) for t in (sleeper, spinner)]  # type: ignore[arg-type]
        before = [time.clock_gettime(c) for c in clocks]
        time.sleep(0.1)
        slept, spun = (time.clock_gettime(c) - b for c, b in zip(clocks, before))
        assert slept < 0.002
        assert spun > 0.01
    finally:
        release.set()
        stop.set()
        sleeper.join()
        spinner.join()


def test_nothing_outside_flpit_is_patched() -> None:
    import select
    import ssl

    Task.run(lambda: None).result()
    for owner, name in ((socket.socket, "recv"), (socket.socket, "sendall"), (ssl.SSLSocket, "recv"),
                        (time, "sleep"), (socket, "getaddrinfo"), (select, "select")):
        assert not hasattr(getattr(owner, name), "__wrapped__"), f"{name} was replaced"


# -- limits ------------------------------------------------------------------------------------

def test_burst_workers_caps_the_replacement(pool) -> None:
    pool(min_workers=2, burst_workers=8)
    waiting = InFlight()
    with Peak() as peak:
        run_all(waiting.wrap(lambda: time.sleep(0.5)), 24)
    assert peak.value <= 8 + 1  # the cap, plus at most one from the starvation rule
    assert waiting.most >= 6  # but replacement did happen


def test_burst_workers_at_min_workers_keeps_the_old_behaviour(pool) -> None:
    pool(min_workers=4, burst_workers=1)
    waiting = InFlight()
    run_all(waiting.wrap(lambda: time.sleep(0.05)), 24)
    assert waiting.most <= 4 + 1  # min_workers, plus at most one from the starvation rule


def test_a_fixed_size_pool_stays_fixed(pool) -> None:
    pool(max_workers=3)
    with Peak() as peak:
        run_all(lambda: time.sleep(0.02), 30)
    assert peak.value <= 3


def test_configure_validates_burst_workers(pool) -> None:
    with pytest.raises(ValueError):
        Task.configure(burst_workers=0)
    with pytest.raises(ValueError):
        Task.configure(burst_workers=True)  # type: ignore[arg-type]
