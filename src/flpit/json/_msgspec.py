"""msgspec backend for flpit.json.

Builds msgspec Structs mirroring the dataclasses (renamed fields, omitted
defaults, unknown-field policy), decodes into them and converts the result into
the real dataclasses. Types msgspec does not know go through the registry via
dec_hook / enc_hook.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import dataclasses
import re
import sys
import threading
import types
import typing
from dataclasses import MISSING, dataclass
from functools import lru_cache
from typing import Any, ForwardRef, get_args, get_origin, get_type_hints

import msgspec

from flpit.json import _core
from flpit.json._core import (
    JsonDefaultHandling,
    JsonDeserializationError,
    JsonSerializationError,
    JsonSerializerOptions,
    JsonUnknownFieldHandling,
    _allows_none,
    _apply_naming_policy,
    _field_directives,
    _get_property_directive,
    _is_dataclass_type,
    _nested_dataclasses,
)

class _WireCollection[T](list):  # type: ignore[type-arg]
    """Stand-in for registered collections (e.g. FlpList) inside generated structs.

    A list subclass, so msgspec encodes it natively; the dataclass side gets the
    registered collection type back through ``_dec_hook``.
    """


# ---------------------------------------------------------------------
# Generated type metadata
# ---------------------------------------------------------------------

@dataclass(slots=True, eq=False)
class _WireType:
    source: type
    """The source type to build a msgspec.struct for"""
    hints: dict[str, Any]
    namespace: types.ModuleType
    """the name space we are targeting"""
    struct: type | None = None

    @property
    def module_name(self: _WireType) -> str:
        return self.namespace.__name__

    @property
    def class_name(self: _WireType) -> str:
        return self.source.__name__

    @property
    def ref_name(self: _WireType) -> str:
        identity = (
            f"{self.source.__module__}_{self.source.__qualname__}"
        )
        return "_ref_" + re.sub(r"\W", "_", identity)


# ---------------------------------------------------------------------

def _generated_module(source: type) -> types.ModuleType:
    """Generates the required module definition for our runtime only dynamic msgspec.struct"""
    name = f"flpit.json._generated.{source.__module__}"

    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module

    return module


def _rewrite_type(
        tp: Any,
        owner: _WireType,
        graph: dict[type, _WireType],
        *,
        resolve: bool = False,
) -> Any:
    """Replace source dataclasses with generated Structs or ForwardRefs."""
    if tp is getattr(typing, "Self", None):
        info = owner
        return info.struct if resolve else ForwardRef(info.ref_name)

    if _is_dataclass_type(tp):
        info = graph[tp]
        return info.struct if resolve else ForwardRef(info.ref_name)

    if isinstance(tp, list):
        return [
            _rewrite_type(item, owner, graph, resolve=resolve)
            for item in tp
        ]

    if isinstance(tp, tuple):
        return tuple(
            _rewrite_type(item, owner, graph, resolve=resolve)
            for item in tp
        )

    origin = get_origin(tp)

    if origin is None or origin is typing.Literal:
        if origin is None and _core.collection_handler(tp) is not None:
            return _WireCollection[Any]
        return tp

    args = get_args(tp)

    if _core.collection_handler(origin) is not None:
        # FlpList[T] & co. travel as plain lists inside the generated structs:
        # msgspec encodes them natively; _dec_hook rebuilds the real type on the dataclass side.
        wire_generic: Any = _WireCollection
        return wire_generic[_rewrite_type(args[0], owner, graph, resolve=resolve) if args else Any]

    if origin is typing.Annotated:
        base = _rewrite_type(
            args[0], owner, graph, resolve=resolve
        )
        return typing.Annotated[(base, *args[1:])]

    rewritten: tuple[Any, ...] = tuple(
        _rewrite_type(arg, owner, graph, resolve=resolve)
        for arg in args
    )

    if origin in (typing.Union, types.UnionType):
        union: Any = typing.Union # with all the magic here, there's no way to make typing really happy
        return union[rewritten]

    params = rewritten[0] if len(rewritten) == 1 else rewritten

    try:
        return origin[params]
    except (TypeError, AttributeError) as exc:
        copier = getattr(tp, "copy_with", None)
        if copier is not None:
            return copier(rewritten)

        raise TypeError(
            f"Cannot rewrite annotation {tp!r}"
        ) from exc


# ---------------------------------------------------------------------
# Graph discovery
# ---------------------------------------------------------------------


def _discover_graph(
        roots: tuple[type, ...],
) -> dict[type, _WireType]:
    """Discover reachable dataclasses and resolve their annotations."""
    graph: dict[type, _WireType] = {}
    pending = list(roots)

    while pending:
        source = pending.pop()

        if source in graph:
            continue

        info = _WireType(
            source=source,
            hints=get_type_hints(source, include_extras=True),
            namespace=_generated_module(source),
        )
        graph[source] = info

        for field in dataclasses.fields(source):
            annotation, ignored, included, _ = _field_directives(
                info.hints[field.name]
            )
            if ignored:
                continue

            pending.extend(_nested_dataclasses(annotation))

    return graph


# ---------------------------------------------------------------------
# Struct construction
# ---------------------------------------------------------------------


def _struct_fields(
        info: _WireType,
        graph: dict[type, _WireType],
        jso: JsonSerializerOptions,
) -> list[tuple[Any, ...]]:
    definitions: list[tuple[Any, ...]] = []
    dataclass_fields = {f.name for f in dataclasses.fields(info.source)}

    # 1. Process regular fields (regardless of init=True or init=False)
    for field in dataclasses.fields(info.source):
        source_annotation = info.hints[field.name]
        annotation, ignored, included, json_name = _field_directives(source_annotation)

        if ignored:
            continue

        # If the field starts with an underscore, it MUST have JInclude or JProp attached!
        if field.name.startswith("_") and not (included or json_name is not None):
            continue

        annotation = _rewrite_type(annotation, info, graph)
        wire_name = json_name if json_name is not None else _apply_naming_policy(field.name, jso.naming_policy)

        # Resolve structural field default values cleanly
        if field.default is not MISSING:
            default_val = field.default
            has_default = True
        elif field.default_factory is not MISSING:
            default_val = msgspec.field(default_factory=field.default_factory)
            has_default = True
        elif _allows_none(annotation):
            default_val = None
            has_default = True
        else:
            default_val = MISSING
            has_default = False

        field_options: dict[str, Any] = {"name": wire_name}
        if has_default:
            if field.default_factory is not MISSING:
                field_options["default_factory"] = field.default_factory
            else:
                field_options["default"] = default_val

        spec = (field.name, annotation, msgspec.field(**field_options))
        definitions.append(spec)

    # 2. Process properties automatically
    for name, value in vars(info.source).items():
        if isinstance(value, property) and name not in dataclass_fields:
            # Extract the type annotation directly from the getter function signature
            if value.fset is not None:
                _, _, included, json_name = _get_property_directive(value.fset)

                if included or json_name is not None:
                    raise ValueError(
                        f"{info.source.__qualname__}.{name}: "
                        "fplit.json with msgspec backend doesn't support "
                        "JProp/JInclude on property setters"
                    )

            annotation, ignored, included, json_name = _get_property_directive(value.fget)

            if not included and json_name is None:
                continue

            annotation = _rewrite_type(annotation, info, graph)
            wire_name = json_name if json_name is not None else _apply_naming_policy(name, jso.naming_policy)

            # Map the field into the C-struct. Default to None so the inbound parser never complains.
            spec = (name, annotation, msgspec.field(name=wire_name, default=None))
            definitions.append(spec)


    return definitions


def _register_forward_refs(
        graph: dict[type, _WireType],
) -> None:
    """Expose every graph reference in each participating module."""
    namespaces = []

    for info in graph.values():
        if not any(info.namespace is ns for ns in namespaces):
            namespaces.append(info.namespace)

    for namespace in namespaces:
        for info in graph.values():
            setattr(namespace, info.ref_name, info.struct)


def _behavior_namespace(source: type) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(source).items()
        if (
                not name.startswith("__")
                and (callable(value) or isinstance(value, property))
        )
        # pyrefly: ignore [implicit-any-lambda]
    } | {  "__class__": property(lambda self, cls=source: cls) }


def _create_structs(
        graph: dict[type, _WireType],
        jso: JsonSerializerOptions,
) -> None:
    """Create the generated msgspec structs for every node in the graph."""
    for wt in graph.values():
        fields = _struct_fields(wt, graph, jso)
        wt.struct = msgspec.defstruct(
            wt.class_name,
            fields,
            module=wt.module_name,
            namespace=_behavior_namespace(wt.source),
            rename=None,
            kw_only=True,  # optional fields may precede required ones (dataclass order)
            omit_defaults=jso.default_handling.value == JsonDefaultHandling.exclude,
            forbid_unknown_fields=jso.unknown_field_handling.value == JsonUnknownFieldHandling.disallow,
        )


def _validate_structs(graph: dict[type, _WireType]) -> None:
    """Force msgspec to inspect each generated struct after refs are registered."""
    for wt in graph.values():
        msgspec.inspect.type_info(wt.struct)


def _publish_structs(graph: dict[type, _WireType]) -> None:
    # Publish the readable generated class names.
    for wt in graph.values():
        setattr(wt.namespace, wt.class_name, wt.struct)


def _build_graph(
        roots: tuple[type, ...],
        jso: JsonSerializerOptions,
) -> dict[type, _WireType]:
    graph = _discover_graph(roots)
    _create_structs(graph, jso)
    _register_forward_refs(graph)
    _validate_structs(graph)
    _publish_structs(graph)
    return graph


# ---------------------------------------------------------------------
# Cache and public API
# ---------------------------------------------------------------------

# we must only build new when the
_jso_registry: dict[str, JsonSerializerOptions] = {}
_registry_lock = threading.Lock()


@lru_cache(maxsize=None)
def _wrapped_lru(roots: tuple[type, ...], jso_id: str):
    with _registry_lock:
        jso = _jso_registry[jso_id]

    return _build_graph(roots, jso)


@lru_cache(maxsize=None)
def _cached_wire_type(target_type: object, jso_id: str):
    roots = tuple(_nested_dataclasses(target_type))

    if not roots:
        raise TypeError(
            "Only @dataclass are supported!, "
            f"got {target_type!r}"
        )

    graph_roots = tuple(sorted(set(roots), key=id))
    graph = _wrapped_lru(graph_roots, jso_id)

    return _rewrite_type(
        target_type,
        graph[roots[0]],
        graph,
        resolve=True,
    )


def wire_type_for(target_type: type, jso: JsonSerializerOptions) -> type:
    jso_id = jso.fingerprint

    with _registry_lock:
        _jso_registry[jso_id] = jso

    return _cached_wire_type(target_type, jso_id)



# ---------------------------------------------------------------------
# Registry hooks
# ---------------------------------------------------------------------

def _dec_hook(tp: Any, obj: Any) -> Any:
    """Called by msgspec for every type it doesn't know (registry types).

    It runs on three occasions: decoding JSON (obj is the raw JSON value),
    converting the generated Struct into the dataclass and converting the
    dataclass into the Struct when serializing (obj is already the target
    kind of object in the last two).
    """
    origin = get_origin(tp) or tp
    if origin is _WireCollection:
        if isinstance(obj, (str, bytes, bytearray, Mapping)) or not isinstance(obj, Iterable):
            raise msgspec.ValidationError(f"Expected `array`, got `{type(obj).__name__}`")
        args = get_args(tp)
        items = obj if type(obj) is list else list(obj)
        return _WireCollection(msgspec.convert(items, list[args[0]] if args else list,
                                               from_attributes=True, dec_hook=_dec_hook))

    collection = _core.collection_handler(origin)
    if collection is not None:
        if isinstance(obj, (str, bytes, bytearray, Mapping)) or not isinstance(obj, Iterable):
            raise msgspec.ValidationError(f"Expected `array`, got `{type(obj).__name__}`")
        args = get_args(tp)
        if not args:
            base: Any = collection.base
        elif collection.base is tuple:
            base = tuple[args[0], ...]
        else:
            base = typing.cast(Any, collection.base)[args[0]]
        items = obj if type(obj) is list else list(obj)
        converted = msgspec.convert(items, base, from_attributes=True, dec_hook=_dec_hook)
        return collection.factory(converted)

    handler = _core.value_handler(tp)
    if handler is not None:
        if isinstance(obj, tp):
            return obj
        try:
            return handler.decode(obj)
        except (ValueError, TypeError) as exc:
            raise msgspec.ValidationError(f"Invalid `{tp.__name__}`: {exc}") from exc

    raise msgspec.ValidationError(f"flpit.json: unsupported type {getattr(tp, '__qualname__', tp)!r}")


def _enc_hook(obj: Any) -> Any:
    handler = _core.value_handler(type(obj))
    if handler is not None:
        return handler.encode(obj)
    if _core.collection_handler(type(obj)) is not None:
        return list(obj)
    raise NotImplementedError(f"flpit.json: cannot serialize {type(obj).__qualname__}")


@lru_cache(maxsize=256)
def _get_decoder(wire_type: Any):
    return msgspec.json.Decoder(type=wire_type, dec_hook=_dec_hook)


_JSON_ENCODER = msgspec.json.Encoder(enc_hook=_enc_hook)

class Backend:
    name = "msgspec"


    @staticmethod
    def deserialize[T](
            data: bytes | str,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> T:
        if data is None:
            raise JsonDeserializationError("data must not be None")

        if jso is None:
            jso = JsonSerializerOptions()

        wire_type = wire_type_for(target, jso)

        try:
            parsed = _get_decoder(wire_type).decode(data)

            if jso.native:
                return parsed

            result = msgspec.convert(
                parsed,
                target,
                from_attributes=True,
                dec_hook=_dec_hook,
            )

            return result
        except msgspec.MsgspecError as exc:
            raise JsonDeserializationError(str(exc)) from exc

    @staticmethod
    def serialize[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> str:
        if data is None:
            raise JsonSerializationError("data must not be None")

        return Backend.serialize_bytes(data, target, jso).decode("utf-8")

    @staticmethod
    def serialize_bytes[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> bytes:
        if jso is None:
            jso = JsonSerializerOptions()

        wire_type = wire_type_for(target, jso)
        try:
            wire_obj = msgspec.convert(data, wire_type, from_attributes=True, dec_hook=_dec_hook)
            return _JSON_ENCODER.encode(wire_obj)
        except msgspec.MsgspecError as exc:
            raise JsonSerializationError(str(exc)) from exc

    @staticmethod
    def serialize_to[T](
            it: Iterable[T],
            target: type[T],
            output: typing.BinaryIO | typing.TextIO,
            jso: JsonSerializerOptions | None = None,
    ) -> None:
        import io
        if jso is None:
            jso = JsonSerializerOptions()

        if isinstance(output, io.TextIOBase):
            def write(data: bytes) -> None:
                output.write(data.decode("utf-8"))

        elif isinstance(
                output,
                (io.BufferedIOBase, io.RawIOBase),
        ):
            def write(data: bytes) -> None:
                output.write(data)
        else:
            raise TypeError("output must be ByteWriter or TextWriter")

        first = True
        wire_type = wire_type_for(target, jso)

        write(b"[")

        for item in iter(it):
            if not first:
                write(b",")

            wire_obj = msgspec.convert(item, wire_type, from_attributes=True, dec_hook=_dec_hook)
            write(_JSON_ENCODER.encode(wire_obj))
            first = False

        write(b']')
