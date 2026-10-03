---
id: M25
title: to_delimited_string
status: todo
priority: 085
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (closest .NET API: string.Join<T>(string, IEnumerable<T>))
  morelinq: ToDelimitedString.cs, ToDelimitedString.g.cs @ morelinq master d217ab1 (reference only, D7; ToDelimitedStringTest.cs 4 [Test] read for behaviour)
pr:
---

# M25: `to_delimited_string`

## 1. Goal
Ending a pipeline with "join as text" currently breaks the fluent chain: `", ".join(map(str, query))`, and `", ".join(query)` raises `TypeError` on non-strings. `to_delimited_string(", ")` is the terminal for logging, CSV-ish output and messages. The only design question is how elements are rendered, in particular `None`; this card decides it.

## 2. Scope
**In:** `to_delimited_string(delimiter)` on `_LinqOps`.
**Out:** a format callback (`select(fmt).to_delimited_string(d)` composes); a default delimiter (MoreLINQ requires one; `""` is explicit); prefix/suffix wrapping.

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `ToDelimitedString<T>(string delimiter)` | `to_delimited_string(delimiter)` |
| 14 typed overloads (`IEnumerable<bool/byte/char/decimal/double/float/int/long/sbyte/short/string/uint/ulong/ushort>`) | same method; they exist only to avoid boxing in .NET, behaviour is identical |

## 3. Detailed design
### 3.1 Signatures
```python
def to_delimited_string(self, delimiter: str) -> str: ...
```
### 3.2 Semantics
- Kind: terminal. Buffering: full (rendered pieces are collected, then joined once). Short-circuit: none.
- **Element rendering (decision):** `None` renders as the **empty string**, every other element as `str(element)`.
  - `None → ""` matches MoreLINQ (`StringBuilder.Append(object null)` appends nothing; MoreLINQ issue 43 pins `[null, null, "foo"] → ",,foo"`), so the difftest compares equal. It deliberately differs from the naive Python idiom `",".join(map(str, xs))`, which gives `"None,None,foo"`. Users who want `"None"` write `select(str).to_delimited_string(d)`.
  - `str()` instead of .NET `ToString()` is an **intentional deviation** for non-string scalars whose text differs between runtimes: floats (`1.0` → `"1.0"` vs .NET `"1"`, `1e20` → `"1e+20"` vs `"1E+20"`, `nan`/`inf` vs `NaN`/`∞`), and containers (`FlpList` renders as `[1, 2]`, .NET as the type name). `bool` (`True`/`False`), `int` and `str` render identically. README § "Intentional Semantic Deviations" gets an entry.
- No escaping or quoting: delimiters inside elements are left as they are (same as MoreLINQ).
- Empty source → `""`. Singleton → `str(x)` with no delimiter.
- Validation (eager): `delimiter is None` → `ArgumentNoneError("delimiter")`; a non-`str` delimiter → `TypeError("delimiter must be str")` (Python's own `join` error would come too late and name the wrong object). `""` is allowed.
- Exceptions from the source or from an element's `__str__` propagate; nothing is returned partially.

### 3.3 Implementation sketch
```python
def to_delimited_string(self, delimiter):
    _require_not_none(delimiter, "delimiter")
    if not isinstance(delimiter, str):
        raise TypeError("delimiter must be str")
    return delimiter.join(["" if x is None else str(x) for x in self._source()])
```
- O(total length) time and memory. A list comprehension is passed to `join` because `str.join` materialises a generator into a list anyway; the comprehension avoids generator frame overhead (prototype at 1e5 ints: 9.8 ms vs 9.4 ms for `",".join(map(str, data))`).
- **FlpList fast path:** none (no shortcut exists; the generic path already iterates the backing list directly via `_source()`).

### 3.4 Registry entry
```toml
[operators.to_delimited_string]
category = "conversion"
kind = "terminal"
buffering = "full"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.ToDelimitedString"
python_equivalent = "delimiter.join(map(str, xs))"
contract_args = "(',',)"
since = "0.4.0"   # adjust to the release that ships it
card = "M25"
notes = "None renders as ''; non-None elements use str() (floats/containers differ from .NET ToString)"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design); MoreLINQ's 4 cases (non-empty ints, nulls in the middle, nulls at the start, null delimiter) each have an own equivalent. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_to_delimited_string.py`, both `flp_type`s):
  - `[1, 2, 3]` with `"-"` → `"1-2-3"`; empty → `""`; singleton; empty delimiter; multi-character delimiter.
  - `None` at start, middle, end and all-None (`[None, None]` with `","` → `","`).
  - Mixed types: `[1, None, "foo", True]` → `"1,,foo,True"`; floats `[1.0, 2.5]` → `"1.0,2.5"` (pins the documented deviation).
  - Element with a raising `__str__` propagates; delimiter appearing inside an element is not escaped.
  - `None` delimiter → `ArgumentNoneError`; `1` as delimiter → `TypeError`, both before iterating (`NoIterList`).
  - One-shot source is consumed once.
- **Contracts** (auto): terminal, FlpList not mutated, eager validation.
- **Typing** (`tests/typing/test_types_to_delimited_string.py`): returns `str` on every receiver type.

## 5. Differential harness
`difftest/specs/to_delimited_string.toml`; oracle `Operators/ToDelimitedString.cs` calling `MoreEnumerable.ToDelimitedString(source, delimiter)` statically with `CultureInfo.InvariantCulture` set on the oracle thread.
- Items: empty, singleton, ints (negatives, duplicates), strings (including ones containing the delimiter and empty strings), bools, nulls at start/middle/end; delimiters `""`, `","`, `" | "`.
- Probes: result string, exception for `null` delimiter (`at: "call"`).
- Expected: MATCH for the int/str/bool/null domain. A float domain is declared with `EXPECTED_DIFFERENCE` (reason: "OTHER: str() vs .NET ToString() number formatting") so the deviation stays visible in coverage reports instead of being silently excluded.

## 6. Benchmarks
`tests/benchmarks/test_bench_to_delimited_string.py`, sizes 1e3 / 1e5, random ints:
- `native`: `",".join(map(str, data))`
- `flpit-FlpIt`: `flp.it(data).to_delimited_string(",")`; `flpit-FlpList`: `flp.lst(data).to_delimited_string(",")`.
- Target ratio ≤ 1.3× (buffering default; prototype ~1.05×).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.ToDelimitedString(delimiter)`; rendering rule (`None` → `""`, else `str()`), with the `select(str)` tip; Raises; `Execution: Terminal, consumes the whole source`; doctests:
  ```python
  >>> flp.it([1, None, "foo", True]).to_delimited_string(",")
  '1,,foo,True'
  >>> flp.it(range(3)).to_delimited_string(" -> ")
  '0 -> 1 -> 2'
  >>> flp.it([]).to_delimited_string(",")
  ''
  ```
- README deviation entry: "`to_delimited_string` renders with `str()`; `None` → `''` like .NET; floats and containers are formatted the Python way."
- Translation map: MoreLINQ `.ToDelimitedString(", ")` / .NET `string.Join(", ", xs)` / Python `", ".join(map(str, xs))` → `.to_delimited_string(", ")`.

## 8. Expected outcomes
- A fluent string terminal whose `None` handling matches .NET and whose number formatting deviation is documented and tracked by the harness.
- difftest spec: 0 MISMATCH, one declared EXPECTED_DIFFERENCE domain.

## 9. Verification
VERIFY-std with `<op>=to_delimited_string`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_to_delimited_string.py
uv run python -c "from flpit import flp; print(repr(flp.it([None, None, 'foo']).to_delimited_string(',')))"   # ',,foo'
uv run python -c "from flpit import flp; flp.it([1]).to_delimited_string(None)"                               # ArgumentNoneError ... (Parameter 'delimiter')
```

## 10. Definition of Done
DoD-std, plus: README deviation entry; the float `EXPECTED_DIFFERENCE` domain is present in the spec (not omitted).

## 11. Risks / open questions
- Alternative considered: `None → "None"` (pure Python idiom). Rejected because it breaks .NET parity for the most common nullable case, while the Python behaviour stays one `select(str)` away. If the maintainer prefers the Python rendering, flip the rule and turn the null domain into an EXPECTED_DIFFERENCE.
- Future `float` formatting parity (e.g. a `.NET`-style formatter) is out of scope; X01's value model will classify float text explicitly.
