from typing import Annotated
import dataclasses
import re
import sys
import types
import typing

import threading
from dataclasses import MISSING, dataclass
from functools import lru_cache
from typing import Any, ForwardRef, get_args, get_origin, get_type_hints
from hashlib import blake2s

import msgspec

from enum import StrEnum

class JsonNamingPolicy(StrEnum):
    lower_case = "lower"
    upper_case = "upper"
    camel_case = "camel"
    pascal_case = "pascal"
    kebap_case = "kebab"


@dataclass(slots=True, frozen=True)
class JsonSerializerOptions:
    naming_policy: JsonNamingPolicy = JsonNamingPolicy.camel_case
    write_indented: bool = False
    native:bool=False
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
        settings = self.naming_policy.value
        return blake2s(settings.encode(), digest_size=6).hexdigest()

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
# Module and annotation utilities
# ---------------------------------------------------------------------

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
            if not field.init:
                continue

            pending.extend(
                _nested_dataclasses(info.hints[field.name])
            )

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
) -> list[tuple[Any, ...]]:
    definitions: list[tuple[Any, ...]] = []

    for field in dataclasses.fields(info.source):
        if not field.init:
            continue

        annotation = _rewrite_type(
            info.hints[field.name],
            info,
            graph,
        )

        if field.default is not MISSING:
            spec = (field.name, annotation, field.default)

        elif field.default_factory is not MISSING:
            spec = (
                field.name,
                annotation,
                msgspec.field(
                    default_factory=field.default_factory
                ),
            )

        # for now... no enforcing of explicit null in json
        elif _allows_none(info.hints[field.name]):
            spec = (field.name, annotation, None)

        else:
            spec = (field.name, annotation)

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
                and callable(value)
        )
    # pyrefly: ignore [implicit-any-lambda]
    } | {  "__class__": property(lambda self, cls=source: cls) }

def _build_graph(
        roots: tuple[type, ...],
        jso: JsonSerializerOptions,
) -> dict[type, _WireType]:
    graph = _discover_graph(roots)

    for wt in graph.values():
        wt.struct = msgspec.defstruct(
            wt.class_name,
            _struct_fields(wt, graph),
            module=wt.module_name,
            namespace=_behavior_namespace(wt.source),
            rename=jso.naming_policy.value,
            kw_only=True,
            omit_defaults=True, # don't render nulls
            forbid_unknown_fields=False, # ensure ignoring unknow fields!
        )

    _register_forward_refs(graph)

    for wt in graph.values():
        msgspec.inspect.type_info(wt.struct)

    # Publish the readable generated class names.
    for wt in graph.values():
        setattr(wt.namespace, wt.class_name, wt.struct)

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

def _cached_graph(roots:tuple[object, ...], jso: JsonSerializerOptions):
    with _registry_lock:
        _jso_registry[jso.fingerprint] = jso

    return _wrapped_lru(roots, jso.fingerprint)

def wire_type_for(
        target_type: type,
        jso: JsonSerializerOptions,
):
    roots = tuple(_nested_dataclasses(target_type))

    if not roots:
        raise TypeError(
            "Only @dataclass are supported!, "
            f"got {target_type!r}"
        )

    # Normalize the root set so User and list[User] share the graph.
    graph_roots = tuple(sorted(set(roots), key=id))

    graph = _cached_graph(
        graph_roots,
        jso,
    )

    return _rewrite_type(
        target_type,
        graph[roots[0]],
        graph,
        resolve=True,
    )


def decode_dataclass(
        data: bytes | str,
        target: type,
        jso: JsonSerializerOptions|None=None
):
    if jso is None:
        jso = JsonSerializerOptions()

    wire_type = wire_type_for(target, jso)
    parsed = msgspec.json.decode(data, type=wire_type)

    if jso.native:
        return parsed

    return msgspec.convert(
        parsed,
        target,
        from_attributes=True,
    )

def encode_dataclass[T](
        data: Any,
        target: type[T],
        jso: JsonSerializerOptions|None=None
) -> bytes:
    if jso is None:
        jso = JsonSerializerOptions()

    wire_type = wire_type_for(target, jso)
    wire_obj = msgspec.convert(data, wire_type, from_attributes=True)
    return msgspec.json.encode(wire_obj)

