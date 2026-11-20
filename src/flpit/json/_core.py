"""Shared, backend-independent parts of flpit.json.

Options, annotation markers, naming policies, errors and the type registry live
here. Both backends (msgspec and the native stdlib one) build on this module.
"""
from __future__ import annotations

import dataclasses
import re
import threading
import typing
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import blake2s
from typing import Annotated, Any, get_args, get_origin, get_type_hints

class JsonNamingPolicy(StrEnum):
    none = "None"
    lower = "lower" # pyrefly: ignore [bad-override-mutable-attribute]
    upper = "upper" # pyrefly: ignore [bad-override-mutable-attribute]
    camel = "camel"
    pascal = "pascal"
    kebap = "kebab"


class JsonDefaultHandling(StrEnum):
    include = "include"
    exclude = "exclude"

class JsonUnknownFieldHandling(StrEnum):
    allow = "allow"
    disallow = "disallow"


@dataclass(slots=True, frozen=True)
class JsonSerializerOptions:
    naming_policy: JsonNamingPolicy = JsonNamingPolicy.camel
    default_handling: JsonDefaultHandling = JsonDefaultHandling.exclude
    unknown_field_handling: JsonUnknownFieldHandling = JsonUnknownFieldHandling.allow

    # write_indented: bool = False # will be supported later
    native: bool = False
    """
    | Set to true for the native speed of msgspec
    
    !! only set to true if you know what you are doing !!
    You'll receive the msgspec.msgstruct object that will try to do it's best to behave like your dataclass.
    But remember !! "It's NOT your dataclass" !!
    """

    @property
    def fingerprint(self) -> str:
        """
        Identifies a unique jso instance for building a struct
        !! All parts of a jso that don't influence the defstruct MUST be ignored!
        """
        settings = (f"jpn-{self.naming_policy.value}:"
                   f"dh-{self.default_handling}:"
                   f"ufh-{self.unknown_field_handling}:"
                   ).encode("utf-8")
        return blake2s(settings, digest_size=6).hexdigest()

# ---------------------------------------------------------------------------
# Metadata Annotation Markers
# ---------------------------------------------------------------------------

class JIgnore:
    def __class_getitem__[T](cls, item: type[T]) -> Annotated[type[T], JIgnore]:
        return typing.cast(Annotated[type[T], JIgnore], Annotated[item, cls])

class JInclude:
    def __class_getitem__[T](cls, item: type[T]) -> Annotated[type[T], JInclude]:
        return typing.cast(Annotated[type[T], JInclude], Annotated[item, cls])


class JPropMeta(type):
    def __getattr__(cls, name: str) -> Any:
        class SpecializedJProp:
            def __class_getitem__[T](sub_cls, item: type[T]) -> Annotated[type[T], JProp]:
                return typing.cast(Annotated[type[T], JProp], Annotated[item, JProp(json_name=name)])
        return SpecializedJProp

class JProp:
    __slots__ = ("json_name",)
    json_name: str

    def __init__(self, json_name: str):
        self.json_name = json_name

    # 1. This handles the standard initialization/metadata if needed
    def __repr__(self):
        return f"JProp(json_name={self.json_name!r})"

    # 2. This intercepts JProp[str] (the type subscription first)
    def __class_getitem__[T](cls, item: type[T]) -> Any:
        # We return a proxy class that remembers the type 'item' (e.g., str | None)
        class JPropTypeProxy:
            def __getattr__(self, name: str) -> Annotated[type[T], JProp]:
                # 3. This intercepts .JsonPropNameToUse and returns the Annotated type
                return typing.cast(
                    Annotated[type[T], JProp],
                    Annotated[item, JProp(json_name=name)]
                )

        return JPropTypeProxy()

@dataclass
class AnnotationModel:
    other_name: Annotated[str, JProp("WorksToo")]
    display_name: JProp[str].meta
    secret: JIgnore[str] = ""
    always_emit: JInclude[int] = 0

# ---------------------------------------------------------------------


class JsonSerializationError(Exception):
    pass


class JsonDeserializationError(Exception):
    pass


class ConversionError(ValueError):
    """A value could not be converted into the requested type (CSV loading)."""


# Never imagined this would be required to have a proper lib behavior
# ---------------------------------------------------------------------

def _apply_naming_policy(name: str, policy: JsonNamingPolicy) -> str:
    """
    Tokenizes snake_case, camelCase, PascalCase, UPPER_CASE, and kebab-case
    identifiers, then formats the tokens according to the target policy.
    Preserves leading underscores.
    """
    if policy == JsonNamingPolicy.none:
        return name

    # Preserve all leading underscores.
    prefix = name[: len(name) - len(name.lstrip("_"))]
    clean_name = name[len(prefix):]

    # Split on existing separators first, then tokenize each segment.
    # This also correctly handles acronyms such as XMLParser and UPPER_CASE.
    token_pattern = r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+"

    tokens = [
        token
        for part in re.split(r"[_-]+", clean_name)
        for token in re.findall(token_pattern, part)
    ]

    if not tokens:
        return name

    if policy == JsonNamingPolicy.lower:
        result = "".join(token.lower() for token in tokens)
    elif policy == JsonNamingPolicy.upper:
        result = "".join(token.upper() for token in tokens)
    elif policy == JsonNamingPolicy.pascal:
        result = "".join(token.capitalize() for token in tokens)
    elif policy == JsonNamingPolicy.camel:
        result = tokens[0].lower() + "".join(
            token.capitalize() for token in tokens[1:]
        )
    elif policy == JsonNamingPolicy.kebap:
        result = "-".join(token.lower() for token in tokens)
    else:
        raise ValueError(f"Unsupported naming policy: {policy!r}")

    return prefix + result


def _is_dataclass_type(tp: Any) -> bool:
    return isinstance(tp, type) and dataclasses.is_dataclass(tp)


def _field_directives(
        annotation: Any,
) -> tuple[Any, bool, bool, str | None]:
    """Extract JIgnore, JInclude, and JProp directives from a field annotation."""

    if get_origin(annotation) is not typing.Annotated:
        return annotation, False, False, None

    args = get_args(annotation)
    base_type = args[0]
    metadata = args[1:]
    ignored = any(item is JIgnore for item in metadata)
    included = any(item is JInclude for item in metadata)
    json_name = next(
        (item.json_name for item in metadata if isinstance(item, JProp)),
        None,
    )
    remaining = tuple(
        item
        for item in metadata
        if item is not JIgnore
        and item is not JInclude
        and not isinstance(item, JProp)
    )

    if remaining:
        base_type = Annotated[(base_type, *remaining)]

    return base_type, ignored, included, json_name


def _get_property_directive(prop_func: Callable[[Any, Any], None] | Callable[[Any], Any] | None):
    if prop_func is not None:
        getter_hints = get_type_hints(prop_func, include_extras=True)
        source_annotation = getter_hints.get("return", Any)
    else:
        source_annotation = Any

    return  _field_directives(source_annotation)


def _nested_dataclasses(tp: Any):
    """Yield dataclass types referenced by an annotation."""
    if _is_dataclass_type(tp):
        yield tp
        return

    if isinstance(tp, (list, tuple)):
        for item in tp:
            yield from _nested_dataclasses(item)
        return

    origin = get_origin(tp)

    if origin is typing.Annotated:
        yield from _nested_dataclasses(get_args(tp)[0])
        return

    if origin is typing.Literal:
        return

    for arg in get_args(tp):
        yield from _nested_dataclasses(arg)



def _allows_none(tp: Any) -> bool:
    if get_origin(tp) is typing.Annotated:
        tp = get_args(tp)[0]

    return type(None) in get_args(tp)



# ---------------------------------------------------------------------
# Type registry
# ---------------------------------------------------------------------
#
# Two kinds of entries:
#
# * value types: stored as a single JSON value (usually a string). The
#   registry holds a decode(json_value) -> T and an encode(T) -> json_value.
#   Example: whenever.Date <-> "2025-06-15".
#
# * collection types: a generic container ``C[T]`` stored as a JSON array.
#   It is decoded like ``base[T]`` and then handed to ``factory``; encoding
#   iterates the container. Example: FlpList[T] <-> [ ... ].


@dataclass(frozen=True, slots=True)
class _ValueHandler:
    tp: type
    decode: Callable[[Any], Any]
    encode: Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class _CollectionHandler:
    tp: type
    factory: Callable[[Any], Any]
    base: type


_COLLECTION_BASES: tuple[type, ...] = (list, tuple, set, frozenset)

_value_handlers: dict[type, _ValueHandler] = {}
_collection_handlers: dict[type, _CollectionHandler] = {}
_registry_lock = threading.Lock()
_registry_version = 0
_defaults_loaded = False


def _bump() -> None:
    global _registry_version
    _registry_version += 1


def register_type[T](
        tp: type[T],
        *,
        decode: Callable[[Any], T],
        encode: Callable[[T], Any],
) -> None:
    """Teach flpit.json a value type it does not know.

    ``decode`` receives the plain JSON value (str, int, float, bool, None,
    list or dict) and returns an instance of ``tp``; ``encode`` does the
    reverse. Raising ``ValueError`` or ``TypeError`` from ``decode`` turns
    into a ``JsonDeserializationError``. Registering a type again replaces
    the previous handler, including the built-in defaults.
    """
    if not isinstance(tp, type):
        raise TypeError(f"register_type expects a class, got {tp!r}")
    if not callable(decode) or not callable(encode):
        raise TypeError("decode and encode must be callable")
    _register_defaults()
    with _registry_lock:
        _collection_handlers.pop(tp, None)
        _value_handlers[tp] = _ValueHandler(tp, decode, encode)
        _bump()


def register_collection(
        tp: type,
        *,
        factory: Callable[[Any], Any] | None = None,
        base: type = list,
) -> None:
    """Teach flpit.json a generic container stored as a JSON array.

    ``tp[T]`` is decoded as ``base[T]`` (list, tuple, set or frozenset) and
    passed to ``factory`` (default: ``tp`` itself). Encoding iterates the
    container. ``FlpList`` is registered this way by default.
    """
    if not isinstance(tp, type):
        raise TypeError(f"register_collection expects a class, got {tp!r}")
    if base not in _COLLECTION_BASES:
        raise TypeError(f"base must be one of {[b.__name__ for b in _COLLECTION_BASES]}")
    _register_defaults()
    with _registry_lock:
        _value_handlers.pop(tp, None)
        _collection_handlers[tp] = _CollectionHandler(tp, factory or tp, base)
        _bump()


def unregister_type(tp: type) -> bool:
    """Remove a registered value or collection type. Returns True if one was removed."""
    _register_defaults()
    with _registry_lock:
        removed = (_value_handlers.pop(tp, None) or _collection_handlers.pop(tp, None)) is not None
        if removed:
            _bump()
        return removed


def _register_defaults() -> None:
    """Built-in registrations; never override what the user registered first."""
    global _defaults_loaded
    if _defaults_loaded:
        return
    with _registry_lock:
        if _defaults_loaded:
            return
        from flpit.core.linq import FlpList

        _collection_handlers.setdefault(FlpList, _CollectionHandler(FlpList, FlpList, list))

        try:
            import whenever  # pyrefly: ignore [missing-import]
        except ImportError:
            whenever = None

        if whenever is not None:
            for name in (
                    "Instant", "OffsetDateTime", "ZonedDateTime", "PlainDateTime",
                    "Date", "Time", "YearMonth", "MonthDay",
                    "TimeDelta", "ItemizedDelta", "ItemizedDateDelta",
            ):
                tp = getattr(whenever, name, None)
                if tp is None or tp in _value_handlers or tp in _collection_handlers:
                    continue
                _value_handlers[tp] = _ValueHandler(tp, tp.parse_iso, tp.format_iso)

        _defaults_loaded = True
        _bump()


def value_handler(tp: Any) -> _ValueHandler | None:
    _register_defaults()
    try:
        return _value_handlers.get(tp)
    except TypeError:  # unhashable annotation
        return None


def collection_handler(tp: Any) -> _CollectionHandler | None:
    _register_defaults()
    try:
        return _collection_handlers.get(tp)
    except TypeError:
        return None


def registry_version() -> int:
    _register_defaults()
    return _registry_version


_BUILTIN_EMPTY_FACTORIES: tuple[Any, ...] = (list, dict, set, frozenset, bytearray)


def is_empty_collection_factory(factory: Any) -> bool:
    """Default factories whose empty value is omitted when excluding defaults.

    Only builtin containers qualify (that is what msgspec can detect); an empty
    registered collection such as ``FlpList`` is always written as ``[]``.
    """
    return factory in _BUILTIN_EMPTY_FACTORIES
