"""HTTP content and cancellation-aware response stream implementations."""
from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterable, Mapping
from typing import Any, BinaryIO, TypeVar
from urllib.parse import urlencode

from flpit.task import CancellationToken, OperationCanceledError, Task

from .errors import HttpRequestException
from .headers import HttpHeaders
from .transport import CancellationScope

T = TypeVar("T")


def _token(token: CancellationToken | None) -> CancellationToken:
    return token if token is not None else CancellationToken.none()


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

    def read_as_bytes(self, token: CancellationToken | None = None) -> bytes:
        """Read the complete response body synchronously, observing token cancellation."""
        return self._read_bytes(_token(token))

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

    def read_as_string(self, token: CancellationToken | None = None,
                       *, encoding: str | None = None) -> str:
        """Read and decode the complete response body synchronously."""
        data = self._read_bytes(_token(token))
        codec = encoding or self._charset() or "utf-8"
        return data.decode(codec, errors="replace")

    def read_as_string_async(self, token: CancellationToken | None = None,
                             *, encoding: str | None = None) -> Task[str]:
        actual = _token(token)
        async def read(token: CancellationToken) -> str:
            data = await self.read_as_bytes_async(token)
            codec = encoding or self._charset() or "utf-8"
            return data.decode(codec, errors="replace")
        return Task.run(read, token=actual, pass_token=True)

    @staticmethod
    def _deserialize_json(data: bytes, target_type: type[T] | None = None) -> Any:
        value = json.loads(data)
        if target_type is None or target_type in (dict, list, str, int, float, bool):
            return value
        if hasattr(target_type, "model_validate"):
            return target_type.model_validate(value)
        if hasattr(target_type, "from_dict"):
            return target_type.from_dict(value)
        return target_type(**value) if isinstance(value, dict) else target_type(value)

    def read_from_json(self, target_type: type[T] | None = None,
                       token: CancellationToken | None = None) -> Any:
        """Deserialize JSON content synchronously, observing token cancellation."""
        return self._deserialize_json(self._read_bytes(_token(token)), target_type)

    def read_from_json_async(self, target_type: type[T] | None = None,
                             token: CancellationToken | None = None) -> Task[Any]:
        actual = _token(token)
        async def read(token: CancellationToken) -> Any:
            data = await self.read_as_bytes_async(token)
            return self._deserialize_json(data, target_type)
        return Task.run(read, token=actual, pass_token=True)

    def read_as_json(self, target_type: type[T] | None = None,
                     token: CancellationToken | None = None) -> Any:
        return self.read_from_json(target_type, token)

    def read_as_json_async(self, target_type: type[T] | None = None,
                           token: CancellationToken | None = None) -> Task[Any]:
        return self.read_from_json_async(target_type, token)

    def read_as_stream(self, token: CancellationToken | None = None) -> BinaryIO:
        """Transfer the response body to a blocking stream."""
        actual = _token(token)
        actual.throw_if_cancellation_requested()
        if self._closed:
            raise ValueError("HTTP content is closed")
        if self._stream is not None:
            return self._stream
        if self._buffer is not None:
            self._stream = io.BytesIO(self._buffer)
        elif self._raw is not None:
            raw, self._raw = self._raw, None
            self._stream_taken = True
            self._stream = CancellationAwareResponseStream(raw, actual)
        else:
            self._stream = io.BytesIO(b"")
        return self._stream

    def read_as_stream_async(self, token: CancellationToken | None = None) -> Task[BinaryIO]:
        actual = _token(token)
        return Task.run(self.read_as_stream, token=actual, pass_token=True)

    def load_into_buffer(self, token: CancellationToken | None = None) -> None:
        """Buffer the full response body synchronously."""
        self._read_bytes(_token(token))

    def load_into_buffer_async(self, token: CancellationToken | None = None) -> Task[None]:
        actual = _token(token)
        async def load(token: CancellationToken) -> None:
            await self.read_as_bytes_async(token)
        return Task.run(load, token=actual, pass_token=True)

    def copy_to(self, destination: BinaryIO,
                token: CancellationToken | None = None) -> None:
        """Copy the complete response body to destination synchronously."""
        actual = _token(token)
        destination.write(self._read_bytes(actual))
        actual.throw_if_cancellation_requested()

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
        self._lock = threading.Lock()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1, *, token: CancellationToken | None = None) -> bytes:
        """Read a chunk synchronously; a supplied token interrupts a blocked socket read."""
        actual = _token(token) if token is not None else self._token
        scope = CancellationScope(actual)
        scope.attach(getattr(self._raw, "connection", None))
        try:
            actual.throw_if_cancellation_requested()
            with self._lock:
                result = self._raw.read(size, decode_content=True)
            actual.throw_if_cancellation_requested()
            return result
        except BaseException as error:
            if actual.is_cancellation_requested:
                raise OperationCanceledError("Response stream read cancelled", token=actual) from error
            raise
        finally:
            scope.dispose()

    def read_async(self, size: int = -1,
                   token: CancellationToken | None = None) -> Task[bytes]:
        actual = token if token is not None else self._token
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


