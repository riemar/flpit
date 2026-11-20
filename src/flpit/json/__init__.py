"""Typed JSON for dataclasses: ``JsonConvert``, options, annotations and the type registry.

Two interchangeable backends implement the same contract:

* ``"msgspec"``: fast, used automatically when msgspec is installed.
* ``"native"``: pure Python on the standard library ``json`` module. Used when
  msgspec is not available (PyPy, Pyodide, platforms without wheels).

Select explicitly with ``set_backend("native")`` / ``set_backend("msgspec")``
or the ``FLPIT_JSON_BACKEND`` environment variable; ``"auto"`` (the default)
picks msgspec when it can be imported.
"""
from __future__ import annotations

import os
import threading
import typing
from collections.abc import Iterable
from typing import Any

from flpit.json._core import (
    AnnotationModel,
    ConversionError,
    JIgnore,
    JInclude,
    JProp,
    JPropMeta,
    JsonDefaultHandling,
    JsonDeserializationError,
    JsonNamingPolicy,
    JsonSerializationError,
    JsonSerializerOptions,
    JsonUnknownFieldHandling,
    _apply_naming_policy,
    register_collection,
    register_type,
    unregister_type,
)

__all__ = [
    "JIgnore",
    "JInclude",
    "JProp",
    "JsonConvert",
    "JsonDefaultHandling",
    "JsonDeserializationError",
    "JsonNamingPolicy",
    "JsonSerializationError",
    "JsonSerializerOptions",
    "JsonUnknownFieldHandling",
    "available_backends",
    "get_backend",
    "register_collection",
    "register_type",
    "set_backend",
    "unregister_type",
]

_BACKEND_NAMES = ("msgspec", "native")
_ENV_VAR = "FLPIT_JSON_BACKEND"

_backend_lock = threading.Lock()
_requested: str | None = None   # None: not decided yet
_active: Any = None


def _load(name: str) -> Any:
    if name == "msgspec":
        from flpit.json._msgspec import Backend
    elif name == "native":
        from flpit.json._native import Backend
    else:
        raise ValueError(f"unknown flpit.json backend {name!r}; use one of {_BACKEND_NAMES} or 'auto'")
    return Backend


def _msgspec_importable() -> bool:
    try:
        import msgspec  # noqa: F401
    except ImportError:
        return False
    return True


def available_backends() -> tuple[str, ...]:
    """Backends usable in this environment, fastest first."""
    return _BACKEND_NAMES if _msgspec_importable() else ("native",)


def _resolve(requested: str) -> Any:
    requested = requested.strip().lower() or "auto"
    if requested == "auto":
        return _load("msgspec" if _msgspec_importable() else "native")
    return _load(requested)


def set_backend(name: str = "auto") -> None:
    """Select the JSON backend: ``"auto"``, ``"msgspec"`` or ``"native"``.

    Raises ImportError when ``"msgspec"`` is requested but not installed.
    """
    global _requested, _active
    backend = _resolve(name)
    with _backend_lock:
        _requested = name
        _active = backend


def get_backend() -> str:
    """Name of the backend in use (``"msgspec"`` or ``"native"``)."""
    return _impl().name


def _impl() -> Any:
    global _requested, _active
    backend = _active
    if backend is not None:
        return backend
    with _backend_lock:
        if _active is None:
            _requested = os.environ.get(_ENV_VAR, "auto")
            _active = _resolve(_requested)
        return _active


def __getattr__(name: str) -> Any:
    # Backwards compatibility: msgspec-specific helpers that used to live here.
    if name == "wire_type_for":
        from flpit.json._msgspec import wire_type_for
        return wire_type_for
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class JsonConvert:
    """Serialize dataclasses to JSON and back, using the active backend."""

    @staticmethod
    def deserialize[T](
            data: bytes | str,
            target: type[T],
            jso: JsonSerializerOptions | None = None,
    ) -> T:
        return _impl().deserialize(data, target, jso)

    @staticmethod
    def serialize[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None,
    ) -> str:
        return _impl().serialize(data, target, jso)

    @staticmethod
    def serialize_bytes[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None,
    ) -> bytes:
        return _impl().serialize_bytes(data, target, jso)

    @staticmethod
    def serialize_to[T](
            it: Iterable[T],
            target: type[T],
            output: typing.BinaryIO | typing.TextIO,
            jso: JsonSerializerOptions | None = None,
    ) -> None:
        return _impl().serialize_to(it, target, output, jso)
