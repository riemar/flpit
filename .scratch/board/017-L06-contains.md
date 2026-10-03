---
id: L06
title: contains
status: todo
priority: 017
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ContainsTests.cs @ dotnet/runtime main 6f1d9331 (13 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L06: `contains`

## 1. Goal
`Contains(value)` is the terminal membership test at the end of a pipeline (`...where(...).contains(x)`), listed in `rules.md` as a core terminal op but missing. Python users can write `x in query`, but that is not discoverable in a fluent chain and has no documented short-circuit or equality contract. This card also fixes the **equality contract** that L14 (`sequence_equal`) and the set operators L21–L23 build on, in a small private module.

## 2. Scope
**In:** `contains(value)` on `_LinqOps`; deferral to the source's own `__contains__` (like .NET deferring to `ICollection<T>.Contains`); new private module `src/flpit/core/_equality.py` with the equality helpers; README deviation entry "Equality semantics".
**Out:** `Contains(value, IEqualityComparer)` (D3: no comparer objects; the comparer use case is `xs.select(key).contains(key(value))`, shown in the docstring). A `contains_by` variant is not added (no .NET counterpart).

## 3. Detailed design
### 3.1 Signatures
```python
def contains(self, value: TItem) -> bool: ...
```
| .NET | Python |
|---|---|
| `Contains(TSource value)` | `contains(value)` |
| `Contains(TSource value, IEqualityComparer<TSource>? comparer)` | omitted (D3); `comparer: null` cases port to `contains(value)` |

### 3.2 Semantics
- Kind: terminal. Short-circuit: stops at the first equal element; scans everything when absent.
- **Equality** (new, documented once in `_equality.py` and README): Python container semantics, `item is value or item == value` (CPython `PyObject_RichCompareBool`), the element's `__eq__` and the reflected `__eq__` are honoured. Consequences, listed in README § "Intentional Semantic Deviations":
  - NaN: `.NET` `double.NaN.Equals(double.NaN)` is `true`; in flpit two distinct `float('nan')` objects are not equal (the same object is, by identity).
  - Cross-type numeric equality: `flp.it([1]).contains(1.0)` and `contains(True)` are `True`.
- **Deferral to the source** (mirrors .NET's "no comparer defers to collection", test `NoComparerDoesDeferToCollection`): when `self` does not override `__iter__` (FlpIt, FlpList, Grouping; never `OrderedIt`) and the underlying source is a `collections.abc.Container`, the result is `value in source`. Exceptions: `str`, `bytes`, `bytearray`, `memoryview` are **never** deferred (their `in` is substring/byte-value semantics, not element membership).
- Unhashable values against builtin hash containers (`set`, `frozenset`, `dict`, dict key/item views): `[1] in {1}` raises `TypeError` in Python; flpit catches that `TypeError` **only for these exact types** and falls back to a linear scan, so `FlpIt(set_source).contains([1])` returns `False` like the non-collection path. Custom containers' exceptions propagate.
- `None` is an ordinary value: `contains(None)` finds `None` elements. No argument validation (any value is legal, as in .NET).
- One-shot sources are consumed up to the match.
- Exceptions from the source or from an element's `__eq__` propagate.

### 3.3 Implementation sketch
```python
# _equality.py (private)
def items_equal(a: object, b: object) -> bool:         # reused by L14, L21–L23
    return a is b or bool(a == b)

_HASHED_EXACT = (set, frozenset, dict, type({}.keys()), type({}.items()))   # exact types only
_NOT_ELEMENTWISE = (str, bytes, bytearray, memoryview)

def container_contains(src: Container[object], value: object) -> bool:
    if type(src) in _HASHED_EXACT:
        try:
            return value in src
        except TypeError:                               # unhashable value
            return any(items_equal(x, value) for x in src)
    return value in src

# _LinqOps
def contains(self, value):
    src = self._source() if not self._overrides_iter() else None
    if src is not None and isinstance(src, Container) and not isinstance(src, _NOT_ELEMENTWISE):
        return container_contains(src, value)
    return value in iter(self)                          # C-level scan, identity-or-eq, short-circuits
```
- `value in iterator` runs the C loop `PySequence_Contains` → identical equality rule to `items_equal`, no Python-level per-element call. O(n) time, O(1) memory.
- **FlpList**: covered by the deferral (`_source()` is the backing `list`), no override needed.
- `OrderedIt.contains` iterates (sorts). .NET does not skip ordering for `Contains` either; skipping it would change key-selector call counts. Not optimised.

### 3.4 Registry entry
```toml
[operators.contains]
category = "quantifier"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.Contains"
python_equivalent = "value in xs"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_contains.py` from `ContainsTests.cs` (13). `IdentityTransforms` map to `flp_type` × {`list`, `tuple`, `set` where order is irrelevant, `non_collection`}.
  - `Int`, `IntRunOnce` (10 rows × transforms), `NullableInt` (4 rows), `SameResultsRepeatCalls*` (2), `NullSource` (`SourceNoneError`): ported; `Contains(value, null)` sub-asserts collapse into `contains(value)`.
  - `String`, `StringRunOnce`: `StringComparer.Ordinal` rows port as plain equality; `AnagramEqualityComparer` rows are rewritten per D3 as `select(sorted_key).contains(sorted_key(value))` (intent preserved).
  - `NoComparerDoesDeferToCollection`: ported with a case-insensitive `Container` subclass (`__contains__` override) wrapped in `flp.it`, asserting deferral.
  - `COMPARER_NOT_SUPPORTED` (3): `ExplicitNullComparerDoesNotDeferToCollection`, `ExplicitComparerDoesNotDeferToCollection`, `ExplicitComparerDoestNotDeferToCollectionWithComparer`.
  - `FollowingVariousOperators`: split into one `pytest` param per operator family. Ported now: Append/Prepend, Concat, Distinct (comparer rows rewritten with `distinct_by(lambda x: 0)`), OrderBy(+ThenBy), OrderByDescending, Where/Select, SelectMany, Skip/Take, Repeat, Cast, OfType. Added later by the owning card: DefaultIfEmpty (L12), Union (L21), Shuffle (N11).
  - Target: 10 of 13 methods ported (77 %); 3 categorised skips.
- **Own unit tests** (`tests/unit/test_contains.py`):
  - Short-circuit: stops pulling after the match (pull counter on a generator).
  - `str` source: `flp.it("abc").contains("ab")` is `False` (no substring semantics); `bytes` likewise.
  - `set` source with an unhashable value returns `False`; custom container raising propagates.
  - NaN identity vs distinct NaN; `1`, `1.0`, `True` equality; `None` value.
  - `OrderedIt` source still invokes key selectors (no shortcut).
- **Contracts** (auto): terminal; short-circuit probe (stops after first match); FlpList not mutated.
- **Typing**: `assert_type(flp.it([1]).contains(1), bool)`; `flp.it([1]).contains("x")` is a pyrefly error.

## 5. Differential harness
`difftest/specs/contains.toml`: sources (non-collection only, so deferral is not in play) empty, ints with duplicates, strings with `None`; values present at first/middle/last position, absent, `None`; probes `result`, `elements_pulled` (match index + 1, or n). Floats with NaN: `EXPECTED_DIFFERENCE` (reason: README Equality deviation).

## 6. Benchmarks
`tests/benchmarks/test_bench_contains.py`, sizes 1e3 / 1e5, value in the middle and absent:
- `native`: `v in data` (list) and `v in (x for x in data if x >= 0)` (pipeline case)
- `flpit-FlpIt`: `flp.it(data).contains(v)` and `flp.it(data).where(lambda x: x >= 0).contains(v)`; `flpit-FlpList`: `flp.lst(data).contains(v)`
- Target ratio ≤ 1.5× (terminal short-circuit); deferral case expected ≈ 1.0×.

## 7. Docs
- Docstring: `.NET: Enumerable.Contains(value)`; the equality rule; deferral to `__contains__` (and the str/bytes exception); comparer replacement `xs.select(key).contains(key(v))`; Execution: Terminal, short-circuits.
- Doctests: `flp.it(range(5)).where(lambda x: x % 2 == 0).contains(4)` gives `True`; `flp.it("abc").contains("ab")` gives `False`.
- README: new deviation section "Equality semantics" (NaN, cross-type numerics, honours `__eq__`), referenced by L14 and L21–L23.
- Translation map: `v in xs` / `.Contains(v)` → `.contains(v)`; `.Contains(v, cmp)` → `.select(key).contains(key(v))`.

## 8. Expected outcomes
- `contains` on all four types; 10 ported methods green, 3 comparer skips.
- `_equality.py` with `items_equal` and `container_contains`, documented as the single equality contract.

## 9. Verification
VERIFY-std with `<op>=contains`, plus:
```bash
uv run pytest -q tests/nettests/test_contains.py -rs        # 3 COMPARER_NOT_SUPPORTED skips
uv run python -c "from flpit import flp; print(flp.it('abc').contains('ab'), flp.it({1}).contains([1]))"   # False False
```

## 10. Definition of Done
DoD-std, plus the README "Equality semantics" deviation entry and unit tests for `_equality.py`.

## 11. Risks / open questions
- Deferring to arbitrary `Container`s means a user container whose `__contains__` disagrees with its `__iter__` gives container semantics. This mirrors .NET and is documented; the alternative (deferring only for builtin types) would fail the ported `NoComparerDoesDeferToCollection`.
- L21–L23 should extend `_equality.py` (e.g. a key set with a linear fallback for unhashable keys) rather than re-deriving the rule. Note: the existing `distinct` raises `TypeError` on unhashable elements; aligning it is B05's call.
