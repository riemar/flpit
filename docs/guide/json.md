---
description: Typed JSON serialization and deserialization for dataclasses with FlpIt. Naming policies, ignored fields, custom types, and the msgspec and native backends.
---
# JSON

`flpit.json` turns typed objects into JSON and back. Dataclasses and nested models work out of the box.

```python
--8<-- "examples/json/json_convert.py:json"
```

- Property names are camel case by default: `first_name` becomes `firstName`.
- `JProp("id")` sets an explicit JSON name, `JIgnore` leaves a field out, and `JInclude` explicitly includes an
  underscore-prefixed field that would otherwise be skipped.
- `FlpList.from_json(text, Person)` reads a JSON array straight into a `FlpList[Person]`. Pass the complete
  target type, such as `list[Person]`, to `JsonConvert.deserialize` so nested and generic values decode
  against the right schema.

## Options

`JsonSerializerOptions` controls naming, default values and unknown fields:

```python
--8<-- "examples/json/json_options.py:options"
```

The other options are `default_handling` (`include` or `exclude` values that still hold their default) and
`unknown_field_handling` (`allow` or `disallow` JSON fields the model does not have).

## Custom types

`FlpList[T]` fields work without any setup. Other types are added to the type registry with `register_type`
(stored as one JSON value) or `register_collection` (stored as a JSON array):

```python
--8<-- "examples/json/json_options.py:custom_type"
```

When [`whenever`](https://github.com/ariebovenberg/whenever) is installed, its date and time types are
registered automatically and use its ISO 8601 parsing and formatting.

## Large outputs

`JsonConvert.serialize_to()` writes a JSON array to a file-like stream without building the whole document in
memory first.

## Backends

| Backend   | Used when                                     | Notes                                     |
|-----------|-----------------------------------------------|-------------------------------------------|
| `msgspec` | msgspec is installed (default on CPython)     | fastest                                   |
| `native`  | msgspec is not available (PyPy, Pyodide, ...) | standard library `json`, no dependencies  |

Both backends implement the same contract and run the same test suite. Choose one explicitly with
`flpit.json.set_backend("native")` or the `FLPIT_JSON_BACKEND` environment variable, and ask which one is active
with `get_backend()`. Float output can differ in exponent spelling (`1e16` against `1e+16`); the values are
identical.

By default, deserialization returns instances of the model you asked for. `JsonSerializerOptions(native=True)`
returns the generated `msgspec.Struct` instead: faster, but no longer your own class (msgspec backend only).

`import flpit` does not load the JSON support; it is loaded on first use.
