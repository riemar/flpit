from __future__ import annotations

from collections.abc import Iterable
import dataclasses
import re
import sys
import threading
import types
import typing
from dataclasses import MISSING, dataclass
from enum import StrEnum
from functools import lru_cache
from hashlib import blake2s
from typing import Annotated, Any, ForwardRef, get_args, get_origin, get_type_hints, Callable

import msgspec


class JsonNamingPolicy(StrEnum):
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

class JsonIgnore:
    def __class_getitem__[T](cls, item: type[T]) -> Any:
        return Annotated[item, cls]

class JsonInclude:
    def __class_getitem__[T](cls, item: type[T]) -> Any:
        return Annotated[item, cls]

class JsonProperty:
    def __class_getitem__[T](cls, item: tuple[type[T], str]) -> Any:
        target_type, json_name = item
        return Annotated[target_type, cls(json_name)]

    def __init__(self, name: str):
        self.name = name

JIgnore = JsonIgnore
JInclude = JsonInclude
JProp = JsonProperty

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
# Never imagined this would be required to have a proper lib behavior
# ---------------------------------------------------------------------

def _apply_naming_policy(name: str, policy: JsonNamingPolicy) -> str:
    """
    Splits any attribute name (snake_case, PascalCase, UPPER_CASE)
    into individual tokens and formats them according to the target policy.
    """
    # 1. Check if there is a leading underscore and save it
    prefix = "_" if name.startswith("_") else ""
    clean_name = name.lstrip("_")

    # 2. Tokenize only the clean part of the string
    tokens = [t for t in re.split(r'_(?=[a-zA-Z])|(?<=[a-z])(?=[A-Z])', clean_name) if t]
    if not tokens:
        return name

    if policy == JsonNamingPolicy.lower:
        result = "".join(t.lower() for t in tokens)

    if policy == JsonNamingPolicy.upper:
        result = "".join(t.upper() for t in tokens)

    if policy == JsonNamingPolicy.pascal:
        result = "".join(t.capitalize() for t in tokens)

    if policy == JsonNamingPolicy.kebap:
        result = "-".join(t.lower() for t in tokens)

    if policy == JsonNamingPolicy.camel:
        # Lowercase the first token completely, capitalize all subsequent tokens
        result = tokens[0].lower() + "".join(t.capitalize() for t in tokens[1:])

    else:
        result = clean_name

    return prefix + result



def _generated_module(source: type) -> types.ModuleType:
    """Generates the required module definition for our runtime only dynamic msgspec.struct"""
    name = f"flpit.json._generated.{source.__module__}"

    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module

    return module


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
    ignored = any(item is JsonIgnore for item in metadata)
    included = any(item is JsonInclude for item in metadata)
    json_name = next(
        (item.name for item in metadata if isinstance(item, JsonProperty)),
        None,
    )
    remaining = tuple(
        item
        for item in metadata
        if item is not JsonIgnore
        and item is not JsonInclude
        and not isinstance(item, JsonProperty)
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
        return tp

    args = get_args(tp)

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


def _allows_none(tp: Any) -> bool:
    if get_origin(tp) is typing.Annotated:
        tp = get_args(tp)[0]

    return type(None) in get_args(tp)

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
            kw_only=False,
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


@lru_cache(maxsize=256)
def _get_decoder(wire_type: Any):
    return msgspec.json.Decoder(type=wire_type)


_JSON_ENCODER = msgspec.json.Encoder()


class JsonConvert:

    @staticmethod
    def deserialize[T](
            data: bytes | str,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> T:
        if jso is None:
            jso = JsonSerializerOptions()

        wire_type = wire_type_for(target, jso)
        parsed = _get_decoder(wire_type).decode(data)

        if jso.native:
            return parsed

        result = msgspec.convert(
            parsed,
            target,
            from_attributes=True,
        )

        return result

    @staticmethod
    def serialize[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> str:
        return JsonConvert.serialize_bytes(data, target, jso).decode("utf-8")

    @staticmethod
    def serialize_bytes[T](
            data: Any,
            target: type[T],
            jso: JsonSerializerOptions | None = None
    ) -> bytes:
        if jso is None:
            jso = JsonSerializerOptions()

        wire_type = wire_type_for(target, jso)
        wire_obj = msgspec.convert(data, wire_type, from_attributes=True)
        return _JSON_ENCODER.encode(wire_obj)

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

            wire_obj = msgspec.convert(item, wire_type, from_attributes=True)
            write(_JSON_ENCODER.encode(wire_obj))
            first = False

        write(b']')


