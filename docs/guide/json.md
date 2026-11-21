# JSON

`flpit.json` turns typed objects into JSON and back. Dataclasses and nested models work out of the box.

```python
--8<-- "examples/json/json_convert.py:json"
```

- Property names are camel case by default: `first_name` becomes `firstName`.
- `JProp("id")` sets an explicit JSON name, and `JIgnore` leaves a field out.
- `FlpList.from_json(text, Person)` reads a JSON array straight into a `FlpList[Person]`.

FlpIt uses [`msgspec`](https://github.com/jcrist/msgspec) when it is installed and a pure-Python backend
everywhere else. Naming policies, custom types and backends are covered in the
[README](https://github.com/riemar/flpit#json-serialization).
