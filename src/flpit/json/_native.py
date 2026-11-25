"""Native (pure Python, stdlib ``json``) backend for flpit.json.

Implements the same contract as the msgspec backend: strict type checking,
naming policies, JProp / JIgnore / JInclude, default and unknown-field handling,
properties, temporal formats (RFC 3339 / ISO 8601 durations as msgspec reads
and writes them) and the type registry.

For every (type, options) pair a tree of small converter functions is built
once and cached; parsing and writing is done by the stdlib ``json`` module.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import datetime as dt
import decimal
import enum
import io
import json
import math
import re
import threading
import types
import typing
import uuid
from collections.abc import Callable, Iterable
from dataclasses import MISSING
from typing import Any, get_args, get_origin, get_type_hints

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
    _nested_dataclasses,
)

Converter = Callable[[Any], Any]


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------

class _Invalid(Exception):
    """Conversion failure with a JSON path, e.g. ``$.employees[3].salary``."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.path: list[str | int] = []

    def at(self, segment: str | int) -> _Invalid:
        self.path.insert(0, segment)
        return self

    @typing.override
    def __str__(self) -> str:
        if not self.path:
            return self.message
        location = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in self.path)
        return f"{self.message} - at `{location}`"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _expected(what: str, value: Any) -> _Invalid:
    return _Invalid(f"Expected `{what}`, got `{_kind(value)}`")


# ---------------------------------------------------------------------
# Temporal formats (mirrors msgspec: RFC 3339 subset + ISO 8601 durations)
# ---------------------------------------------------------------------

_DATE = r"(\d{4})-(\d{2})-(\d{2})"
_TIME = r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
_OFFSET = r"(?:([zZ])|([+-])(\d{2}):?(\d{2}))"
_DATE_RE = re.compile(_DATE + r"\Z")
_TIME_RE = re.compile(_TIME + _OFFSET + r"?\Z")
_DATETIME_RE = re.compile(_DATE + r"[Tt ]" + _TIME + _OFFSET + r"?\Z")
_DURATION_RE = re.compile(
    r"([+-])?[Pp]"
    r"(?:(\d+(?:\.\d+)?)[Dd])?"
    r"(?:[Tt](?=\d)(?:(\d+(?:\.\d+)?)[Hh])?(?:(\d+(?:\.\d+)?)[Mm])?(?:(\d+(?:\.\d+)?)[Ss])?)?\Z"
)


def _micros(fraction: str | None) -> int:
    """Fractional seconds rounded to microseconds (may return 1_000_000)."""
    if not fraction:
        return 0
    padded = (fraction[:7]).ljust(7, "0")
    return (int(padded) + 5) // 10


def _tz(z: str | None, sign: str | None, hh: str | None, mm: str | None) -> dt.tzinfo | None:
    if z:
        return dt.timezone.utc
    if sign is None:
        return None
    hours, minutes = int(hh), int(mm)  # type: ignore[arg-type]
    if hours > 23 or minutes > 59:
        raise ValueError("offset out of range")
    if hours == 0 and minutes == 0:
        return dt.timezone.utc
    offset = dt.timedelta(hours=hours, minutes=minutes)
    return dt.timezone(-offset if sign == "-" else offset)


def _parse_date(value: str) -> dt.date:
    m = _DATE_RE.match(value)
    if m is None:
        raise ValueError
    return dt.date(int(m[1]), int(m[2]), int(m[3]))


def _parse_time(value: str) -> dt.time:
    m = _TIME_RE.match(value)
    if m is None:
        raise ValueError
    micro = _micros(m[4])
    tz = _tz(m[5], m[6], m[7], m[8])
    base = dt.datetime(2000, 1, 1, int(m[1]), int(m[2]), int(m[3]))
    if micro:
        base += dt.timedelta(microseconds=micro)  # like msgspec: rounding may wrap past midnight
    return base.time().replace(tzinfo=tz)


def _parse_datetime(value: str) -> dt.datetime:
    m = _DATETIME_RE.match(value)
    if m is None:
        raise ValueError
    tz = _tz(m[8], m[9], m[10], m[11])
    result = dt.datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6]), tzinfo=tz)
    micro = _micros(m[7])
    return result + dt.timedelta(microseconds=micro) if micro else result


def _parse_timedelta(value: str) -> dt.timedelta:
    m = _DURATION_RE.match(value)
    if m is None or not any(m.group(i) for i in range(2, 6)):
        raise ValueError
    days, hours, minutes, seconds = (decimal.Decimal(m[i]) if m[i] else decimal.Decimal(0) for i in range(2, 6))
    total_us = ((days * 86400 + hours * 3600 + minutes * 60 + seconds) * 1_000_000).to_integral_value(
        rounding=decimal.ROUND_HALF_EVEN)
    result = dt.timedelta(microseconds=int(total_us))
    return -result if m[1] == "-" else result


def _format_offset(value: dt.datetime | dt.time) -> str:
    offset = value.utcoffset()
    if offset is None:
        return ""
    minutes = int(offset.total_seconds() / 60)
    if minutes == 0:
        return "Z"
    sign = "-" if minutes < 0 else "+"
    hours, minutes = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _format_time_part(value: dt.datetime | dt.time) -> str:
    text = f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    if value.microsecond:
        text += f".{value.microsecond:06d}"
    return text


def _format_datetime(value: dt.datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{_format_time_part(value)}{_format_offset(value)}"


def _format_time(value: dt.time) -> str:
    return _format_time_part(value) + _format_offset(value)


def _format_timedelta(value: dt.timedelta) -> str:
    if not value:
        return "P0D"
    sign = "-" if value < dt.timedelta(0) else ""
    value = abs(value)
    text = f"{sign}P"
    if value.days:
        text += f"{value.days}D"
    if value.seconds or value.microseconds:
        seconds = str(value.seconds)
        if value.microseconds:
            seconds += f".{value.microseconds:06d}".rstrip("0")
        text += f"T{seconds}S"
    return text


_INT_RE = re.compile(r"[+-]?\d+\Z")   # integer dict keys


# ---------------------------------------------------------------------
# Field specs shared by decoder and encoder
# ---------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _FieldSpec:
    name: str
    wire: str
    annotation: Any
    init: bool
    default: Any               # MISSING when none
    default_factory: Any       # MISSING when none
    implicit_none: bool        # optional without default -> None


@dataclasses.dataclass(slots=True)
class _PropertySpec:
    name: str
    wire: str
    annotation: Any


def _class_layout(cls: type, jso: JsonSerializerOptions) -> tuple[list[_FieldSpec], list[_PropertySpec]]:
    hints = get_type_hints(cls, include_extras=True)
    fields: list[_FieldSpec] = []
    seen: dict[str, str] = {}

    def claim(wire: str, name: str) -> None:
        if wire in seen:
            raise ValueError(
                f"{cls.__qualname__}: '{name}' and '{seen[wire]}' both map to JSON name '{wire}'")
        seen[wire] = name

    for field in dataclasses.fields(cls):
        annotation, ignored, included, json_name = _field_directives(hints[field.name])
        if ignored:
            continue
        if field.name.startswith("_") and not (included or json_name is not None):
            continue
        wire = json_name if json_name is not None else _apply_naming_policy(field.name, jso.naming_policy)
        claim(wire, field.name)
        fields.append(_FieldSpec(
            name=field.name,
            wire=wire,
            annotation=annotation,
            init=field.init,
            default=field.default,
            default_factory=field.default_factory,
            implicit_none=(field.default is MISSING and field.default_factory is MISSING
                           and _allows_none(annotation)),
        ))

    field_names = {f.name for f in dataclasses.fields(cls)}
    properties: list[_PropertySpec] = []
    for name, value in vars(cls).copy().items():
        if not isinstance(value, property) or name in field_names:
            continue
        if value.fset is not None:
            _, _, included, json_name = _get_property_directive(value.fset)
            if included or json_name is not None:
                raise ValueError(
                    f"{cls.__qualname__}.{name}: JProp/JInclude on property setters is not supported")
        annotation, _, included, json_name = _get_property_directive(value.fget)
        if not included and json_name is None:
            continue
        wire = json_name if json_name is not None else _apply_naming_policy(name, jso.naming_policy)
        claim(wire, name)
        properties.append(_PropertySpec(name, wire, annotation))

    return fields, properties


def _strip_annotated(tp: Any) -> Any:
    while get_origin(tp) is typing.Annotated:
        tp = get_args(tp)[0]
    return tp


def _is_union(origin: Any) -> bool:
    return origin is typing.Union or origin is types.UnionType


# ---------------------------------------------------------------------
# Decoder construction
# ---------------------------------------------------------------------

class _DecoderBuilder:
    def __init__(self, jso: JsonSerializerOptions) -> None:
        self.jso = jso
        self.memo: dict[Any, Converter] = {}

    def build(self, tp: Any) -> Converter:
        try:
            return self.memo[tp]
        except KeyError:
            pass
        except TypeError:  # unhashable annotation
            return self._make(tp)
        if dataclasses.is_dataclass(tp) and isinstance(tp, type):
            cell: list[Converter] = []
            self.memo[tp] = lambda v: cell[0](v)  # recursion guard
            real = self._dataclass(tp)
            cell.append(real)
            self.memo[tp] = real
            return real
        converter = self._make(tp)
        self.memo[tp] = converter
        return converter

    # -- scalars -------------------------------------------------------

    def _make(self, tp: Any) -> Converter:
        tp = _strip_annotated(tp)

        if tp is Any or tp is object:
            return lambda v: v
        if tp is None or tp is type(None):
            def dec_none(v: Any) -> None:
                if v is None:
                    return None
                raise _expected("null", v)
            return dec_none

        handler = _core.value_handler(tp)
        if handler is not None:
            decode = handler.decode

            def dec_registered(v: Any) -> Any:
                try:
                    return decode(v)
                except (ValueError, TypeError) as exc:
                    raise _Invalid(f"Invalid `{tp.__name__}`: {exc}") from exc
            return dec_registered

        if tp is bool:
            def dec_bool(v: Any) -> bool:
                if v is True or v is False:
                    return v
                raise _expected("bool", v)
            return dec_bool
        if tp is int:
            def dec_int(v: Any) -> int:
                if type(v) is int:
                    return v
                raise _expected("int", v)
            return dec_int
        if tp is float:
            def dec_float(v: Any) -> float:
                t = type(v)
                if t is float:
                    if math.isinf(v):
                        raise _Invalid("Number out of range")
                    return v
                if t is int:
                    return float(v)
                raise _expected("float", v)
            return dec_float
        if tp is str:
            def dec_str(v: Any) -> str:
                if type(v) is str:
                    return v
                raise _expected("str", v)
            return dec_str
        if tp in (bytes, bytearray):
            def dec_bytes(v: Any) -> Any:
                if type(v) is not str:
                    raise _expected("str", v)
                try:
                    raw = base64.b64decode(v, validate=True)
                except (binascii.Error, ValueError):
                    raise _Invalid("Invalid base64 encoded string") from None
                return raw if tp is bytes else bytearray(raw)
            return dec_bytes
        for temporal, parse, label in (
                (dt.datetime, _parse_datetime, "RFC3339 encoded datetime"),
                (dt.date, _parse_date, "RFC3339 encoded date"),
                (dt.time, _parse_time, "RFC3339 encoded time"),
                (dt.timedelta, _parse_timedelta, "ISO8601 duration"),
        ):
            if tp is temporal:
                return self._string_parser(parse, label, tp.__name__)
        if tp is uuid.UUID:
            return self._string_parser(uuid.UUID, "uuid", "uuid")
        if tp is decimal.Decimal:
            def dec_decimal(v: Any) -> decimal.Decimal:
                t = type(v)
                if t is str:
                    try:
                        return decimal.Decimal(v)
                    except decimal.InvalidOperation:
                        raise _Invalid("Invalid decimal string") from None
                if t is int or t is float:
                    return decimal.Decimal(str(v))
                raise _expected("decimal", v)
            return dec_decimal
        if isinstance(tp, type) and issubclass(tp, enum.Enum):
            return self._enum(tp)

        origin, args = get_origin(tp), get_args(tp)
        if origin is typing.Literal:
            return self._literal(args)
        if _is_union(origin):
            return self._union(args)

        collection = _core.collection_handler(origin or tp)
        if collection is not None:
            item_type = args[0] if args else Any
            base_type = tuple[item_type, ...] if collection.base is tuple else typing.cast(Any, collection.base)[item_type]
            inner = self.build(base_type)
            factory = collection.factory
            return lambda v: factory(inner(v))

        if origin is list or tp is list:
            return self._sequence(args[0] if args else Any, list)
        if origin is set or tp is set:
            return self._sequence(args[0] if args else Any, set)
        if origin is frozenset or tp is frozenset:
            return self._sequence(args[0] if args else Any, frozenset)
        if origin is tuple or tp is tuple:
            if not args or (len(args) == 2 and args[1] is Ellipsis):
                return self._sequence(args[0] if args else Any, tuple)
            return self._fixed_tuple(args)
        if origin is dict or tp is dict:
            key_type, value_type = args if args else (Any, Any)
            return self._dict(key_type, value_type)

        raise TypeError(f"flpit.json (native backend): type {tp!r} is not supported")

    def _string_parser(self, parse: Callable[[str], Any], label: str, kind: str) -> Converter:
        def dec(v: Any) -> Any:
            if type(v) is not str:
                raise _expected(kind, v)
            try:
                return parse(v)
            except ValueError:
                raise _Invalid(f"Invalid {label}") from None
        return dec

    def _enum(self, tp: type[enum.Enum]) -> Converter:
        by_value = {member.value: member for member in tp}

        def dec_enum(v: Any) -> Any:
            member = by_value.get(v) if not isinstance(v, (list, dict)) else None
            if member is None or type(member.value) is not type(v):
                raise _Invalid(f"Invalid enum value {v!r}")
            return member
        return dec_enum

    def _literal(self, values: tuple[Any, ...]) -> Converter:
        allowed = [(value, type(value)) for value in values]

        def dec_literal(v: Any) -> Any:
            for value, kind in allowed:
                if type(v) is kind and v == value:
                    return value
            raise _Invalid(f"Invalid enum value {v!r}")
        return dec_literal

    def _union(self, members: tuple[Any, ...]) -> Converter:
        non_none = [m for m in members if m is not type(None)]
        nullable = len(non_none) != len(members)
        if len(non_none) == 1:
            inner = self.build(non_none[0])
            if not nullable:
                return inner

            def dec_optional(v: Any) -> Any:
                if v is None:
                    return None
                return inner(v)
            return dec_optional

        decoders = [(m, self.build(m)) for m in non_none]
        int_first = [d for m, d in decoders if _strip_annotated(m) is int] + \
                    [d for m, d in decoders if _strip_annotated(m) is not int]
        plain = [d for _, d in decoders]
        names = " | ".join(getattr(m, "__name__", str(m)) for m in members)

        def dec_union(v: Any) -> Any:
            if v is None:
                if nullable:
                    return None
                raise _Invalid(f"Expected `{names}`, got `null`")
            for decode in (int_first if type(v) is int else plain):
                try:
                    return decode(v)
                except _Invalid:
                    continue
            raise _Invalid(f"Expected `{names}`, got `{_kind(v)}`")
        return dec_union

    def _sequence(self, item_type: Any, kind: type) -> Converter:
        item = self.build(item_type)
        identity = item_type is Any

        def dec_seq(v: Any) -> Any:
            if type(v) is not list:
                raise _expected("array", v)
            try:
                items = v if identity else [item(x) for x in v]
            except _Invalid:
                for index, x in enumerate(v):
                    try:
                        item(x)
                    except _Invalid as exc:
                        raise exc.at(index) from None
                raise
            return items if kind is list else kind(items)
        return dec_seq

    def _fixed_tuple(self, item_types: tuple[Any, ...]) -> Converter:
        items = [self.build(t) for t in item_types]
        size = len(items)

        def dec_tuple(v: Any) -> tuple[Any, ...]:
            if type(v) is not list:
                raise _expected("array", v)
            if len(v) != size:
                raise _Invalid(f"Expected `array` of length {size}")
            out = []
            for index, (decode, x) in enumerate(zip(items, v)):
                try:
                    out.append(decode(x))
                except _Invalid as exc:
                    raise exc.at(index) from None
            return tuple(out)
        return dec_tuple

    def _dict(self, key_type: Any, value_type: Any) -> Converter:
        key = self._dict_key(_strip_annotated(key_type))
        value = self.build(value_type)

        def dec_dict(v: Any) -> dict[Any, Any]:
            if type(v) is not dict:
                raise _expected("object", v)
            out = {}
            for k, x in v.items():
                try:
                    out[key(k)] = value(x)
                except _Invalid as exc:
                    raise exc.at(k) from None
            return out
        return dec_dict

    def _dict_key(self, key_type: Any) -> Converter:
        if key_type is str or key_type is Any:
            return lambda k: k
        if key_type is int:
            def dec_int_key(k: str) -> int:
                if _INT_RE.match(k):
                    return int(k)
                raise _Invalid("Expected `int`, got `str` - at `key`")
            return dec_int_key
        if (isinstance(key_type, type) and issubclass(key_type, enum.Enum)) or get_origin(key_type) is typing.Literal:
            inner = self.build(key_type)
            int_valued = all(isinstance(getattr(m, "value", m), int) for m in (
                list(typing.cast(Any, key_type)) if isinstance(key_type, type) else get_args(key_type)))
            if int_valued:
                return lambda k: inner(int(k)) if _INT_RE.match(k) else inner(k)
            return inner
        handler = _core.value_handler(key_type)
        if handler is not None:
            return self.build(key_type)
        raise TypeError(f"flpit.json (native backend): dict key type {key_type!r} is not supported")

    # -- dataclasses ---------------------------------------------------

    def _dataclass(self, cls: type) -> Converter:
        fields, properties = _class_layout(cls, self.jso)
        forbid = self.jso.unknown_field_handling == JsonUnknownFieldHandling.disallow
        known = {f.wire for f in fields} | {p.wire for p in properties}
        plan = [
            (f.name, f.wire, self.build(f.annotation),
             f.default is MISSING and f.default_factory is MISSING and not f.implicit_none,
             f.implicit_none, f.init)
            for f in fields
        ]
        property_plan = [(p.wire, self.build(p.annotation)) for p in properties]

        def dec_dataclass(v: Any) -> Any:
            if type(v) is not dict:
                raise _expected("object", v)
            if forbid:
                for k in v:
                    if k not in known:
                        raise _Invalid(f"Object contains unknown field `{k}`")
            kwargs: dict[str, Any] = {}
            late: list[tuple[str, Any]] = []
            for name, wire, decode, required, implicit_none, init in plan:
                if wire in v:
                    try:
                        value = decode(v[wire])
                    except _Invalid as exc:
                        raise exc.at(wire) from None
                elif required:
                    raise _Invalid(f"Object missing required field `{wire}`")
                elif implicit_none:
                    value = None
                else:
                    continue
                if init:
                    kwargs[name] = value
                else:
                    late.append((name, value))
            for wire, decode in property_plan:
                if wire in v:
                    try:
                        decode(v[wire])  # validated like any field, value is computed
                    except _Invalid as exc:
                        raise exc.at(wire) from None
            try:
                instance = cls(**kwargs)
            except TypeError as exc:
                raise _Invalid(str(exc)) from None
            for name, value in late:
                object.__setattr__(instance, name, value)
            return instance
        return dec_dataclass


# ---------------------------------------------------------------------
# Encoder construction
# ---------------------------------------------------------------------

def _encode_any(v: Any) -> Any:
    """Encode a value without static type information (fields typed Any)."""
    if v is None or v is True or v is False or type(v) is str or type(v) is int:
        return v
    if type(v) is float:
        return v if math.isfinite(v) else None
    if isinstance(v, enum.Enum):
        return _encode_any(v.value)
    if isinstance(v, str):
        return str.__str__(v)
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_encode_any(x) for x in v]
    if isinstance(v, dict):
        return {_encode_key_any(k): _encode_any(x) for k, x in v.items()}
    if isinstance(v, dt.datetime):
        return _format_datetime(v)
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return _format_time(v)
    if isinstance(v, dt.timedelta):
        return _format_timedelta(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    if isinstance(v, (decimal.Decimal, uuid.UUID)):
        return str(v)
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _encode_any(getattr(v, f.name)) for f in dataclasses.fields(v)}
    handler = _core.value_handler(type(v))
    if handler is not None:
        return handler.encode(v)
    if _core.collection_handler(type(v)) is not None:
        return [_encode_any(x) for x in typing.cast(Iterable[Any], v)]
    raise _Invalid(f"Encoding objects of type {type(v).__qualname__} is unsupported")


def _encode_key_any(k: Any) -> str:
    if isinstance(k, enum.Enum):
        k = k.value
    if isinstance(k, str):
        return str.__str__(k)
    if isinstance(k, (int, float)) and not isinstance(k, bool):
        return str(k)
    raise _Invalid(f"Only dicts with str-like or number-like keys are supported, got {type(k).__qualname__}")


class _EncoderBuilder:
    def __init__(self, jso: JsonSerializerOptions) -> None:
        self.jso = jso
        self.memo: dict[Any, Converter] = {}

    def build(self, tp: Any) -> Converter:
        try:
            return self.memo[tp]
        except KeyError:
            pass
        except TypeError:
            return self._make(tp)
        if dataclasses.is_dataclass(tp) and isinstance(tp, type):
            cell: list[Converter] = []
            self.memo[tp] = lambda v: cell[0](v)
            real = self._dataclass(tp)
            cell.append(real)
            self.memo[tp] = real
            return real
        converter = self._make(tp)
        self.memo[tp] = converter
        return converter

    def _make(self, tp: Any) -> Converter:
        tp = _strip_annotated(tp)
        if tp is Any or tp is object:
            return _encode_any
        if tp is None or tp is type(None):
            def enc_none(v: Any) -> None:
                if v is None:
                    return None
                raise _expected("null", v)
            return enc_none

        handler = _core.value_handler(tp)
        if handler is not None:
            encode = handler.encode

            def enc_registered(v: Any) -> Any:
                if not isinstance(v, tp):
                    raise _expected(tp.__name__, v)
                return encode(v)
            return enc_registered

        if tp is bool:
            def enc_bool(v: Any) -> bool:
                if v is True or v is False:
                    return v
                raise _expected("bool", v)
            return enc_bool
        if tp is int:
            def enc_int(v: Any) -> int:
                if type(v) is int:
                    return v
                if isinstance(v, int) and not isinstance(v, bool):
                    return int(v)
                raise _expected("int", v)
            return enc_int
        if tp is float:
            def enc_float(v: Any) -> float | None:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    v = float(v)
                    return v if math.isfinite(v) else None
                raise _expected("float", v)
            return enc_float
        if tp is str:
            def enc_str(v: Any) -> str:
                if type(v) is str:
                    return v
                if isinstance(v, str):
                    return str.__str__(v)
                raise _expected("str", v)
            return enc_str
        if tp in (bytes, bytearray):
            def enc_bytes(v: Any) -> str:
                if isinstance(v, (bytes, bytearray, memoryview)):
                    return base64.b64encode(bytes(v)).decode("ascii")
                raise _expected("bytes", v)
            return enc_bytes
        for temporal, fmt in (
                (dt.datetime, _format_datetime),
                (dt.date, dt.date.isoformat),
                (dt.time, _format_time),
                (dt.timedelta, _format_timedelta),
        ):
            if tp is temporal:
                def enc_temporal(v: Any, _tp: type = temporal, _fmt: Callable[[Any], str] = fmt) -> str:
                    if type(v) is _tp or (isinstance(v, _tp) and not (_tp is dt.date and isinstance(v, dt.datetime))):
                        return _fmt(v)
                    raise _expected(_tp.__name__, v)
                return enc_temporal
        if tp in (uuid.UUID, decimal.Decimal):
            def enc_str_like(v: Any) -> str:
                if isinstance(v, tp):
                    return str(v)
                raise _expected(tp.__name__, v)
            return enc_str_like
        if isinstance(tp, type) and issubclass(tp, enum.Enum):
            def enc_enum(v: Any) -> Any:
                if isinstance(v, tp):
                    return _encode_any(v.value)
                raise _Invalid(f"Expected `{tp.__name__}`, got `{type(v).__name__}`")
            return enc_enum

        origin, args = get_origin(tp), get_args(tp)
        if origin is typing.Literal:
            allowed = [(value, type(value)) for value in args]

            def enc_literal(v: Any) -> Any:
                for value, kind in allowed:
                    if type(v) is kind and v == value:
                        return v
                raise _Invalid(f"Invalid enum value {v!r}")
            return enc_literal
        if _is_union(origin):
            return self._union(args)

        collection = _core.collection_handler(origin or tp)
        if collection is not None:
            item = self.build(args[0] if args else Any)
            container = collection.tp

            def enc_collection(v: Any) -> list[Any]:
                if not isinstance(v, container):
                    raise _expected(container.__name__, v)
                return _encode_items(item, v)
            return enc_collection

        if origin in (list, set, frozenset) or tp in (list, set, frozenset):
            return self._sequence(args[0] if args else Any, (list, tuple, set, frozenset))
        if origin is tuple or tp is tuple:
            if not args or (len(args) == 2 and args[1] is Ellipsis):
                return self._sequence(args[0] if args else Any, (list, tuple))
            items = [self.build(t) for t in args]

            def enc_tuple(v: Any) -> list[Any]:
                if not isinstance(v, (list, tuple)) or len(v) != len(items):
                    raise _Invalid(f"Expected `array` of length {len(items)}")
                return [encode(x) for encode, x in zip(items, v)]
            return enc_tuple
        if origin is dict or tp is dict:
            value = self.build(args[1] if args else Any)

            def enc_dict(v: Any) -> dict[str, Any]:
                if not isinstance(v, dict):
                    raise _expected("object", v)
                out = {}
                for k, x in v.items():
                    try:
                        out[_encode_key_any(k)] = value(x)
                    except _Invalid as exc:
                        raise exc.at(str(k)) from None
                return out
            return enc_dict

        raise TypeError(f"flpit.json (native backend): type {tp!r} is not supported")

    def _sequence(self, item_type: Any, accepted: tuple[type, ...]) -> Converter:
        item = self.build(item_type)

        def enc_seq(v: Any) -> list[Any]:
            if not isinstance(v, accepted):
                raise _expected("array", v)
            return _encode_items(item, v)
        return enc_seq

    def _union(self, members: tuple[Any, ...]) -> Converter:
        non_none = [m for m in members if m is not type(None)]
        nullable = len(non_none) != len(members)
        encoders = [self.build(m) for m in non_none]

        def enc_union(v: Any) -> Any:
            if v is None:
                if nullable:
                    return None
                raise _Invalid("Expected a value, got `null`")
            for encode in encoders:
                try:
                    return encode(v)
                except _Invalid:
                    continue
            raise _Invalid(f"Value of type `{type(v).__name__}` does not match the declared union")
        return enc_union

    def _dataclass(self, cls: type) -> Converter:
        fields, properties = _class_layout(cls, self.jso)
        exclude = self.jso.default_handling == JsonDefaultHandling.exclude
        plan = []
        for f in fields:
            if not exclude:
                skip: Callable[[Any], bool] | None = None
            elif f.default is not MISSING:
                skip = (lambda v, d=f.default: v is d or (type(v) is type(d) and v == d))
            elif f.default_factory is not MISSING:
                # Like msgspec: only "empty container" factories are omitted, and
                # only while the value is still empty.
                skip = _empty_skip if _core.is_empty_collection_factory(f.default_factory) else None
            elif f.implicit_none:
                skip = (lambda v: v is None)
            else:
                skip = None
            plan.append((f.name, f.wire, self.build(f.annotation), skip))
        property_plan = [(p.name, p.wire, self.build(p.annotation)) for p in properties]

        def enc_dataclass(v: Any) -> dict[str, Any]:
            if v is None:
                raise _expected(cls.__name__, v)
            out: dict[str, Any] = {}
            for name, wire, encode, skip in plan:
                try:
                    value = getattr(v, name)
                except AttributeError:
                    raise _Invalid(f"Object missing required field `{wire}`") from None
                if skip is not None and skip(value):
                    continue
                try:
                    out[wire] = encode(value)
                except _Invalid as exc:
                    raise exc.at(wire) from None
            for name, wire, encode in property_plan:
                value = getattr(v, name)
                if exclude and value is None:
                    continue
                try:
                    out[wire] = encode(value)
                except _Invalid as exc:
                    raise exc.at(wire) from None
            return out
        return enc_dataclass


def _empty_skip(value: Any) -> bool:
    try:
        return len(value) == 0
    except TypeError:
        return False


def _encode_items(item: Converter, values: Iterable[Any]) -> list[Any]:
    if item is _encode_any:
        return [_encode_any(x) for x in values]
    try:
        return [item(x) for x in values]
    except _Invalid:
        for index, x in enumerate(values):
            try:
                item(x)
            except _Invalid as exc:
                raise exc.at(index) from None
        raise


# ---------------------------------------------------------------------
# Compilation cache
# ---------------------------------------------------------------------

_cache: dict[tuple[Any, ...], Converter] = {}
_cache_lock = threading.Lock()
_cache_version = -1


def _check_target(target: Any) -> None:
    if not any(True for _ in _nested_dataclasses(target)):
        raise TypeError(f"Only @dataclass are supported!, got {target!r}")


def _compiled(kind: str, target: Any, jso: JsonSerializerOptions) -> Converter:
    global _cache_version
    version = _core.registry_version()
    key = (kind, target, jso)
    if _cache_version == version:
        converter = _cache.get(key)
        if converter is not None:
            return converter
    _check_target(target)
    if kind == "enc":
        converter = _EncoderBuilder(jso).build(target)
    else:
        converter = _DecoderBuilder(jso).build(target)
    with _cache_lock:
        if _cache_version != version:
            _cache.clear()
            _cache_version = version
        _cache[key] = converter
    return converter


# ---------------------------------------------------------------------
# JSON text
# ---------------------------------------------------------------------

def _reject_constant(name: str) -> Any:
    raise ValueError(f"invalid JSON constant {name}")


def _loads(data: Any) -> Any:
    if isinstance(data, (bytes, bytearray, memoryview)):
        try:
            data = bytes(data).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JsonDeserializationError(f"JSON is malformed: invalid UTF-8 ({exc.reason})") from exc
    elif not isinstance(data, str):
        raise JsonDeserializationError(f"Expected str or bytes, got {type(data).__name__}")
    try:
        return json.loads(data, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise JsonDeserializationError(f"JSON is malformed: {exc.msg} (char {exc.pos})") from exc
    except ValueError as exc:
        raise JsonDeserializationError(f"JSON is malformed: {exc}") from exc


_dumps = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False, check_circular=False).encode


def _dump_bytes(value: Any) -> bytes:
    try:
        return _dumps(value).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise JsonSerializationError(f"String is not valid UTF-8: {exc.reason}") from exc


# ---------------------------------------------------------------------
# Public backend
# ---------------------------------------------------------------------

_DEFAULT_OPTIONS = JsonSerializerOptions()


class Backend:
    name = "native"

    @staticmethod
    def deserialize[T](data: bytes | str, target: type[T], jso: JsonSerializerOptions | None = None) -> T:
        if data is None:
            raise JsonDeserializationError("data must not be None")
        decode = _compiled("dec", target, jso or _DEFAULT_OPTIONS)
        parsed = _loads(data)
        try:
            return decode(parsed)
        except _Invalid as exc:
            raise JsonDeserializationError(str(exc)) from None

    @staticmethod
    def serialize_bytes[T](data: Any, target: type[T], jso: JsonSerializerOptions | None = None) -> bytes:
        encode = _compiled("enc", target, jso or _DEFAULT_OPTIONS)
        try:
            return _dump_bytes(encode(data))
        except _Invalid as exc:
            raise JsonSerializationError(str(exc)) from None

    @staticmethod
    def serialize[T](data: Any, target: type[T], jso: JsonSerializerOptions | None = None) -> str:
        if data is None:
            raise JsonSerializationError("data must not be None")
        return Backend.serialize_bytes(data, target, jso).decode("utf-8")

    @staticmethod
    def serialize_to[T](
            it: Iterable[T],
            target: type[T],
            output: typing.BinaryIO | typing.TextIO,
            jso: JsonSerializerOptions | None = None,
    ) -> None:
        if isinstance(output, io.TextIOBase):
            def write(data: bytes) -> None:
                output.write(data.decode("utf-8"))  # type: ignore[arg-type]
        elif isinstance(output, (io.BufferedIOBase, io.RawIOBase)):
            def write(data: bytes) -> None:
                output.write(data)  # type: ignore[arg-type]
        else:
            raise TypeError("output must be ByteWriter or TextWriter")

        encode = _compiled("enc", target, jso or _DEFAULT_OPTIONS)
        write(b"[")
        first = True
        for item in iter(it):
            if not first:
                write(b",")
            try:
                write(_dump_bytes(encode(item)))
            except _Invalid as exc:
                raise JsonSerializationError(str(exc)) from None
            first = False
        write(b"]")
