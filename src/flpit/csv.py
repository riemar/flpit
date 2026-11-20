"""Typed CSV loading into dataclasses.

Columns map to dataclass fields by name: ``CsvCol`` gives an explicit column name,
otherwise ``JProp`` (shared with JSON) or the configured naming policy applies;
``JIgnore`` fields are never read. Cell text is converted leniently: numbers,
booleans (``true``/``false``/``1``/``0``), ``null`` for optional fields, ISO dates
and times, enums, literals and any type in the flpit.json type registry.

Each (model, header) pair is compiled once into a small generated converter that
reads a ``csv.reader`` row (a list of strings) straight into the dataclass. It has
no dependency on msgspec.
"""
from __future__ import annotations

import base64
import binascii
import csv
import dataclasses
import datetime as dt
import decimal
import enum
import io
import math
import re
import threading
import types
import typing
import uuid
from collections.abc import Callable, Iterator
from dataclasses import MISSING, dataclass
from pathlib import Path
from typing import Annotated, Any, TextIO, get_args, get_origin, get_type_hints

from flpit import FlpIt, FlpList
from flpit.json import _core
from flpit.json._core import (
    ConversionError,
    JInclude,
    JProp,
    JsonNamingPolicy,
    _apply_naming_policy,
)

__all__ = ["CsvCol", "CsvConversionError", "CsvLoader", "CsvOptions"]

CsvConversionError = ConversionError
"""Raised when a CSV value cannot be converted to the field type (a ValueError)."""


class CsvCol:
    """Explicit CSV column name: ``Annotated[str, CsvCol("Display Label")]`` or ``CsvCol[str].Label``.

    Only CSV reads it; JSON names are set with ``JProp``.
    """

    __slots__ = ("column",)

    def __init__(self, column: str) -> None:
        self.column = column

    def __repr__(self) -> str:
        return f"CsvCol({self.column!r})"

    @property
    def json_name(self) -> str:
        """Backwards compatible spelling of ``column``."""
        return self.column

    def __class_getitem__[T](cls, item: type[T]) -> Any:
        class CsvColTypeProxy:
            def __getattr__(self, name: str) -> Annotated[type[T], CsvCol]:
                return typing.cast(Annotated[type[T], CsvCol], Annotated[item, CsvCol(name)])

        return CsvColTypeProxy()


@dataclass(frozen=True, slots=True)
class CsvOptions:
    """CSV parsing and property-mapping options.

    Naming defaults to none: headers match declared property names unless
    CsvCol specifies an explicit column name.
    """

    delimiter: str = ","
    quotechar: str = '"'
    escapechar: str | None = None
    doublequote: bool = True
    skipinitialspace: bool = False
    strict: bool = False
    encoding: str = "utf-8-sig"
    naming_policy: JsonNamingPolicy = JsonNamingPolicy.none

    def __post_init__(self) -> None:
        if len(self.delimiter) != 1:
            raise ValueError("delimiter must be exactly one character")
        if len(self.quotechar) != 1:
            raise ValueError("quotechar must be exactly one character")
        if self.escapechar is not None and len(self.escapechar) != 1:
            raise ValueError("escapechar must be exactly one character")


# =============================================================================
# Cell conversion (lenient string rules)
# =============================================================================

class _Bad(Exception):
    """A cell that does not convert; turned into CsvConversionError with its position."""


def _expected(kind: str, value: Any) -> _Bad:
    shown = "an empty cell (no value)" if value is None else f"{value!r}"
    return _Bad(f"Expected `{kind}`, got {shown}")


# JSON number grammar: no leading '+', no leading zeros, no bare '.', no '_' or spaces.
_INT_TEXT = re.compile(r"-?(?:0|[1-9]\d*)\Z")
_NUMBER_TEXT = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")
_SPECIAL_FLOATS = {"nan", "-nan", "inf", "-inf", "infinity", "-infinity"}
_MAX_EXACT = 2 ** 53


def _to_int(value: Any) -> int:
    """Integer text, or number text with an integral value (``"1e3"``, ``"2.0"``) up to 2**53."""
    if type(value) is str:
        if _INT_TEXT.match(value):
            return int(value)
        if _NUMBER_TEXT.match(value):
            number = float(value)
            if number.is_integer() and abs(number) <= _MAX_EXACT:
                return int(number)
    raise _expected("int", value)


def _to_float(value: Any) -> float:
    if type(value) is str:
        if _NUMBER_TEXT.match(value):
            number = float(value)
            if not math.isinf(number):
                return number
        elif value.lower() in _SPECIAL_FLOATS:
            return float(value)
    raise _expected("float", value)


_BOOL_TEXT = {"true": True, "false": False, "1": True, "0": False, "-0": False}


def _to_bool(value: Any) -> bool:
    if type(value) is str:
        result = _BOOL_TEXT.get(value.lower())
        if result is not None:
            return result
    raise _expected("bool", value)


def _to_exact_int(value: Any) -> int:
    """Integer text only (no "1.0" / "1e3"): for `int | float` unions and int literals."""
    if type(value) is str and _INT_TEXT.match(value):
        return int(value)
    raise _expected("int", value)


_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _seconds(value: str) -> dt.timedelta:
    """Number text as seconds, rounded to microseconds (lenient datetime / timedelta input)."""
    micros = (decimal.Decimal(value) * 1_000_000).to_integral_value(rounding=decimal.ROUND_HALF_EVEN)
    return dt.timedelta(microseconds=int(micros))


def _number_or(parse: Callable[[str], Any], from_seconds: Callable[[dt.timedelta], Any]) -> Callable[[str], Any]:
    """Accept ISO text, or a number of seconds (Unix time for datetimes), like msgspec's lax mode."""
    def convert(value: str) -> Any:
        if _NUMBER_TEXT.match(value):
            return from_seconds(_seconds(value))
        return parse(value)
    return convert


def _is_null(value: Any) -> bool:
    return value is None or (type(value) is str and len(value) == 4 and value.lower() == "null")


def _to_none(value: Any) -> None:
    if _is_null(value):
        return None
    raise _expected("null", value)


def _to_str(value: Any) -> str:
    if type(value) is str:
        return value
    raise _expected("str", value)


def _to_optional_str(value: Any) -> str | None:
    if value is None or type(value) is str:
        return value
    raise _expected("str | None", value)


def _string_parser(parse: Callable[[str], Any], kind: str) -> Callable[[Any], Any]:
    def convert(value: Any) -> Any:
        if type(value) is str:
            try:
                return parse(value)
            except (ValueError, TypeError, ArithmeticError):
                pass
        raise _expected(kind, value)
    return convert


def _parse_bytes(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as exc:
        raise ValueError(str(exc)) from None


def _temporal_parsers() -> dict[type, Callable[[str], Any]]:
    from flpit.json import _native  # stdlib-only RFC 3339 / ISO 8601 parsers shared with JSON

    return {
        dt.datetime: _number_or(_native._parse_datetime, lambda seconds: _EPOCH + seconds),
        dt.date: _native._parse_date,
        dt.time: _native._parse_time,
        dt.timedelta: _number_or(_native._parse_timedelta, lambda seconds: seconds),
    }


def _tag(convert: Callable[[Any], Any], target: type) -> Callable[[Any], Any]:
    convert.__flpit_target__ = target  # type: ignore[attr-defined]
    return convert


def _strip_annotated(tp: Any) -> Any:
    while get_origin(tp) is typing.Annotated:
        tp = get_args(tp)[0]
    return tp


def _cell_converter(tp: Any) -> Callable[[Any], Any]:
    """Converter for one cell of declared type ``tp`` (raises _Bad)."""
    tp = _strip_annotated(tp)
    if tp is Any or tp is object or tp is str:
        return _to_str if tp is str else (lambda v: v)
    if tp is int:
        return _to_int
    if tp is float:
        return _to_float
    if tp is bool:
        return _to_bool
    if tp is None or tp is type(None):
        return _to_none

    handler = _core.value_handler(tp)
    if handler is not None:
        return _string_parser(handler.decode, getattr(tp, "__name__", str(tp)))

    temporal = _temporal_parsers().get(tp)
    if temporal is not None:
        return _tag(_string_parser(temporal, tp.__name__), tp)
    if tp is decimal.Decimal:
        return _tag(_string_parser(decimal.Decimal, "decimal"), decimal.Decimal)
    if tp is uuid.UUID:
        return _string_parser(uuid.UUID, "uuid")
    if tp is bytes:
        return _string_parser(_parse_bytes, "bytes")
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return _enum_converter(tp)

    origin, args = get_origin(tp), get_args(tp)
    if origin is typing.Literal:
        return _literal_converter(args)
    if origin is typing.Union or origin is types.UnionType:
        return _union_converter(args)

    raise TypeError(f"flpit.csv: a CSV column cannot hold values of type {tp!r}")


def _enum_converter(tp: type[enum.Enum]) -> Callable[[Any], Any]:
    by_text: dict[str, Any] = {}
    for member in tp:
        by_text.setdefault(str(member.value), member)

    def convert(value: Any) -> Any:
        if type(value) is str:
            member = by_text.get(value)
            if member is not None:
                return member
        raise _expected(tp.__name__, value)
    return convert


def _literal_converter(values: tuple[Any, ...]) -> Callable[[Any], Any]:
    converters = [(literal, _to_exact_int if type(literal) is int else _cell_converter(type(literal)))
                  for literal in values]

    def convert(value: Any) -> Any:
        for literal, to_type in converters:
            try:
                if to_type(value) == literal:
                    return literal
            except _Bad:
                continue
        raise _expected(" | ".join(repr(v) for v in values), value)
    return convert


def _union_converter(members: tuple[Any, ...]) -> Callable[[Any], Any]:
    plain = [_strip_annotated(m) for m in members]
    nullable = type(None) in plain
    others = [m for m in plain if m is not type(None)]
    if str in others:
        # Text matches `str` directly (as in msgspec): "null" stays "null" for `str | None`.
        return _to_optional_str if nullable else _to_str
    ordered = sorted(others, key=lambda m: {int: 0, float: 1, bool: 2}.get(m, 3))
    # with both int and float, integer text is an int and any other number a float
    converters = [_to_exact_int if m is int and float in others else _cell_converter(m) for m in ordered]
    names = " | ".join(getattr(m, "__name__", str(m)) for m in plain)

    def convert(value: Any) -> Any:
        if nullable and _is_null(value):
            return None
        for to_type in converters:
            try:
                return to_type(value)
            except _Bad:
                continue
        raise _expected(names, value)
    return convert


# =============================================================================
# Row converters (generated per model and header)
# =============================================================================

@dataclass(slots=True)
class _Column:
    field: str
    column: str
    convert: Callable[[Any], Any]
    index: int | None          # position in the header, None when missing
    required: bool
    implicit_none: bool        # optional field without default -> None when missing


def _field_columns(item_type: type, naming_policy: JsonNamingPolicy) -> list[tuple[str, str, Any, bool, bool, bool]]:
    if not (isinstance(item_type, type) and dataclasses.is_dataclass(item_type)):
        raise TypeError(f"Only @dataclass are supported!, got {item_type!r}")
    hints = get_type_hints(item_type, include_extras=True)
    out = []
    for field in dataclasses.fields(item_type):
        annotation = hints[field.name]
        meta: tuple[Any, ...] = ()
        base = annotation
        if get_origin(annotation) is typing.Annotated:
            base, *rest = get_args(annotation)
            meta = tuple(rest)
        if any(m is _core.JIgnore for m in meta):
            continue
        csv_name = next((m.column for m in meta if isinstance(m, CsvCol)), None)
        json_name = next((m.json_name for m in meta if isinstance(m, JProp)), None)
        explicit = csv_name if csv_name is not None else json_name
        included = any(m is JInclude for m in meta)
        if field.name.startswith("_") and explicit is None and not included:
            continue
        column = explicit if explicit is not None else _apply_naming_policy(field.name, naming_policy)
        has_default = field.default is not MISSING or field.default_factory is not MISSING
        implicit_none = not has_default and _core._allows_none(base)
        out.append((field.name, column, base, field.init, not has_default and not implicit_none, implicit_none))
    return out


class _RowConverter:
    """Converts the ``csv.reader`` rows of one header into instances of one dataclass."""

    def __init__(self, item_type: type, header: tuple[str, ...], naming_policy: JsonNamingPolicy) -> None:
        self.item_type = item_type
        self.header = header
        self.width = len(header)
        position = {name: i for i, name in enumerate(header)}
        init_fields = {f.name for f in dataclasses.fields(item_type) if f.init}
        self.columns: list[_Column] = []
        seen: dict[str, str] = {}
        for name, column, base, _init, required, implicit_none in _field_columns(item_type, naming_policy):
            if column in seen:
                raise ValueError(
                    f"{item_type.__qualname__}: '{name}' and '{seen[column]}' both map to CSV column '{column}'")
            seen[column] = name
            index = position.get(column)
            # only columns present in this header need a converter (a list field may simply be absent)
            convert = _cell_converter(base) if index is not None else _to_str
            self.columns.append(_Column(name, column, convert, index, required, implicit_none))
        self.late = [c for c in self.columns if c.field not in init_fields]   # init=False fields
        self.rows = self._generate()

    # -- generated fast path ---------------------------------------------------

    def _generate(self) -> Callable[[Any], Iterator[Any]]:
        """Generate the row loop for this header. For ``Row(name: str, count: int)``::

            def rows(reader):
                for row in reader:
                    if len(row) == 2:
                        try:
                            yield _cls(row[0], (int(_v) if (_v := row[1]).isdigit() ... else _to_int(_v)))
                            continue
                        except _Retry:
                            pass
                    elif not row:
                        continue
                    elif len(row) > 2:
                        raise ValueError("... more values than the header")
                    yield _slow(row, reader.line_num)

        Plain cells convert inline and the dataclass is built with positional arguments;
        anything unusual (and every error) goes through ``slow``, which converts cell by
        cell and reports the failing line and column.
        """
        env: dict[str, Any] = {
            "_cls": self.item_type, "_slow": self.slow, "_to_int": _to_int, "_to_float": _to_float,
            "_to_bool": _to_bool, "_bools": {"true": True, "false": False, "1": True, "0": False},
            "_Retry": (_Bad, ValueError, TypeError, KeyError, ArithmeticError),
            "_date": dt.date.fromisoformat, "_datetime": dt.datetime.fromisoformat, "_Decimal": decimal.Decimal,
        }
        call = self._constructor_call(env)
        width = self.width
        lines = ["def rows(reader):", "    for row in reader:"]
        if call is not None:
            lines += [
                f"        if len(row) == {width}:",
                "            try:",
                f"                yield {call}",
                "                continue",
                "            except _Retry:",
                "                pass",
                "        elif not row:",
                "            continue",
            ]
        else:
            lines += ["        if not row:", "            continue"]
        lines += [
            f"        if len(row) > {width}:",
            "            raise ValueError(",
            "                f'CSV row ending at line {reader.line_num} contains more values than the header')",
            "        yield _slow(row, reader.line_num)",
        ]
        source = "\n".join(lines) + "\n"
        exec(compile(source, f"<flpit.csv rows of {self.item_type.__qualname__}>", "exec"), env)
        return typing.cast(Callable[[Any], Iterator[Any]], env["rows"])

    def _constructor_call(self, env: dict[str, Any]) -> str | None:
        """``_cls(<positional>, <kw_only>=...)`` or None when only the slow path can build it."""
        if self.late:
            return None
        by_field = {c.field: c for c in self.columns}
        positional: list[str] = []
        keywords: list[str] = []
        for i, field in enumerate(f for f in dataclasses.fields(self.item_type) if f.init):
            column = by_field.get(field.name)
            expression: str | None = None
            if column is not None and column.index is not None:
                expression = self._cell_expression(column, i, env)
            elif column is not None and column.required:
                return None                          # error: let the slow path report it
            elif column is not None and column.implicit_none:
                expression = "None"
            if expression is None:                   # not in the CSV (or JIgnore): dataclass default
                if field.default is not MISSING:
                    env[f"_d{i}"] = field.default
                    expression = f"_d{i}"
                elif field.default_factory is not MISSING:
                    env[f"_f{i}"] = field.default_factory
                    expression = f"_f{i}()"
                else:
                    return None
            if field.kw_only:
                keywords.append(f"{field.name}={expression}")
            else:
                positional.append(expression)
        return f"_cls({', '.join(positional + keywords)})"

    @staticmethod
    def _cell_expression(column: _Column, i: int, env: dict[str, Any]) -> str:
        cell = f"row[{column.index}]"
        if column.convert is _to_str or column.convert is _to_optional_str:
            return cell  # a full-width row only holds strings
        target = getattr(column.convert, "__flpit_target__", None)
        if target is dt.date:
            # YYYY-MM-DD only; other shapes go through the RFC 3339 parser
            return (f"(_date(_v) if len(_v := {cell}) == 10 and _v[4] == '-' and _v[7] == '-' "
                    f"and _v.isascii() else _c{i}(_v))") if env.setdefault(f"_c{i}", column.convert) else ""
        if target is dt.datetime:
            # YYYY-MM-DDTHH:MM:SS with optional Z / +HH:MM, no fraction; the rest via the RFC 3339 parser
            return (f"(_datetime(_v) if (len(_v := {cell}) == 19 or (len(_v) == 20 and _v[19] in 'Zz') "
                    f"or (len(_v) == 25 and _v[19] in '+-' and _v[22] == ':')) and _v[4] == '-' and _v[7] == '-' "
                    f"and _v[10] in 'Tt ' and _v[13] == ':' and _v[16] == ':' and _v.isascii() "
                    f"else _c{i}(_v))") if env.setdefault(f"_c{i}", column.convert) else ""
        if target is decimal.Decimal:
            return f"_Decimal({cell})"
        if column.convert is _to_int:
            # plain non-negative integers inline, everything else through the full rules
            return (f"(int(_v) if (_v := {cell}).isdigit() and _v.isascii() "
                    f"and (_v[0] != '0' or len(_v) == 1) else _to_int(_v))")
        if column.convert is _to_float:
            # plain non-negative decimals inline: exactly the JSON number grammar for them
            return (f"(float(_v) if (_v := {cell}).isascii() and _v.replace('.', '', 1).isdigit() "
                    f"and _v[0] != '.' and _v[-1] != '.' and (_v[0] != '0' or len(_v) == 1 or _v[1] == '.') "
                    f"else _to_float(_v))")
        if column.convert is _to_bool:
            return f"(_bools[_v] if (_v := {cell}) in _bools else _to_bool(_v))"
        env[f"_c{i}"] = column.convert
        return f"_c{i}({cell})"

    # -- slow path -----------------------------------------------------------------

    def slow(self, row: list[Any], line: int) -> Any:
        """Cell by cell, with exact error positions; short rows get None for missing cells."""
        if len(row) < self.width:
            row = row + [None] * (self.width - len(row))
        kwargs: dict[str, Any] = {}
        late: list[tuple[str, Any]] = []
        for spec in self.columns:
            if spec.index is None:
                if spec.required:
                    raise CsvConversionError(f"CSV has no column '{spec.column}' for required field '{spec.field}'")
                if not spec.implicit_none:
                    continue
                value: Any = None
            else:
                try:
                    value = spec.convert(row[spec.index])
                except _Bad as exc:
                    raise CsvConversionError(f"{exc} - at line {line}, column '{spec.column}'") from None
            if spec in self.late:
                late.append((spec.field, value))
            else:
                kwargs[spec.field] = value
        try:
            instance = self.item_type(**kwargs)
        except (TypeError, ValueError) as exc:
            raise CsvConversionError(f"{exc} - at line {line}") from exc
        for name, value in late:
            object.__setattr__(instance, name, value)
        return instance


_converters: dict[tuple[Any, ...], _RowConverter] = {}
_converters_lock = threading.Lock()


def _row_converter(item_type: type, header: tuple[str, ...], naming_policy: JsonNamingPolicy) -> _RowConverter:
    key = (item_type, header, naming_policy, _core.registry_version())
    converter = _converters.get(key)
    if converter is None:
        converter = _RowConverter(item_type, header, naming_policy)
        with _converters_lock:
            if len(_converters) > 1024:
                _converters.clear()
            _converters[key] = converter
    return converter


# =============================================================================
# Loader
# =============================================================================

class CsvLoader:
    """Load typed records from CSV without adding format methods to FlpList/FlpIt."""

    @staticmethod
    def load_list[T](
            data: str | Path,
            item_type: type[T],
            options: CsvOptions | None = None,
    ) -> FlpList[T]:
        """Load CSV rows eagerly.

        Args:
            data: CSV text, or a Path to a CSV file.
            item_type: Type of each resulting model.
            options: CSV dialect, encoding, and naming policy.

        Returns:
            An eagerly populated FlpList of item_type instances.
        """
        opts = options or CsvOptions()
        with CsvLoader._open_text(data, opts) as stream:
            return FlpList[T](list(CsvLoader._convert_rows(stream, item_type, opts)))

    @staticmethod
    def load_it[T](
            data: str | Path,
            item_type: type[T],
            options: CsvOptions | None = None,
    ) -> FlpIt[T]:
        """Load CSV rows lazily, converting one row when it is consumed.

        For Path input, the file is opened on iteration and closed when
        the iterator is exhausted or closed. CSV parsing and conversion
        errors therefore occur during iteration, not at this call.
        """
        opts = options or CsvOptions()
        _field_columns(item_type, opts.naming_policy)  # validate the model up front
        return FlpIt[T](CsvLoader._iter_items(data, item_type, opts))

    @staticmethod
    def _open_text(data: str | Path, options: CsvOptions) -> TextIO:
        if isinstance(data, Path):
            return data.open("r", newline="", encoding=options.encoding)
        return io.StringIO(data.removeprefix("﻿"), newline="")

    @staticmethod
    def _reader(stream: TextIO, options: CsvOptions) -> tuple[Any, tuple[str, ...]]:
        reader = csv.reader(
            stream,
            delimiter=options.delimiter,
            quotechar=options.quotechar,
            escapechar=options.escapechar,
            doublequote=options.doublequote,
            skipinitialspace=options.skipinitialspace,
            strict=options.strict,
        )
        header = next(reader, None)
        if header is None:
            raise ValueError("CSV input must contain a header row")
        if any(name == "" for name in header):
            raise ValueError("CSV column names must not be empty")
        if len(header) != len(set(header)):
            raise ValueError("CSV column names must be unique")
        return reader, tuple(header)

    @staticmethod
    def _convert_rows[T](stream: TextIO, item_type: type[T], options: CsvOptions) -> Iterator[T]:
        reader, header = CsvLoader._reader(stream, options)
        return _row_converter(item_type, header, options.naming_policy).rows(reader)

    @staticmethod
    def _iter_items[T](data: str | Path, item_type: type[T], options: CsvOptions) -> Iterator[T]:
        with CsvLoader._open_text(data, options) as stream:
            yield from CsvLoader._convert_rows(stream, item_type, options)
