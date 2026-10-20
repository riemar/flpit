from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import msgspec
import pytest

from flpit.csv import CsvCol, CsvLoader, CsvOptions
from flpit.json import JsonNamingPolicy


@dataclass
class CsvTestModel:
    name: str
    count: int


@dataclass
class CsvAliasModel:
    display_name: Annotated[str, CsvCol("Display Label")]


@dataclass
class CsvCamelModel:
    first_name: str
    item_count: int


class TestCsvLoader:
    def test_load_list_from_string(self) -> None:
        raw = "name,count\nAda,3\nGrace,7\n"

        result = CsvLoader.load_list(raw, CsvTestModel)

        assert list(result) == [
            CsvTestModel("Ada", 3),
            CsvTestModel("Grace", 7),
        ]

    def test_load_list_from_path_with_bom_and_custom_delimiter(
            self,
            tmp_path: Path,
    ) -> None:
        path = tmp_path / "people.csv"
        path.write_text(
            "\ufeffname;count\nAda;3\n",
            encoding="utf-8",
        )

        result = CsvLoader.load_list(
            path,
            CsvTestModel,
            CsvOptions(delimiter=";"),
        )

        assert list(result) == [CsvTestModel("Ada", 3)]

    def test_csv_column_alias(self) -> None:
        result = CsvLoader.load_list(
            "Display Label\nCountess of Lovelace\n",
            CsvAliasModel,
        )

        assert list(result) == [
            CsvAliasModel("Countess of Lovelace")
        ]

    def test_naming_policy_is_applied(self) -> None:
        result = CsvLoader.load_list(
            "firstName,itemCount\nAda,3\n",
            CsvCamelModel,
            CsvOptions(naming_policy=JsonNamingPolicy.camel),
        )

        assert list(result) == [CsvCamelModel("Ada", 3)]

    def test_load_it_converts_incrementally(self) -> None:
        raw = "name,count\nAda,3\nGrace,not-an-int\n"

        result = CsvLoader.load_it(raw, CsvTestModel)
        iterator = iter(result)

        # Construction and consumption of the first row succeed.
        assert next(iterator) == CsvTestModel("Ada", 3)

        # The invalid second row fails only when requested.
        with pytest.raises(msgspec.ValidationError):
            next(iterator)

    def test_empty_input_requires_header(self) -> None:
        with pytest.raises(ValueError, match="header row"):
            CsvLoader.load_list("", CsvTestModel)

    def test_duplicate_headers_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be unique"):
            CsvLoader.load_list(
                "name,name\nAda,Lovelace\n",
                CsvTestModel,
            )

    def test_extra_values_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="more values than the header"):
            CsvLoader.load_list(
                "name,count\nAda,3,unexpected\n",
                CsvTestModel,
            )

    def test_quoted_commas_are_parsed(self) -> None:
        result = CsvLoader.load_list(
            'name,count\n"Ada, Lovelace",3\n',
            CsvTestModel,
        )

        assert list(result) == [
            CsvTestModel("Ada, Lovelace", 3)
        ]


@pytest.mark.benchmark
@dataclass
class CsvTestRow:
    name: str
    count: int

import io
import csv
from time import perf_counter

def test_loads_one_million_csv_rows_from_memory(tlog) -> None:
    row_count = 1_000_000

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["name", "count"])
    writer.writerows((f"item-{i}", i) for i in range(row_count))

    raw = buffer.getvalue()
    buffer.close()

    start = perf_counter()

    result = (CsvLoader
              .load_it(raw, CsvTestRow)
              .where(lambda x: x.count != 100000)
              .select(lambda x: x.name)
              .to_list()
    )

    tlog.info(f"CSV load: {perf_counter() - start:.3f}s")

    start = perf_counter()

    result = CsvLoader.load_list(raw, CsvTestRow)

    tlog.info(f"CSV load: {perf_counter() - start:.3f}s")

    assert len(result) == row_count
    assert result[0] == CsvTestRow(name="item-0", count=0)
    assert result[-1] == CsvTestRow(
        name=f"item-{row_count - 1}",
        count=row_count - 1,
    )