---
id: B05
title: distinct / distinct_by
status: todo
priority: 017
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: DistinctTests.cs @ dotnet/runtime main 6f1d9331 (29 [Fact]/[Theory], DistinctBy tests included)
  morelinq: n/a
pr:
---

# B05: `distinct` / `distinct_by` (backfill)

## 1. Goal
Both operators exist and stream correctly, but `DistinctTests.cs` (which also holds the `DistinctBy` tests) is not ported, `distinct_by(None)` is accepted and only fails on enumeration, and Python-specific equality behaviour (unhashable elements, `1 == 1.0 == True`, `NaN`) is undocumented. This card ports the tests, adds eager validation, records the hashing decisions and lands the deviation notes.

## 2. Scope
**In:** `distinct()`, `distinct_by(key_selector)` on `_LinqOps`; eager `key_selector` validation; docs; port of `DistinctTests.cs`.
**Out:** comparer overloads (D3); a linear-scan fallback for unhashable elements (rejected, §3.2).

## 3. Detailed design
### 3.1 Signatures
```python
THashKey = TypeVar("THashKey", bound=Hashable)

def distinct(self) -> FlpIt[TItem]: ...
def distinct_by(self, key_selector: Callable[[TItem], THashKey]) -> FlpIt[TItem]: ...
```
.NET overloads: `Distinct()` → `distinct()`; `Distinct(comparer)` → D3, use `distinct_by(key)`; `DistinctBy(keySelector)` → `distinct_by(key_selector)`; `DistinctBy(keySelector, comparer)` → D3, fold the comparer into the key (`distinct_by(lambda p: p.name.casefold())`).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (first occurrence is yielded immediately); memory grows with the number of distinct keys, O(u). Short-circuit: `distinct().first()` pulls 1 element.
- Order: first occurrence wins, source order preserved.
- Equality = Python hash + `==`. `None` is an ordinary value (`[None, None, ""]` → `[None, ""]`).
- Validation (eager): `key_selector is None` → `ArgumentNoneError("key_selector")` (.NET param `keySelector`).
- **Unhashable elements/keys** (`list`, `dict`, `set`, `@dataclass` with `eq=True` and no `frozen`): `TypeError` raised lazily when the offending element is reached, after earlier distinct elements were yielded. **Decision: no linear-scan fallback** (as `more_itertools.unique_everseen` does): it would silently turn O(n) into O(n²). Workaround documented: `distinct_by(tuple)` for value equality, `distinct_by(id)` for .NET-style reference equality.
- **Cross-type equality**: `1`, `1.0`, `True` (and `Decimal(1)`) hash and compare equal, so `[1, True, 1.0]` → `[1]`. .NET `object[]` keeps three elements (different types are never `Equals`). **README deviation entry.**
- **NaN**: .NET `double.Equals(NaN, NaN)` is true, so one `NaN` survives. Python `set` deduplicates `NaN` only when it is the *same object* (identity shortcut); distinct `float("nan")` objects all survive. **README deviation entry**; `distinct_by(lambda x: "nan" if x != x else x)` documented as workaround.
- `0.0` and `-0.0` collapse (first wins) in both runtimes.
- Exceptions from `key_selector` propagate at enumeration; the key selector is called exactly once per element.

### 3.3 Implementation sketch
```python
def distinct_by(self, key_selector):
    _require_callable(key_selector, "key_selector")             # F05 helper
    def _generator():
        seen: set[Any] = set()
        add = seen.add
        for item in self:
            key = key_selector(item)
            if key not in seen:
                add(key)
                yield item
    return FlpIt(_FactoryIterable(_generator))
```
- `distinct()` is the same loop without the selector call (no `lambda x: x` indirection). O(n) average time, O(u) memory.
- **FlpList fast path** `dict.fromkeys(data)`: rejected. It is eager (hashes the whole list before the first yield), so `first()` cost, exception timing for unhashable elements, and laziness would differ. Not observationally equivalent.

### 3.4 Registry entry
```toml
[operators.distinct]
category = "set"
kind = "intermediate"
buffering = "streaming"        # memory O(distinct)
short_circuit = false
dotnet = "Enumerable.Distinct"
python_equivalent = "dict.fromkeys(xs)"
since = "0.2.0"                # pre-registry operator

[operators.distinct_by]
category = "set"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.DistinctBy"
python_equivalent = "more_itertools.unique_everseen(xs, key=f)"
since = "0.2.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_distinct.py` from `DistinctTests.cs` (29):
  - Ported (25): `SameResultsRepeatCallsIntQuery`, `SameResultsRepeatCallsStringQuery`, `EmptySource`, `EmptySourceRunOnce`, `SingleNullElementExplicitlyUseDefaultComparer`, `EmptyStringDistinctFromNull`, `CollapsDuplicateNulls` (default comparer → plain `distinct()`), `SourceAllDuplicates`, `AllUnique`, `SomeDuplicatesIncludingNulls` (+`RunOnce`), `LastSameAsFirst`, `RepeatsNonConsecutive` (+`RunOnce`), `NullComparer`, `CustomEqualityComparer` (+`RunOnce`) rewritten per D3 as `distinct_by(lambda s: "".join(sorted(s)))` (the anagram comparer is ordinal, case-sensitive), `FindDistinctAndValidate` (6 rows; `long`/`float`/`double` rows become `int`/`float`, `decimal` → `Decimal`), `ToArray`, `ToList`, `Count`, `RepeatEnumerating`, `DistinctBy_KeySelectorNull_ThrowsArgumentNullException` (comparer line dropped), `DistinctBy_HasExpectedOutput` and `DistinctBy_RunOnce_HasExpectedOutput` (11 rows; `StringComparer.OrdinalIgnoreCase` rows rewritten as `key=str.casefold`; data is ASCII so intent is preserved).
  - Adapted (1): `ForcedToEnumeratorDoesntEnumerate` → query is not an `Iterator`.
  - Skips: `OTHER` 3 (`NullSource`, `NullSourceCustomComparer`, `DistinctBy_SourceNull_ThrowsArgumentNullException`: no extension methods on `None`). No `COMPARER_NOT_SUPPORTED` skips: every comparer case is expressible as a key.
  - Target: 26/29 ≈ 90 % ported.
- **Own unit tests** (`tests/unit/test_distinct.py`):
  - Unhashable element: earlier elements yielded, then `TypeError`; `distinct_by(tuple)` works on lists.
  - `[1, True, 1.0]` → `[1]`; two distinct `nan` objects → both kept; same `nan` object twice → one.
  - `distinct_by(None)` raises at call time on a `NoIterList` source; key selector called once per element (tracker).
  - Consumer stops early: the source generator is not advanced further (existing luna test moved).
- **Contracts** (auto): `distinct().first()` pulls 1.
- **Typing**: `assert_type(q.distinct_by(lambda r: r.id), FlpIt[Row])`; pyrefly rejects `distinct_by(lambda r: [r.id])` (`list` is not `Hashable`).

## 5. Differential harness
`difftest/specs/distinct.toml`: sources {empty, all duplicates, ints with duplicates, nullable ints with `null`, strings with case variants, doubles with `NaN`/`-0.0`}; `distinct_by` keys {identity, `x % 5`, constant `true`, `string.ToUpperInvariant` ↔ `str.upper`}. Expected MATCH, except doubles containing several `NaN` values → `EXPECTED_DIFFERENCE` (reason: §3.2 NaN rule). Mixed-type object sources are not generated (cross-type rule is documented, not compared).

## 6. Benchmarks
`tests/benchmarks/test_bench_distinct.py`, sizes 1e3 and 1e5, data `[i % (n // 2) for i in range(n)]` and a string variant:
- `native`: `list(dict.fromkeys(data))` (eager C path) and the streaming `unique_everseen` recipe from the `itertools` docs.
- `flpit-FlpIt`, `flpit-FlpList`: `.distinct().to_list()`; `.distinct_by(f)` vs `unique_everseen(data, key=f)`.
- Target ≤ 1.5× vs the streaming recipe; ratio vs `dict.fromkeys` recorded for information (today ≈ 1.6×, 0.16 s vs 0.10 s for 20 × 1e5 unique ints).

## 7. Docs
- Docstrings: `.NET: Enumerable.Distinct()` / `DistinctBy(keySelector)`; first occurrence wins; hashing rules (unhashable, cross-type, NaN) with workarounds; D3 note on comparers. Doctests: `flp.it([3, 1, 3, None, 1]).distinct().to_list()` → `[3, 1, None]`; `flp.it(["Bob", "bob", "Tim"]).distinct_by(str.lower).to_list()` → `['Bob', 'Tim']`.
- README deviations: cross-type equality, NaN, unhashable elements.
- Translation map: `.Distinct()` / `dict.fromkeys(xs)` → `.distinct()`; `.DistinctBy(k)` / `unique_everseen(xs, key=k)` → `.distinct_by(k)`; `.Distinct(StringComparer.OrdinalIgnoreCase)` → `.distinct_by(str.casefold)`.

## 8. Expected outcomes
- 26 ported .NET tests green, including all comparer cases via key selectors.
- Hashing behaviour documented; `distinct_by(None)` fails fast.

## 9. Verification
VERIFY-std with `<op>=distinct`, plus:
```bash
uv run pytest -q tests/nettests/test_distinct.py -rs
uv run python -c "from flpit import flp; print(flp.it([3, 1, 3, None, 1]).distinct().to_list())"   # [3, 1, None]
uv run python -c "from flpit import flp; flp.it([1]).distinct_by(None)"   # ArgumentNoneError at call time
```

## 10. Definition of Done
DoD-std, plus: three README deviation entries; `THashKey` bound added without new pyrefly errors elsewhere.

## 11. Risks / open questions
- The `Hashable` bound on the key type may flag code that relies on `Any` keys; acceptable (it only narrows what was already a runtime error).
- L21–L23 (set operators) need the same hashing helper and deviation text; they should reference this card's README entries instead of duplicating them.
