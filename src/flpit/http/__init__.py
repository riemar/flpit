"""FlpIt's provisional .NET-inspired HttpClient surface, backed by urllib3."""
from __future__ import annotations

import contextvars
import io
import json
import socket
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, MutableMapping
from enum import Enum, IntEnum, auto
from typing import Any, BinaryIO, Protocol, TypeVar, runtime_checkable
from urllib.parse import urlencode, urljoin, urlsplit

import urllib3
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import HTTPError, TimeoutError as Urllib3TimeoutError
from urllib3.poolmanager import PoolManager, pool_classes_by_scheme
from urllib3.util import Timeout

from flpit.task import CancellationToken, OperationCanceledError, Task

T = TypeVar("T")


def _token(token: CancellationToken | None) -> CancellationToken:
    return token if token is not None else CancellationToken.none()


class HttpRequestException(Exception):
    def __init__(self, message: str, *, status_code: int | None = None,
                 inner_exception: BaseException | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.inner_exception = inner_exception
        if inner_exception is not None:
            self.__cause__ = inner_exception


class HttpRequestTimeoutError(HttpRequestException):
    """The HTTP request exceeded its configured timeout."""


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    CONNECT = "CONNECT"


class HttpCompletionOption(Enum):
    RESPONSE_CONTENT_READ = auto()
    RESPONSE_HEADERS_READ = auto()


class HttpStatusCode(IntEnum):
    CONTINUE = 100
    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204
    MOVED_PERMANENTLY = 301
    FOUND = 302
    NOT_MODIFIED = 304
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504


class HttpHeaders(MutableMapping[str, str]):
    """Case-insensitive headers. get_all() preserves individual values."""
    def __init__(self, values: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        self._values: dict[str, tuple[str, list[str]]] = {}
        if values is not None:
            source = values.items() if isinstance(values, Mapping) else values
            for name, value in source:
                self.add(name, value)

    def __getitem__(self, name: str) -> str:
        try:
            return ", ".join(self._values[name.casefold()][1])
        except KeyError:
            raise KeyError(name) from None

    def __setitem__(self, name: str, value: str) -> None:
        self._validate(name, value)
        self._values[name.casefold()] = (name, [value])

    def __delitem__(self, name: str) -> None:
        del self._values[name.casefold()]

    def __iter__(self):
        return (name for name, _ in self._values.values())

    def __len__(self) -> int:
        return len(self._values)

    @staticmethod
    def _validate(name: str, value: str) -> None:
        if not isinstance(name, str) or not name or any(c in name for c in "\r\n:"):
            raise ValueError("Invalid HTTP header name")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError("Invalid HTTP header value")

    def add(self, name: str, value: str) -> None:
        self._validate(name, value)
        key = name.casefold()
        if key not in self._values:
            self._values[key] = (name, [value])
        else:
            self._values[key][1].append(value)

    def get_all(self, name: str) -> tuple[str, ...]:
        item = self._values.get(name.casefold())
        return tuple(item[1]) if item else ()

    def copy(self) -> HttpHeaders:
        result = HttpHeaders()
        for key, (name, values) in self._values.items():
            result._values[key] = (name, list(values))
        return result

    def set_if_absent(self, name: str, value: str) -> None:
        if name.casefold() not in self._values:
            self[name] = value

    def as_dict(self) -> dict[str, str]:
        return {name: ", ".join(values) for name, values in self._values.values()}


class HttpContent:
    """HTTP request or response content with Task-returning async readers."""
    def __init__(self, data: bytes | None = None, *, raw_response: Any = None,
                 headers: HttpHeaders | None = None,
                 max_buffer_size: int | None = 2**31 - 1) -> None:
        self.headers = headers.copy() if headers else HttpHeaders()
        self._buffer = data
        self._raw = raw_response
        self._max_buffer_size = max_buffer_size
        self._lock = threading.Lock()
        self._stream: BinaryIO | None = None
        self._stream_taken = False
        self._closed = False

    def to_bytes(self, token: CancellationToken | None = None) -> bytes:
        _token(token).throw_if_cancellation_requested()
        if self._buffer is None:
            raise NotImplementedError("Response-only content cannot be sent as a request body")
        return self._buffer

    def read_as_bytes_async(self, token: CancellationToken | None = None) -> Task[bytes]:
        actual = _token(token)
        return Task.run(self._read_bytes, token=actual, pass_token=True)

    def _read_bytes(self, token: CancellationToken) -> bytes:
        token.throw_if_cancellation_requested()
        if self._buffer is not None:
            return self._buffer
        if self._closed:
            raise ValueError("HTTP content is closed")
        if self._stream_taken:
            raise RuntimeError("The response stream has already been taken")
        raw = self._raw
        if raw is None:
            self._buffer = b""
            return self._buffer
        with self._lock:
            if self._buffer is not None:
                return self._buffer
            scope = CancellationScope(token)
            scope.attach(getattr(raw, "connection", None))
            try:
                token.throw_if_cancellation_requested()
                limit = self._max_buffer_size + 1 if self._max_buffer_size is not None else None
                data = raw.read(limit, decode_content=True) if limit is not None else raw.read(decode_content=True)
                token.throw_if_cancellation_requested()
                if self._max_buffer_size is not None and len(data) > self._max_buffer_size:
                    raise HttpRequestException("Response content exceeded the configured buffer limit")
                self._buffer = bytes(data)
                self._raw = None
                return self._buffer
            except BaseException as error:
                raw.close()
                if token.is_cancellation_requested:
                    raise OperationCanceledError("Reading the response body was cancelled", token=token) from error
                raise
            finally:
                scope.dispose()
                try:
                    raw.release_conn()
                except Exception:
                    pass

    def read_as_string_async(self, token: CancellationToken | None = None,
                             *, encoding: str | None = None) -> Task[str]:
        actual = _token(token)
        async def read(token: CancellationToken) -> str:
            data = await self.read_as_bytes_async(token)
            codec = encoding or self._charset() or "utf-8"
            return data.decode(codec, errors="replace")
        return Task.run(read, token=actual, pass_token=True)

    def read_from_json_async(self, target_type: type[T] | None = None,
                             token: CancellationToken | None = None) -> Task[Any]:
        actual = _token(token)
        async def read(token: CancellationToken) -> Any:
            value = json.loads(await self.read_as_bytes_async(token))
            if target_type is None or target_type in (dict, list, str, int, float, bool):
                return value
            if hasattr(target_type, "model_validate"):
                return target_type.model_validate(value)
            if hasattr(target_type, "from_dict"):
                return target_type.from_dict(value)
            return target_type(**value) if isinstance(value, dict) else target_type(value)
        return Task.run(read, token=actual, pass_token=True)

    def read_as_json_async(self, target_type: type[T] | None = None,
                           token: CancellationToken | None = None) -> Task[Any]:
        return self.read_from_json_async(target_type, token)

    def read_as_stream_async(self, token: CancellationToken | None = None) -> Task[BinaryIO]:
        actual = _token(token)
        def open_stream(token: CancellationToken) -> BinaryIO:
            token.throw_if_cancellation_requested()
            if self._closed:
                raise ValueError("HTTP content is closed")
            if self._stream is not None:
                return self._stream
            if self._buffer is not None:
                self._stream = io.BytesIO(self._buffer)
            elif self._raw is not None:
                raw, self._raw = self._raw, None
                self._stream_taken = True
                self._stream = CancellationAwareResponseStream(raw, token)
            else:
                self._stream = io.BytesIO(b"")
            return self._stream
        return Task.run(open_stream, token=actual, pass_token=True)

    def load_into_buffer_async(self, token: CancellationToken | None = None) -> Task[None]:
        actual = _token(token)
        async def load(token: CancellationToken) -> None:
            await self.read_as_bytes_async(token)
        return Task.run(load, token=actual, pass_token=True)

    def copy_to_async(self, destination: BinaryIO,
                      token: CancellationToken | None = None) -> Task[None]:
        actual = _token(token)
        async def copy(token: CancellationToken) -> None:
            destination.write(await self.read_as_bytes_async(token))
            token.throw_if_cancellation_requested()
        return Task.run(copy, token=actual, pass_token=True)

    def _charset(self) -> str | None:
        value = self.headers.get("Content-Type", "")
        for part in value.split(";")[1:]:
            key, sep, val = part.strip().partition("=")
            if sep and key.casefold() == "charset":
                return val.strip(' "\'')
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream is not None:
            self._stream.close()
        if self._raw is not None:
            self._raw.close()

    def __enter__(self) -> HttpContent:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class CancellationAwareResponseStream(io.RawIOBase):
    def __init__(self, raw: Any, token: CancellationToken) -> None:
        super().__init__()
        self._raw = raw
        self._token = token
        self._scope = CancellationScope(token)
        self._scope.attach(getattr(raw, "connection", None))
        self._lock = threading.Lock()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        self._token.throw_if_cancellation_requested()
        try:
            with self._lock:
                result = self._raw.read(size, decode_content=True)
            self._token.throw_if_cancellation_requested()
            return result
        except BaseException as error:
            if self._token.is_cancellation_requested:
                raise OperationCanceledError("Response stream read cancelled", token=self._token) from error
            raise

    def read_async(self, size: int = -1,
                   token: CancellationToken | None = None) -> Task[bytes]:
        actual = _token(token)
        def read(token: CancellationToken) -> bytes:
            scope = CancellationScope(token)
            scope.attach(getattr(self._raw, "connection", None))
            try:
                token.throw_if_cancellation_requested()
                with self._lock:
                    data = self._raw.read(size, decode_content=True)
                token.throw_if_cancellation_requested()
                return data
            except BaseException as error:
                if token.is_cancellation_requested:
                    raise OperationCanceledError("Response stream read cancelled", token=token) from error
                raise
            finally:
                scope.dispose()
        return Task.run(read, token=actual, pass_token=True)

    def close(self) -> None:
        if not self.closed:
            self._scope.dispose()
            try:
                self._raw.close()
            finally:
                super().close()


class ByteArrayContent(HttpContent):
    def __init__(self, content: bytes | bytearray | memoryview,
                 content_type: str | None = None) -> None:
        super().__init__(bytes(content))
        if content_type:
            self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(content))


class StringContent(ByteArrayContent):
    def __init__(self, content: str, encoding: str = "utf-8",
                 media_type: str = "text/plain") -> None:
        super().__init__(content.encode(encoding), f"{media_type}; charset={encoding}")


class JsonContent(ByteArrayContent):
    def __init__(self, value: Any, *, encoding: str = "utf-8") -> None:
        super().__init__(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(encoding),
                         f"application/json; charset={encoding}")


class FormUrlEncodedContent(ByteArrayContent):
    def __init__(self, values: Mapping[str, str] | Iterable[tuple[str, str]]) -> None:
        super().__init__(urlencode(values).encode("ascii"), "application/x-www-form-urlencoded")


class StreamContent(HttpContent):
    """File-like upload body; token is checked between chunks."""
    def __init__(self, stream: BinaryIO, content_type: str | None = None,
                 chunk_size: int = 64 * 1024) -> None:
        super().__init__()
        self._source = stream
        self._chunk_size = chunk_size
        if content_type:
            self.headers["Content-Type"] = content_type

    def to_bytes(self, token: CancellationToken | None = None) -> bytes:
        actual = _token(token)
        chunks: list[bytes] = []
        while True:
            actual.throw_if_cancellation_requested()
            chunk = self._source.read(self._chunk_size)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode()
            chunks.append(bytes(chunk))
        return b"".join(chunks)


class HttpRequestMessage:
    def __init__(self, method: HttpMethod | str, request_uri: str,
                 content: HttpContent | None = None) -> None:
        if not request_uri:
            raise ValueError("request_uri must not be empty")
        self.method = method.value if isinstance(method, HttpMethod) else str(method).upper()
        self.request_uri = request_uri
        self.content = content
        self.headers = HttpHeaders()
        self.version = "HTTP/1.1"
        self.version_policy = "exact"
        self.options: dict[str, Any] = {}
        self._timeout: float | None = 100.0
        self._completion_option = HttpCompletionOption.RESPONSE_CONTENT_READ
        self._max_response_content_buffer_size: int | None = 2**31 - 1
        self._sent = False
        self._lock = threading.Lock()

    def mark_sent(self) -> None:
        with self._lock:
            if self._sent:
                raise ValueError("An HttpRequestMessage cannot be sent more than once")
            self._sent = True


class HttpResponseMessage:
    def __init__(self, status_code: int, content: HttpContent, *,
                 reason_phrase: str = "", request_message: HttpRequestMessage | None = None,
                 headers: HttpHeaders | None = None, version: str = "HTTP/1.1") -> None:
        self.status_code = int(status_code)
        self.reason_phrase = reason_phrase
        self.request_message = request_message
        self.headers = headers.copy() if headers else HttpHeaders()
        self.content = content
        self.version = version
        self._closed = False

    @property
    def is_success_status_code(self) -> bool:
        return 200 <= self.status_code <= 299

    def ensure_success_status_code(self) -> HttpResponseMessage:
        if not self.is_success_status_code:
            raise HttpRequestException(
                f"Response status code does not indicate success: {self.status_code} {self.reason_phrase}".rstrip(),
                status_code=self.status_code,
            )
        return self

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.content.close()

    def __enter__(self) -> HttpResponseMessage:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class CancellationScope:
    """Registers socket shutdown on a FLPIT CancellationToken."""
    def __init__(self, token: CancellationToken) -> None:
        self.token = token
        self._lock = threading.Lock()
        self._connection: Any = None
        self._cancelled = token.is_cancellation_requested
        self._registration = token.register(self.cancel) if token.can_be_cancelled else None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled or self.token.is_cancellation_requested

    def attach(self, connection: Any) -> None:
        if connection is None:
            return
        with self._lock:
            self._connection = connection
            cancelled = self.is_cancelled
        if cancelled:
            self._abort(connection)

    def detach(self, connection: Any) -> None:
        with self._lock:
            if self._connection is connection:
                self._connection = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            connection = self._connection
        if connection is not None:
            self._abort(connection)

    @staticmethod
    def _abort(connection: Any) -> None:
        sock = getattr(connection, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            connection.close()
        except Exception:
            pass

    def dispose(self) -> None:
        with self._lock:
            self._connection = None
            registration, self._registration = self._registration, None
        if registration is not None:
            registration.dispose()


_ACTIVE_SCOPE: contextvars.ContextVar[CancellationScope | None] = contextvars.ContextVar(
    "flpit_http_active_cancellation_scope", default=None
)


class _CancellablePoolMixin:
    def _make_request(self, conn: Any, *args: Any, **kwargs: Any) -> Any:
        scope = _ACTIVE_SCOPE.get()
        if scope is None:
            return super()._make_request(conn, *args, **kwargs)
        scope.attach(conn)
        try:
            scope.token.throw_if_cancellation_requested()
            response = super()._make_request(conn, *args, **kwargs)
            scope.token.throw_if_cancellation_requested()
            return response
        except BaseException as error:
            if scope.is_cancelled and not isinstance(error, OperationCanceledError):
                raise OperationCanceledError("HTTP request cancelled", token=scope.token) from error
            raise
        finally:
            scope.detach(conn)


class _CancellableHTTPPool(_CancellablePoolMixin, HTTPConnectionPool):
    pass


class _CancellableHTTPSPool(_CancellablePoolMixin, HTTPSConnectionPool):
    pass


class CancellablePoolManager(PoolManager):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        classes = dict(pool_classes_by_scheme)
        classes["http"] = _CancellableHTTPPool
        classes["https"] = _CancellableHTTPSPool
        self.pool_classes_by_scheme = classes


class Urllib3Transport:
    def __init__(self, *, max_connections_per_host: int = 10,
                 retries: int | bool = 0, redirect: bool = True,
                 pool_manager: PoolManager | None = None) -> None:
        self._owns_pool = pool_manager is None
        self._pool = pool_manager or CancellablePoolManager(num_pools=20, maxsize=max_connections_per_host, block=True)
        self.retries = retries
        self.redirect = redirect
        self._closed = False

    def send(self, method: str, url: str, *, body: bytes | None,
             headers: dict[str, str], timeout: float | None,
             preload_content: bool, token: CancellationToken) -> Any:
        if self._closed:
            raise RuntimeError("HTTP transport is closed")
        token.throw_if_cancellation_requested()
        scope = CancellationScope(token)
        ctx = _ACTIVE_SCOPE.set(scope)
        try:
            try:
                return self._pool.request(
                    method, url, body=body, headers=headers, retries=self.retries,
                    redirect=self.redirect,
                    timeout=Timeout(total=timeout) if timeout is not None else Timeout(total=None),
                    preload_content=preload_content, decode_content=True,
                )
            except OperationCanceledError:
                raise
            except (HTTPError, OSError, TimeoutError) as error:
                if token.is_cancellation_requested:
                    raise OperationCanceledError("HTTP request cancelled", token=token) from error
                if isinstance(error, Urllib3TimeoutError):
                    raise TimeoutError(f"HTTP request timed out: {url}") from error
                raise
        finally:
            _ACTIVE_SCOPE.reset(ctx)
            scope.dispose()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._owns_pool:
                self._pool.clear()


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
