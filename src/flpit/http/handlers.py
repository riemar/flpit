"""HttpMessageHandler pipeline and urllib3-backed primary handler."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from flpit.task import CancellationToken, OperationCanceledError, Task

from .content import HttpContent
from .errors import HttpRequestException, HttpRequestTimeoutError
from .headers import HttpHeaders
from .messages import HttpCompletionOption, HttpRequestMessage, HttpResponseMessage
from .transport import CancellationScope, Urllib3Transport

class HttpMessageHandler(ABC):
    @abstractmethod
    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DelegatingHandler(HttpMessageHandler):
    def __init__(self, inner_handler: HttpMessageHandler | None = None) -> None:
        self.inner_handler = inner_handler
        self._closed = False

    def attach(self, inner_handler: HttpMessageHandler) -> None:
        if self.inner_handler is not None:
            raise RuntimeError("DelegatingHandler can only be attached once")
        self.inner_handler = inner_handler

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        if self._closed or self.inner_handler is None:
            raise RuntimeError("DelegatingHandler is closed or has no inner handler")
        return self.inner_handler.send_async(request, token)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self.inner_handler is not None:
                self.inner_handler.close()


class HttpClientHandler(HttpMessageHandler):
    """Primary handler: urllib3 pools plus FLPIT-token-aware socket abort."""
    def __init__(self, *, max_connections_per_host: int = 10,
                 retries: int | bool = 0, allow_auto_redirect: bool = True,
                 transport: Urllib3Transport | None = None) -> None:
        self._transport = transport or Urllib3Transport(
            max_connections_per_host=max_connections_per_host,
            retries=retries, redirect=allow_auto_redirect,
        )
        self._closed = False

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        if self._closed:
            raise RuntimeError("HttpClientHandler is closed")
        actual = _token(token)
        request.mark_sent()
        return Task.run(self._send, request, token=actual, pass_token=True)

    def _send(self, request: HttpRequestMessage, token: CancellationToken) -> HttpResponseMessage:
        token.throw_if_cancellation_requested()
        headers = request.headers.copy()
        body = request.content.to_bytes(token) if request.content is not None else None
        if request.content is not None:
            for name, value in request.content.headers.items():
                headers.set_if_absent(name, value)
        try:
            raw = self._transport.send(
                request.method, request.request_uri, body=body, headers=headers.as_dict(),
                timeout=request._timeout, preload_content=False, token=token,
            )
        except OperationCanceledError:
            raise
        except TimeoutError as error:
            raise HttpRequestTimeoutError(str(error), inner_exception=error) from error
        except Exception as error:
            if token.is_cancellation_requested:
                raise OperationCanceledError("HTTP request cancelled", token=token) from error
            raise HttpRequestException(f"Error sending request to {request.request_uri}",
                                       inner_exception=error) from error

        response_headers = HttpHeaders()
        for name, value in raw.headers.items():
            response_headers[name] = str(value)
        content_headers = HttpHeaders(
            (name, value) for name, value in response_headers.items()
            if name.casefold().startswith("content-")
        )
        max_size = request._max_response_content_buffer_size
        if request._completion_option is HttpCompletionOption.RESPONSE_CONTENT_READ:
            scope = CancellationScope(token)
            scope.attach(getattr(raw, "connection", None))
            try:
                limit = max_size + 1 if max_size is not None else None
                data = raw.read(limit, decode_content=True) if limit is not None else raw.read(decode_content=True)
                token.throw_if_cancellation_requested()
                if max_size is not None and len(data) > max_size:
                    raise HttpRequestException("Response content exceeded the configured buffer limit")
            except OperationCanceledError:
                raw.close()
                raise
            except BaseException as error:
                raw.close()
                if token.is_cancellation_requested:
                    raise OperationCanceledError("Response body read cancelled", token=token) from error
                raise HttpRequestException("Error reading HTTP response body", inner_exception=error) from error
            finally:
                scope.dispose()
                try:
                    raw.release_conn()
                except Exception:
                    pass
            content = HttpContent(bytes(data), headers=content_headers, max_buffer_size=max_size)
        else:
            content = HttpContent(raw_response=raw, headers=content_headers, max_buffer_size=max_size)
        version = "HTTP/1.0" if getattr(raw, "version", 11) == 10 else "HTTP/1.1"
        return HttpResponseMessage(raw.status, content,
                                   reason_phrase=str(getattr(raw, "reason", "") or ""),
                                   request_message=request, headers=response_headers, version=version)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()


@runtime_checkable
class IHttpClient(Protocol):
    base_address: str | None
    timeout: float | None
    max_response_content_buffer_size: int | None
    default_request_headers: HttpHeaders

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None,
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

    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None,
                   completion_option: HttpCompletionOption = HttpCompletionOption.RESPONSE_CONTENT_READ) -> Task[HttpResponseMessage]:
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
        return self._handler.send_async(request, actual)

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


__all__ = [
    "ByteArrayContent", "CancellationAwareResponseStream", "DelegatingHandler",
    "FormUrlEncodedContent", "HttpClient", "HttpClientFactory", "HttpClientHandler",
    "HttpCompletionOption", "HttpContent", "HttpHeaders", "HttpMessageHandler",
    "HttpMessageInvoker", "HttpMethod", "HttpRequestException", "HttpRequestMessage",
    "HttpRequestTimeoutError", "HttpResponseMessage", "HttpStatusCode",
    "IHttpClient", "IHttpClientFactory", "JsonContent", "StreamContent",
    "StringContent", "Urllib3Transport",
]