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


def _token(token: CancellationToken | None) -> CancellationToken:
    return token if token is not None else CancellationToken.none()


class HttpMessageHandler(ABC):
    @abstractmethod
    def send_async(self, request: HttpRequestMessage,
                   token: CancellationToken | None = None) -> Task[HttpResponseMessage]:
        raise NotImplementedError

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None) -> HttpResponseMessage:
        """Blocking compatibility path for async-only custom handlers."""
        return self.send_async(request, token).result()

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

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None) -> HttpResponseMessage:
        if self._closed or self.inner_handler is None:
            raise RuntimeError("DelegatingHandler is closed or has no inner handler")
        # Preserve async-only middleware subclasses when they are used by the
        # blocking API. The primary handler still performs native blocking I/O.
        if type(self).send_async is not DelegatingHandler.send_async:
            return self.send_async(request, token).result()
        return self.inner_handler.send(request, token)

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

    def send(self, request: HttpRequestMessage,
             token: CancellationToken | None = None) -> HttpResponseMessage:
        if self._closed:
            raise RuntimeError("HttpClientHandler is closed")
        actual = _token(token)
        actual.throw_if_cancellation_requested()
        request.mark_sent()
        return self._send(request, actual)

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


