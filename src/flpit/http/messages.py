"""HTTP methods, completion options, request and response messages."""
from __future__ import annotations

import threading
from enum import Enum, IntEnum, auto
from typing import Any

from .content import HttpContent
from .errors import HttpRequestException
from .headers import HttpHeaders

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


