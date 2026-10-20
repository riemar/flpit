from __future__ import annotations

import csv
import io
from csv import DictReader
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, TextIO

import msgspec

from flpit import FlpIt, FlpList
from flpit.json import (
    JProp,
    JsonNamingPolicy,
    JsonSerializerOptions,
    wire_type_for,
)


class CsvCol(JProp):
    """Explicit CSV column name.

    Inherits JProp so the existing wire-schema machinery recognizes
    the metadata without a separate conversion implementation.
    """


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


@lru_cache(maxsize=None)
def _json_options_for_csv(
        naming_policy: JsonNamingPolicy,
) -> JsonSerializerOptions:
    """Reuse options identity because the wire-type cache keys by options ID."""
    return JsonSerializerOptions(naming_policy=naming_policy)


class CsvLoader:
    """Load typed records from CSV without adding format methods to FlpList/FlpIt."""

    @staticmethod
    def load_list[T](
            data: str | Path,
            item_type: type[T],
            options: CsvOptions | None = None,
    ) -> FlpList[T]:
        """Load CSV rows eagerly using bulk conversion.

        Args:
            data: CSV text, or a Path to a CSV file.
            item_type: Type of each resulting model.
            options: CSV dialect, encoding, and naming policy.

        Returns:
            An eagerly populated FlpList of item_type instances.
        """
        opts = options or CsvOptions()
        jso = _json_options_for_csv(opts.naming_policy)
        target: type[list[T]] = list[item_type]
        wire_type = wire_type_for(target, jso)

        with CsvLoader._open_text(data, opts) as stream:
            reader: DictReader[Any] = CsvLoader._reader(stream, opts)
            rows = CsvLoader._read_rows(reader)

        output = msgspec.convert(
            rows,
            wire_type,
            from_attributes=True,
            strict=False,
        )
        del rows

        return FlpList[T](output)

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
        jso = _json_options_for_csv(opts.naming_policy)
        wire_item_type = wire_type_for(item_type, jso)

        return FlpIt[T](
            CsvLoader._iter_items(data, item_type, wire_item_type, opts)
        )

    @staticmethod
    def _open_text(data: str | Path, options: CsvOptions) -> TextIO:
        if isinstance(data, Path):
            return data.open("r", newline="", encoding=options.encoding)
        return io.StringIO(data.removeprefix("\ufeff"), newline="")

    @staticmethod
    def _reader(stream: TextIO, options: CsvOptions) -> csv.DictReader[Any]:
        reader = csv.DictReader(
            stream,
            delimiter=options.delimiter,
            quotechar=options.quotechar,
            escapechar=options.escapechar,
            doublequote=options.doublequote,
            skipinitialspace=options.skipinitialspace,
            strict=options.strict,
        )

        headers = reader.fieldnames
        if headers is None:
            raise ValueError("CSV input must contain a header row")

        if any(header == "" for header in headers):
            raise ValueError("CSV column names must not be empty")

        if len(headers) != len(set(headers)):
            raise ValueError("CSV column names must be unique")

        return reader

    @staticmethod
    def _read_rows(reader: csv.DictReader[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        for row in reader:
            if None in row:
                raise ValueError(
                    f"CSV row ending at line {reader.line_num} "
                    "contains more values than the header"
                )
            rows.append(row)

        return rows

    @staticmethod
    def _iter_items[T](
            data: str | Path,
            item_type: type[T],
            wire_item_type: Any,
            options: CsvOptions,
    ) -> Iterator[T]:
        with CsvLoader._open_text(data, options) as stream:
            reader = CsvLoader._reader(stream, options)

            for row in reader:
                if None in row:
                    raise ValueError(
                        f"CSV row ending at line {reader.line_num} "
                        "contains more values than the header"
                    )

                yield msgspec.convert(
                    row,
                    wire_item_type,
                    from_attributes=True,
                    strict=False,
                )

# import csv
# import io
# from dataclasses import dataclass
# from pathlib import Path
# from typing import TextIO
#
# import msgspec
#
# from flpit.core.linq import FlpList
# from flpit.json import (
#     JProp,
#     JsonNamingPolicy,
#     JsonSerializerOptions,
#     wire_type_for,
# )
#
#
# class CsvCol(JProp):
#     """Explicit CSV column name using the existing property metadata."""
#
#
# @dataclass(frozen=True, slots=True)
# class CsvOptions:
#     """CSV parsing and field-mapping options.
#
#     The naming policy defaults to none, so CSV headers match Python field
#     names unless an explicit CsvCol/JProp name is supplied.
#     """
#
#     delimiter: str = ","
#     quotechar: str = '"'
#     escapechar: str | None = None
#     doublequote: bool = True
#     skipinitialspace: bool = False
#     strict: bool = False
#     encoding: str = "utf-8-sig"
#     naming_policy: JsonNamingPolicy = JsonNamingPolicy.none
#
#     def __post_init__(self) -> None:
#         if len(self.delimiter) != 1:
#             raise ValueError("delimiter must be exactly one character")
#         if len(self.quotechar) != 1:
#             raise ValueError("quotechar must be exactly one character")
#         if self.escapechar is not None and len(self.escapechar) != 1:
#             raise ValueError("escapechar must be exactly one character")
#
#     def to_json_options(self) -> JsonSerializerOptions:
#         """Map CSV field naming to the shared wire-schema builder."""
#         return JsonSerializerOptions(naming_policy=self.naming_policy)
#
#
# class CsvLoader:
#     @staticmethod
#     def load[T](
#             data: str | Path,
#             item_type: type[T],
#             options: CsvOptions | None = None,
#     ) -> FlpList[T]:
#         """Load CSV content or a CSV file into a FlpList.
#
#         CSV headers are matched using the configured naming policy and
#         explicit property metadata. The naming policy is passed to the
#         existing JSON wire-schema builder so annotation handling stays
#         consistent with JsonConvert.
#
#         CSV values are converted in lax mode because CSV supplies text
#         values, including numeric values represented as strings.
#
#         Args:
#             data: CSV content as a string, or a Path to a CSV file.
#             item_type: Model type to construct for each row.
#             options: CSV dialect, encoding and naming options.
#
#         Returns:
#             A FlpList containing instances of item_type.
#         """
#         csv_options = options or CsvOptions()
#         json_options = csv_options.to_json_options()
#         wire_type = wire_type_for(item_type, json_options)
#
#         if isinstance(data, Path):
#             with data.open(
#                     "r",
#                     newline="",
#                     encoding=csv_options.encoding,
#             ) as stream:
#                 return CsvLoader._load_stream(
#                     stream, item_type, wire_type, csv_options
#                 )
#
#         with io.StringIO(data, newline="") as stream:
#             return CsvLoader._load_stream(
#                 stream, item_type, wire_type, csv_options
#             )
#
#     @staticmethod
#     def _load_stream[T](
#             stream: TextIO,
#             item_type: type[T],
#             wire_type: type,
#             options: CsvOptions,
#     ) -> FlpList[T]:
#         reader = csv.DictReader(
#             stream,
#             delimiter=options.delimiter,
#             quotechar=options.quotechar,
#             escapechar=options.escapechar,
#             doublequote=options.doublequote,
#             skipinitialspace=options.skipinitialspace,
#             strict=options.strict,
#         )
#
#         if reader.fieldnames is None:
#             raise ValueError("CSV input must contain a header row")
#
#         if len(reader.fieldnames) != len(set(reader.fieldnames)):
#             raise ValueError("CSV column names must be unique")
#
#         def convert_rows():
#             for row in reader:
#                 if None in row:
#                     raise ValueError(
#                         f"CSV row ending at line {reader.line_num} "
#                         "contains more values than the header"
#                     )
#
#                 wire_obj = msgspec.convert(
#                     row,
#                     wire_type,
#                     from_attributes=True,
#                     strict=False,
#                 )
#
#                 # Reconstruct the declared model rather than leaking the
#                 # dynamically generated wire type to the caller.
#                 yield msgspec.convert(
#                     wire_obj,
#                     item_type,
#                     from_attributes=True,
#                     strict=False,
#                 )
#
#         return FlpList[T](convert_rows())
#
