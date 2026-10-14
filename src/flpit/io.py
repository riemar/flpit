from types import TracebackType
from abc import ABC, abstractmethod
from io import StringIO, TextIOWrapper
from typing import Any, BinaryIO, Iterable

import msgspec


# ---------- Text layer ----------

class StringBuilder:
    __slots__ = ("_buffer", "_length")

    def __init__(self, initial_value: str = ""):
        self._buffer = StringIO()
        self._length = 0
        self.append(initial_value)

    def append(self, text: str) -> "StringBuilder":
        self._buffer.write(text)
        self._length += len(text)
        return self

    def append_line(self, text: str = "") -> "StringBuilder":
        return self.append(text).append("\n")

    def clear(self) -> None:
        self._buffer.seek(0)
        self._buffer.truncate(0)
        self._length = 0

    @property
    def length(self) -> int:
        return self._length

    def to_string(self) -> str:
        return self._buffer.getvalue()

    def __str__(self) -> str:
        return self.to_string()


class TextWriter(ABC):
    @abstractmethod
    def write(self, text: str) -> int:
        ...

    def write_line(self, text: str = "") -> None:
        self.write(text)
        self.write("\n")

    @abstractmethod
    def flush(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    def __enter__(self):
        return self

    def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> bool | None:
        self.close()


class StringWriter(TextWriter):
    def __init__(self):
        self._builder = StringBuilder()
        self._closed = False

    def write(self, text: str) -> int:
        if self._closed:
            raise ValueError("Writer is closed")
        self._builder.append(text)
        return len(text)

    def flush(self) -> None:
        if self._closed:
            raise ValueError("Writer is closed")

    def close(self) -> None:
        self._closed = True

    def getvalue(self) -> str:
        return self._builder.to_string()


class StreamWriter(TextWriter):
    """Text writer over a binary stream; closing it closes the stream."""

    def __init__(self, stream: BinaryIO, encoding: str = "utf-8"):
        self._stream = TextIOWrapper(stream, encoding=encoding)

    def write(self, text: str) -> int:
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()

#===================================
# ---------- Binary layer ----------
#===================================

class ByteWriter(ABC):
    """write() must consume or copy the supplied bytes before returning."""

    @abstractmethod
    def write(self, data: bytes | bytearray | memoryview) -> None:
        ...

    @abstractmethod
    def flush(self) -> None:
        ...

class MemoryByteWriter(ByteWriter):
    def __init__(self):
        self._buffer = bytearray()

    def write(self, data: bytes | bytearray | memoryview) -> None:
        self._buffer.extend(data)

    def flush(self) -> None:
        pass

    def getvalue(self) -> bytes:
        return bytes(self._buffer)


class StreamByteWriter(ByteWriter):
    """Adapter for a Python binary stream. The caller owns the stream."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream

    def write(self, data: bytes | bytearray | memoryview) -> None:
        view = memoryview(data)

        while view:
            count = self._stream.write(view)
            if count is None or count <= 0:
                raise OSError("Stream failed to write data")
            view = view[count:]

    def flush(self) -> None:
        self._stream.flush()


class BufferedByteWriter(ByteWriter):
    """Adds explicit, bounded-size output buffering to another writer."""

    def __init__(self, destination: ByteWriter, chunk_size: int = 1 << 20):
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")

        self._destination = destination
        self._chunk_size = chunk_size
        self._buffer = bytearray()

    def write(self, data: bytes | bytearray | memoryview) -> None:
        view = memoryview(data)

        while view:
            count = min(
                self._chunk_size - len(self._buffer),
                len(view),
                )
            self._buffer.extend(view[:count])
            view = view[count:]

            if len(self._buffer) == self._chunk_size:
                self._flush_buffer()

    def _flush_buffer(self) -> None:
        if self._buffer:
            self._destination.write(self._buffer)
            self._buffer.clear()

    def flush(self) -> None:
        self._flush_buffer()
        self._destination.flush()


# ---------- JSON serialization policy ----------

def write_json_array(
        items: Iterable[Any],
        output: ByteWriter,
) -> None:
    encoder = msgspec.json.Encoder()
    scratch = bytearray()
    first = True

    output.write(b"[")

    for item in items:
        if not first:
            output.write(b",")

        encoder.encode_into(item, scratch)
        output.write(scratch)
        first = False

    output.write(b"]")
