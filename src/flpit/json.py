from dataclasses import fields
from typing import Annotated, Any, TypeVar, get_args, get_origin, get_type_hints
import msgspec

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Metadata Annotation Markers
# ---------------------------------------------------------------------------
class JsonIgnore:
    def __class_getitem__(cls, item: type[T]) -> Any:
        return Annotated[item, cls]

class JsonInclude:
    def __class_getitem__(cls, item: type[T]) -> Any:
        return Annotated[item, cls]

class JsonProperty:
    def __class_getitem__(cls, item: tuple[type[T], str]) -> Any:
        target_type, json_name = item
        return Annotated[target_type, cls(json_name)]

    def __init__(self, name: str):
        self.name = name

JIgnore = JsonIgnore
JInclude = JsonInclude
JProp = JsonProperty


# ---------------------------------------------------------------------------
# High-Performance Compiler Engine
# ---------------------------------------------------------------------------
class NativeEngine:
    def __init__(self) -> None:
        self._outbound_structs: dict[type, type] = {}

    def _parse_annotation(self, hint: Any, name: str) -> tuple[Any, str | None, bool, bool]:
        if get_origin(hint) is not Annotated:
            should_include = not name.startswith("_")
            return hint, None, should_include, False

        args = get_args(hint)
        base_type = args[0]
        metadata = args[1:]

        has_ignore = any(item is JsonIgnore for item in metadata)
        has_include = any(item is JsonInclude for item in metadata)
        aliases = [item.name for item in metadata if isinstance(item, JsonProperty)]
        alias = aliases[-1] if aliases else None

        explicit_include = has_include or (alias is not None)
        should_include = explicit_include if name.startswith("_") else not has_ignore

        return base_type, alias, should_include, has_ignore

    def register(self, cls: type) -> None:
        if cls in self._outbound_structs:
            return

        # Read class-level hints for memory fields
        class_hints = get_type_hints(cls, include_extras=True)
        struct_fields = []

        # 1. Process regular dataclass fields
        for f in fields(cls):
            if not f.init:
                continue

            hint = class_hints.get(f.name, f.type)
            base_type, alias, should_include, has_ignore = self._parse_annotation(hint, f.name)

            if should_include and not has_ignore:
                field_kwargs = {"default": None}
                if alias:
                    field_kwargs["name"] = alias
                struct_fields.append((f.name, base_type, msgspec.field(**field_kwargs)))

        # 2. Process properties by inspecting class attributes safely
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name, None)
            if isinstance(attr, property) and attr.fget is not None:
                # Extract the type hints directly from the property's getter function
                prop_hints = get_type_hints(attr.fget, include_extras=True)
                return_hint = prop_hints.get("return", Any)

                base_type, alias, should_include, has_ignore = self._parse_annotation(return_hint, attr_name)

                if should_include and not has_ignore:
                    field_kwargs = {"default": None}
                    if alias:
                        field_kwargs["name"] = alias
                    struct_fields.append((attr_name, base_type, msgspec.field(**field_kwargs)))

        self._outbound_structs[cls] = msgspec.defstruct(f"Out_{cls.__name__}", struct_fields, rename="camel")

    def encode(self, obj: Any) -> bytes:
        cls = type(obj)
        self.register(cls)
        wire_obj = msgspec.convert(obj, self._outbound_structs[cls], from_attributes=True)
        return msgspec.json.encode(wire_obj)

    def decode(self, data: bytes, type: type[T]) -> T:
        return msgspec.json.decode(data, type=type, strict=False)