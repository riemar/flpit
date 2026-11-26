"""HttpClient, IHttpClient and factory abstractions."""
from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

from flpit.task import CancellationToken, Task

from .content import HttpContent, JsonContent
from .handlers import HttpClientHandler, HttpMessageHandler
from .headers import HttpHeaders
from .messages import HttpCompletionOption, HttpMethod, HttpRequestMessage, HttpResponseMessage


def _token(token: CancellationToken | None) -> CancellationToken:
    return token if token is not None else CancellationToken.none()


@runtime_checkable
class IHttpClient(Protocol):
    base_address: str | None
    timeout: float | None
    max_response_content_buffer_size: int | None
    default_request_headers: HttpHeaders

    def send(self, request: HttpRequestMessage, token: CancellationToken | None = None,
             completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> HttpResponseMessage: ...
    def get(self, uri: str, token: CancellationToken | None = None,
            completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> HttpResponseMessage: ...
    def post(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def put(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def delete(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def head(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def options(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def trace(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def connect(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def patch(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def post_as_json(self, uri: str, value: Any, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def put_as_json(self, uri: str, value: Any, token: CancellationToken | None = None) -> HttpResponseMessage: ...
    def get_string(self, uri: str, token: CancellationToken | None = None) -> str: ...
    def get_byte_array(self, uri: str, token: CancellationToken | None = None) -> bytes: ...
    def get_stream(self, uri: str, token: CancellationToken | None = None) -> Any: ...
    def get_from_json(self, uri: str, target_type: type[Any] | None = None,
                      token: CancellationToken | None = None) -> Any: ...

    def send_async(self, request: HttpRequestMessage, token: CancellationToken | None = None,
                   completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> Task[HttpResponseMessage]: ...
    def get_async(self, uri: str, token: CancellationToken | None = None,
                  completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> Task[HttpResponseMessage]: ...
    def post_async(self, uri: str, content: HttpContent,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def put_async(self, uri: str, content: HttpContent,
                  token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def delete_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def head_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def options_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def trace_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def connect_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def patch_async(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def post_as_json_async(self, uri: str, value: Any, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def put_as_json_async(self, uri: str, value: Any, token: CancellationToken | None = None) -> Task[HttpResponseMessage]: ...
    def get_string_async(self, uri: str, token: CancellationToken | None = None) -> Task[str]: ...
    def get_byte_array_async(self, uri: str, token: CancellationToken | None = None) -> Task[bytes]: ...
    def get_stream_async(self, uri: str, token: CancellationToken | None = None) -> Task[Any]: ...
    def get_from_json_async(self, uri: str, target_type: type[Any] | None = None,
                            token: CancellationToken | None = None) -> Task[Any]: ...
    def close(self) -> None: ...


class HttpMessageInvoker:
    def __init__(self, handler: HttpMessageHandler, *, dispose_handler: bool = True) -> None:
        self._handler = handler
        self._dispose_handler = dispose_handler
        self._closed = False

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None) -> HttpResponseMessage:
        """Invoke the handler synchronously with the supplied cancellation token."""
        if self._closed:
            raise RuntimeError("HttpMessageInvoker is closed")
        return self._handler.send(request, token)

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        if self._closed:
            raise RuntimeError("HttpMessageInvoker is closed")
        return self._handler.send_async(request, token)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._dispose_handler:
                self._handler.close()

    def __enter__(self) -> HttpMessageInvoker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class HttpClient(HttpMessageInvoker):
    def __init__(self, handler: HttpMessageHandler | None = None, *,
                 base_address: str | None = None, timeout: float | None = 100.0,
                 max_response_content_buffer_size: int | None = 2**31 - 1,
                 dispose_handler: bool = True) -> None:
        super().__init__(handler or HttpClientHandler(), dispose_handler=dispose_handler)
        self.base_address = base_address
        self.timeout = timeout
        self.max_response_content_buffer_size = max_response_content_buffer_size
        self.default_request_headers = HttpHeaders()

    def _resolve_uri(self, uri: str) -> str:
        if not uri:
            raise ValueError("uri must not be empty")
        if self.base_address is None:
            parts = urlsplit(uri)
            if not parts.scheme or not parts.netloc:
                raise ValueError("Relative URI requires base_address")
            return uri
        base = self.base_address if self.base_address.endswith("/") else self.base_address + "/"
        return urljoin(base, uri)

    def _prepare_request(self, request: HttpRequestMessage,
                         token: CancellationToken | None,
                         completion_option: HttpCompletionOption) -> CancellationToken:
        if self._closed:
            raise RuntimeError("HttpClient is closed")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be positive or None")
        if self.max_response_content_buffer_size is not None and self.max_response_content_buffer_size < 0:
            raise ValueError("max_response_content_buffer_size must be non-negative")
        actual = _token(token)
        actual.throw_if_cancellation_requested()
        request.request_uri = self._resolve_uri(request.request_uri)
        merged = self.default_request_headers.copy()
        for name in request.headers:
            if name in merged:
                del merged[name]
            for value in request.headers.get_all(name):
                merged.add(name, value)
        request.headers = merged
        request._timeout = self.timeout
        request._completion_option = completion_option
        request._max_response_content_buffer_size = self.max_response_content_buffer_size
        return actual

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None,
             completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> HttpResponseMessage:
        """Send a request synchronously; cancellation interrupts in-flight socket I/O."""
        actual = self._prepare_request(request, token, completion_option)
        return self._handler.send(request, actual)

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None,
                   completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> Task[HttpResponseMessage]:
        actual = self._prepare_request(request, token, completion_option)
        return self._handler.send_async(request, actual)

    # Synchronous verb methods.
    def get(self, uri: str, token: CancellationToken | None = None,
            completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.GET, uri), token, completion_option)

    def delete(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.DELETE, uri), token)

    def head(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.HEAD, uri), token)

    def options(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.OPTIONS, uri), token)

    def trace(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.TRACE, uri), token)

    def connect(self, uri: str, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.CONNECT, uri), token)

    def post(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.POST, uri, content), token)

    def put(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.PUT, uri, content), token)

    def patch(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.send(HttpRequestMessage(HttpMethod.PATCH, uri, content), token)

    def post_as_json(self, uri: str, value: Any, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.post(uri, JsonContent(value), token)

    def put_as_json(self, uri: str, value: Any, token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.put(uri, JsonContent(value), token)

    # Synchronous convenience methods. Buffered helpers always dispose the response.
    def get_string(self, uri: str, token: CancellationToken | None = None) -> str:
        actual = _token(token)
        response = self.get(uri, actual)
        try:
            response.ensure_success_status_code()
            return response.content.read_as_string(actual)
        finally:
            response.close()

    def get_byte_array(self, uri: str, token: CancellationToken | None = None) -> bytes:
        actual = _token(token)
        response = self.get(uri, actual)
        try:
            response.ensure_success_status_code()
            return response.content.read_as_bytes(actual)
        finally:
            response.close()

    def get_stream(self, uri: str, token: CancellationToken | None = None) -> Any:
        actual = _token(token)
        response = self.get(uri, actual, HttpCompletionOption.RESPONSE_HEADERS_READ)
        try:
            response.ensure_success_status_code()
            return response.content.read_as_stream(actual)
        except BaseException:
            response.close()
            raise

    def get_from_json(self, uri: str, target_type: type[Any] | None = None,
                      token: CancellationToken | None = None) -> Any:
        actual = _token(token)
        response = self.get(uri, actual)
        try:
            response.ensure_success_status_code()
            return response.content.read_from_json(target_type, actual)
        finally:
            response.close()

    # Asynchronous verb methods.
    def get_async(self, uri: str, token: CancellationToken | None = None,
                  completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.GET, uri), token, completion_option)

    def delete_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.DELETE, uri), token)

    def head_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.HEAD, uri), token)

    def options_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.OPTIONS, uri), token)

    def trace_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.TRACE, uri), token)

    def connect_async(self, uri: str, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.CONNECT, uri), token)

    def post_async(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.POST, uri, content), token)

    def put_async(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.PUT, uri, content), token)

    def patch_async(self, uri: str, content: HttpContent, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.send_async(HttpRequestMessage(HttpMethod.PATCH, uri, content), token)

    def post_as_json_async(self, uri: str, value: Any, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.post_async(uri, JsonContent(value), token)

    def put_as_json_async(self, uri: str, value: Any, token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.put_async(uri, JsonContent(value), token)

    # Asynchronous convenience methods.
    def get_string_async(self, uri: str, token: CancellationToken | None = None) -> Task[str]:
        actual = _token(token)
        async def read(token: CancellationToken) -> str:
            response = await self.get_async(uri, token)
            try:
                response.ensure_success_status_code()
                return await response.content.read_as_string_async(token)
            finally:
                response.close()
        return Task.run(read, token=actual, pass_token=True)

    def get_byte_array_async(self, uri: str, token: CancellationToken | None = None) -> Task[bytes]:
        actual = _token(token)
        async def read(token: CancellationToken) -> bytes:
            response = await self.get_async(uri, token)
            try:
                response.ensure_success_status_code()
                return await response.content.read_as_bytes_async(token)
            finally:
                response.close()
        return Task.run(read, token=actual, pass_token=True)

    def get_stream_async(self, uri: str, token: CancellationToken | None = None) -> Task[Any]:
        actual = _token(token)
        async def open_stream(token: CancellationToken) -> Any:
            response = await self.get_async(uri, token, HttpCompletionOption.RESPONSE_HEADERS_READ)
            try:
                response.ensure_success_status_code()
                return await response.content.read_as_stream_async(token)
            except BaseException:
                response.close()
                raise
        return Task.run(open_stream, token=actual, pass_token=True)

    def get_from_json_async(self, uri: str, target_type: type[Any] | None = None,
                            token: CancellationToken | None = None) -> Task[Any]:
        actual = _token(token)
        async def read(token: CancellationToken) -> Any:
            response = await self.get_async(uri, token)
            try:
                response.ensure_success_status_code()
                return await response.content.read_from_json_async(target_type, token)
            finally:
                response.close()
        return Task.run(read, token=actual, pass_token=True)


class _NonOwningPrimary(HttpMessageHandler):
    def __init__(self, inner: HttpMessageHandler) -> None:
        self.inner = inner

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None) -> HttpResponseMessage:
        return self.inner.send(request, token)

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        return self.inner.send_async(request, token)


class _ClientBuilder:
    def __init__(self) -> None:
        self.configure: list[Any] = []
        self.primary_factory: Any = HttpClientHandler
        self.primary: HttpMessageHandler | None = None
        self.handlers: list[Any] = []

    def build_primary(self) -> HttpMessageHandler:
        if self.primary is None:
            self.primary = self.primary_factory()
        return self.primary

    def build_pipeline(self) -> HttpMessageHandler:
        current: HttpMessageHandler = _NonOwningPrimary(self.build_primary())
        for factory in reversed(self.handlers):
            current = factory(current)
        return current


@runtime_checkable
class IHttpClientFactory(Protocol):
    def create_client(self, name: str = "") -> IHttpClient: ...


class HttpClientFactory:
    """Named clients with per-client middleware and a shared primary pool handler."""
    def __init__(self) -> None:
        self._builders: dict[str, _ClientBuilder] = {}
        self._lock = threading.RLock()
        self._closed = False

    def _builder(self, name: str) -> _ClientBuilder:
        if self._closed:
            raise RuntimeError("HttpClientFactory is closed")
        return self._builders.setdefault(name, _ClientBuilder())

    def configure_client(self, name: str, callback: Any) -> HttpClientFactory:
        with self._lock:
            self._builder(name).configure.append(callback)
        return self

    def configure_primary_handler(self, name: str, factory: Any) -> HttpClientFactory:
        with self._lock:
            builder = self._builder(name)
            if builder.primary is not None:
                raise RuntimeError("Primary handler already created")
            builder.primary_factory = factory
        return self

    def add_http_message_handler(self, name: str, factory: Any) -> HttpClientFactory:
        with self._lock:
            self._builder(name).handlers.append(factory)
        return self

    def create_client(self, name: str = "") -> HttpClient:
        with self._lock:
            builder = self._builder(name)
            pipeline = builder.build_pipeline()
            callbacks = tuple(builder.configure)
        client = HttpClient(pipeline)
        try:
            for callback in callbacks:
                callback(client)
        except BaseException:
            client.close()
            raise
        return client

    def create_typed_client(self, client_type: type[Any], name: str = "",
                            factory: Any | None = None) -> Any:
        client = self.create_client(name)
        try:
            return factory(client) if factory is not None else client_type(client)
        except BaseException:
            client.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            builders = tuple(self._builders.values())
            self._builders.clear()
        for builder in builders:
            if builder.primary is not None:
                builder.primary.close()

    def __enter__(self) -> HttpClientFactory:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
