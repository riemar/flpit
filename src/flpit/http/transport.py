"""urllib3 transport and FLPIT CancellationToken integration."""
from __future__ import annotations

import contextvars
import socket
import threading
from typing import Any

import urllib3
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import HTTPError, TimeoutError as Urllib3TimeoutError
from urllib3.poolmanager import PoolManager, pool_classes_by_scheme
from urllib3.util import Timeout

from flpit.task import CancellationToken, OperationCanceledError

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


