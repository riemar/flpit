---
description: Load typed CSV into dataclasses with FlpIt, eagerly into a FlpList or lazily as a FlpIt. Column names, delimiters and encodings are configurable.
---
# CSV

`flpit.csv` loads CSV rows into dataclasses. Columns map to fields by name, and cells are converted to the
field's type (numbers, booleans, dates, enums and anything in the JSON type registry).

```python
--8<-- "examples/csv/csv_load.py:csv"
```

- `CsvLoader.load_list` reads everything at once and returns a `FlpList`.
- `CsvLoader.load_it` returns a lazy `FlpIt`. With a file path, the file is opened when the query is enumerated
  and closed when it ends, and conversion errors surface during enumeration.
- `data` is either CSV text or a `pathlib.Path`.
- `CsvCol("Header")` names the column explicitly. `JProp` and `JIgnore` work the same way as in
  [JSON](json.md).
- `CsvOptions` sets the delimiter, quote and escape characters, encoding (UTF-8 with an optional byte order mark
  by default) and a naming policy.
- A cell that cannot be converted raises `CsvConversionError`, which is a `ValueError`.
