"""CSV load benchmark (moved out of tests/test_csv.py; the old class-level
benchmark mark never applied to the test function)."""
import csv
import io
from dataclasses import dataclass
from time import perf_counter

from flpit.csv import CsvLoader


@dataclass
class CsvTestRow:
    name: str
    count: int

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
