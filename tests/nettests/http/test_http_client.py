from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from flpit.http import (
    HttpClient,
    HttpClientFactory,
    HttpCompletionOption,
    HttpRequestException,
    JsonContent,
)
from flpit.task import CancellationTokenSource, OperationCanceledError


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/slow":
            body_size = 100_000
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(body_size))
            self.end_headers()
            self.wfile.flush()
            try:
                for _ in range(100):
                    time.sleep(0.03)
                    self.wfile.write(b"x" * 1000)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        body = json.dumps({
            "path": self.path,
            "accept": self.headers.get("Accept"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        body = json.dumps({"body": payload}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
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


def test_get_base_address_and_default_headers(http_server: str) -> None:
    with HttpClient(base_address=http_server) as client:
        client.default_request_headers["Accept"] = "application/json"
        response = client.get_async("/items").result(timeout=3)
        try:
            assert response.status_code == 200
            payload = response.content.read_from_json_async().result(timeout=3)
            assert payload == {
                "path": "/items",
                "accept": "application/json",
            }
        finally:
            response.close()


def test_post_json_content(http_server: str) -> None:
    with HttpClient(base_address=http_server) as client:
        response = client.post_async(
            "/items",
            JsonContent({"name": "flpit"}),
        ).result(timeout=3)
        try:
            assert response.status_code == 201
            assert response.content.read_from_json_async().result(timeout=3) == {
                "body": {"name": "flpit"},
            }
        finally:
            response.close()


def test_response_headers_read_defers_body(http_server: str) -> None:
    with HttpClient(base_address=http_server) as client:
        response = client.get_async(
            "/items",
            completion_option=HttpCompletionOption.RESPONSE_HEADERS_READ,
        ).result(timeout=3)
        try:
            assert response.status_code == 200
            assert response.content.read_as_string_async().result(timeout=3).startswith("{")
        finally:
            response.close()


def test_response_buffer_limit_is_enforced(http_server: str) -> None:
    with HttpClient(
        base_address=http_server,
        max_response_content_buffer_size=4,
    ) as client:
        with pytest.raises(HttpRequestException):
            client.get_async("/items").result(timeout=3)


def test_cancellation_interrupts_inflight_response_body(http_server: str) -> None:
    with HttpClient(base_address=http_server, timeout=5.0) as client:
        cts = CancellationTokenSource()
        request = client.get_async("/slow", token=cts.token)
        threading.Timer(0.2, cts.cancel).start()
        started = time.monotonic()
        with pytest.raises(OperationCanceledError):
            request.result(timeout=3)
        assert time.monotonic() - started < 2.5


def test_stream_read_accepts_a_cancellation_token(http_server: str) -> None:
    with HttpClient(base_address=http_server, timeout=5.0) as client:
        response = client.get_async(
            "/slow",
            completion_option=HttpCompletionOption.RESPONSE_HEADERS_READ,
        ).result(timeout=3)
        stream = response.content.read_as_stream_async().result(timeout=3)
        cts = CancellationTokenSource()
        read = stream.read_async(64, token=cts.token)
        threading.Timer(0.2, cts.cancel).start()
        try:
            with pytest.raises(OperationCanceledError):
                read.result(timeout=3)
        finally:
            stream.close()
            response.close()


def test_named_factory_primary_handler_survives_client_disposal(http_server: str) -> None:
    factory = HttpClientFactory()
    factory.configure_client(
        "catalog",
        lambda client: setattr(client, "base_address", http_server),
    )
    first = factory.create_client("catalog")
    second = factory.create_client("catalog")
    try:
        response = first.get_async("/first").result(timeout=3)
        response.close()
        first.close()

        response = second.get_async("/second").result(timeout=3)
        response.close()
    finally:
        first.close()
        second.close()
        factory.close()
