---
id: N02
title: count_by
status: todo
priority: 041
effort: S
depends_on: [F05, F06, F07, F08, F09, N01]
upstream:
  dotnet: CountByTests.cs @ dotnet/runtime main 6f1d9331 (6 [Fact]/[Theory])
  morelinq: CountBy.cs (reference only, D7; superseded by the .NET 9 operator)
pr:
---

# N02: `count_by`

## 1. Goal
`CountBy(keySelector)` (.NET 9) is the LINQ spelling of `collections.Counter(map(key, xs))`: a histogram by key without building groups. It replaces the common `group_by(k).select(lambda g: (g.key, g.count()))`, which materialises every element. It introduces the `KeyValue` named tuple (N01 convention) that N03 reuses, and it makes `dict(q)` the natural way to materialise the result.

## 2. Scope
**In:** `count_by(key_selector)` on `_LinqOps`; `KeyValue[K, V]` NamedTuple in `src/flpit/core/tuples.py`, exported from `flpit`.
**Out:** the `IEqualityComparer<TKey>? keyComparer` parameter (D3: normalise in the key selector, e.g. `count_by(str.casefold)`). A `long`-count variant (`LongCountBy` does not exist upstream either; Python ints are unbounded). A `to_dictionary()` shortcut for `KeyValue` sequences (L18 may add it; `dict(q)` works today).

## 3. Detailed design
### 3.1 Signatures
```python
# src/flpit/core/tuples.py
class KeyValue[K, V](NamedTuple):
    key: K
    value: V

# _LinqOps
def count_by(self, key_selector: Callable[[TItem], TKey]) -> FlpIt[KeyValue[TKey, int]]: ...
```
.NET overload mapping: `CountBy(source, keySelector, keyComparer = null)` → `count_by(key_selector)`; comparer omitted (D3).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (the whole source is consumed on the first `next()`; memory is O(distinct keys), not O(n)). Short-circuit: none.
- Validation (eager): `key_selector` `None` → `ArgumentNoneError("key_selector")`; not callable → `TypeError` (F05 `_require_callable`).
- Output order: keys in **order of first occurrence** (Python dict insertion order, same as .NET `Dictionary` without removals, which the upstream tests rely on). The key yielded is the first key object seen for that equality class (`1` vs `1.0` vs `True` collapse, Python hashing rules).
- `key_selector` is called exactly once per element, in source order, all before the first pair is yielded.
- Empty source → empty; the selector is never called.
- Keys must be hashable; an unhashable key raises `TypeError` at enumeration.
- Re-enumeration recounts from scratch (live view of a mutated list, like .NET).
- **Deviations** (README § Intentional Semantic Deviations):
  - `None` keys are allowed and counted (.NET `TKey : notnull`, a null key throws `ArgumentNullException` from `Dictionary` at enumeration).
  - Counts never overflow (.NET `checked` int); shared "no fixed-width integer overflow" entry (N01).
  - Results are `KeyValue` NamedTuples instead of `KeyValuePair` (N01 convention).

### 3.3 Implementation sketch
```python
_make_kv = partial(tuple.__new__, KeyValue)

def count_by(self, key_selector):
    _require_callable(key_selector, "key_selector")
    src = self._source()
    def _generator():
        counts = Counter(map(key_selector, src))   # C-level counting (_count_elements)
        yield from map(_make_kv, counts.items())
    return FlpIt(_FactoryIterable(_generator))
```
- `_generator` is a generator, so the source is consumed on the first `next()`, not on `iter()`, exactly like .NET's first `MoveNext` (the upstream `SourceThrowsOn*` tests check this).
- Time O(n), memory O(k) for k distinct keys. `Counter` preserves insertion order (dict subclass).
- **FlpList fast path**: none (no structural shortcut exists).
- No count provider for N10 (the number of keys is unknown without enumerating).

### 3.4 Registry entry
```toml
[operators.count_by]
category = "aggregation"
kind = "intermediate"
buffering = "full"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.CountBy"
morelinq = "MoreEnumerable.CountBy"
python_equivalent = "collections.Counter(map(key, xs)).items()"
since = "0.4.0"
card = "N02"
notes = "Yields KeyValue(key, value); None keys allowed (.NET throws)."
```

## 4. Tests
- **Ported** `tests/nettests/test_count_by.py` from `CountByTests.cs` (6 cases):
  - `CountBy_SourceNull` → `FlpIt(None)` raises `SourceNoneError`; comparer half dropped (`COMPARER_NOT_SUPPORTED` comment).
  - `CountBy_KeySelectorNull` → `ArgumentNoneError("key_selector")` at call.
  - `SourceThrowsOnGetEnumerator / OnMoveNext / OnCurrent`: ported with `tests.helpers` throwing iterables (exception surfaces on first `next`, not at call).
  - `CountBy_HasExpectedOutput`: all `Validate` calls ported (each also against a `RunOnce` source), except the two `StringComparer.OrdinalIgnoreCase` calls: rewriting them as `count_by(str.lower)` changes the yielded key (`"bob"` instead of first-seen `"Bob"`), so they are dropped with a `COMPARER_NOT_SUPPORTED` comment. `KeyValuePair` expectations become `(key, count)` tuples (equality holds with `KeyValue`).
  - Target: 6/6 test functions ported (100 %); 2 of 11 `Validate` calls dropped.
- **Own unit tests** (`tests/unit/test_count_by.py`): first-occurrence order (`"abcab"` gives `a, b, c`); `None` keys counted; `1`/`1.0`/`True` collapse to the first key; selector call count equals len(source) and zero for empty; unhashable key raises `TypeError` at enumeration, not at call; `dict(q)` and attribute access `.key`/`.value`; deferral (`NoIterList`); re-enumeration after mutating the backing list.
- **Contracts**: auto (registry: full buffering, deferred).
- **Typing**: `assert_type(flp.it(["a"]).count_by(len), FlpIt[KeyValue[int, int]])`; `assert_type(dict(flp.it(["a"]).count_by(len)), dict[int, int])`.

## 5. Differential harness
`difftest/specs/count_by.toml`: sources: empty, singleton, ints with duplicates, strings (mixed case), 1000 ints; key selectors: identity, `x % 5`, constant `true`, string length. Probes: values (KeyValue → `[key, value]`), selector call count, exception type for null selector. Domain "strings with nulls + identity key" is `EXPECTED_DIFFERENCE` (reason: .NET throws `ArgumentNullException` for null keys, flpit counts them). Everything else MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_count_by.py`, sizes 1e3 and 1e5, ints with `key = x % 100`:
- `native`: `list(Counter(map(key, data)).items())`
- `flpit-FlpIt`: `flp.it(data).count_by(key).to_list()`; `flpit-FlpList`: same on `flp.lst(data)`.
- Target ratio ≤ 1.3× (buffering op; key construction dominates, 100 KeyValues are negligible).

## 7. Docs
- Docstring: "Counts the elements of the sequence per key."; `.NET: Enumerable.CountBy(keySelector)`; Args/Returns/Raises; Execution: deferred, full buffering (O(distinct keys) memory), first-occurrence order; note on `None` keys and on using a normalising selector instead of a comparer. Example:
  ```python
  >>> flp.it(["a", "bb", "cc", "d"]).count_by(len).to_list()
  [KeyValue(key=1, value=2), KeyValue(key=2, value=2)]
  >>> dict(flp.it("hello").count_by(lambda c: c))
  {'h': 1, 'e': 1, 'l': 2, 'o': 1}
  ```
- README matrix row; deviation entries (None keys, KeyValue); "Named tuple results" table gains `KeyValue`.
- Translation map: `Counter(map(key, xs))` / `.CountBy(k)` / MoreLINQ `CountBy` → `.count_by(k)`.

## 8. Expected outcomes
- `count_by` on all four types; `KeyValue` exported; `dict(flp.it(xs).count_by(k))` is the documented histogram idiom.
- 6 ported .NET tests green, own tests, typing, benchmark recorded, difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=count_by`, plus:
```bash
uv run pytest -q tests/nettests/test_count_by.py -rs
uv run python -c "from flpit import flp; print(dict(flp.it('hello').count_by(lambda c: c)))"
# {'h': 1, 'e': 1, 'l': 2, 'o': 1}
```

## 10. Definition of Done
DoD-std, plus `KeyValue` in `tuples.py` and `flpit.__all__`, and the None-key deviation listed in README.

## 11. Risks / open questions
- The pattern "buffer everything with a C-level builder, then `yield from`" is shared with N03 and the joins; keep it consistent so F08's deferral contract (nothing pulled before the first `next()`) holds for all of them.
- Should `count_by` accept an optional `predicate`/`where` shortcut? No: compose `where(...).count_by(...)`.
