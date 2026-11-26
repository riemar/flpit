from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import urllib3

from flpit import asyncio_bridge
from flpit.asyncio_bridge import LoopLocal, run_asyncio
from flpit.task import CancellationTokenSource, OperationCanceledError


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/slow":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"x")
            self.wfile.flush()
            time.sleep(2)
            try:
                self.wfile.write(b"y")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        body = b"urllib3-future"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def bridge():
    asyncio_bridge.shutdown()
    asyncio_bridge.configure(loops=1)
    yield
    asyncio_bridge.shutdown()


def test_async_pool_manager_runs_on_flpit_bridge(bridge, http_server: str) -> None:
    assert hasattr(urllib3, "AsyncPoolManager"), (
        "Install urllib3-future to run this integration test"
    )
    pools = LoopLocal(urllib3.AsyncPoolManager)

    async def fetch() -> tuple[int, bytes]:
        pool = await pools.get()
        response = await pool.request("GET", http_server)
        try:
            return response.status, await response.data
        finally:
            await response.close()

    tasks = [run_asyncio(fetch()) for _ in range(8)]
    assert [task.result(timeout=5) for task in tasks] == [
        (200, b"urllib3-future")
    ] * 8


def test_flpit_cancellation_cancels_async_socket_read(bridge, http_server: str) -> None:
    assert hasattr(urllib3, "AsyncPoolManager"), (
        "Install urllib3-future to run this integration test"
    )
    pools = LoopLocal(urllib3.AsyncPoolManager)

    async def fetch() -> bytes:
        pool = await pools.get()
        response = await pool.request("GET", f"{http_server}/slow", preload_content=False)
        try:
            return await response.read()
        finally:
            await response.close()

    source = CancellationTokenSource()
    task = run_asyncio(fetch(), token=source.token)
    timer = threading.Timer(0.2, source.cancel)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(OperationCanceledError):
            task.result(timeout=3)
        assert time.monotonic() - started < 1.5
    finally:
        timer.cancel()
