---
id: B07
title: flp.range
status: todo
priority: 060
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: RangeTests.cs @ dotnet/runtime main 6f1d9331 (25 [Fact]/[Theory] + 2 [ConditionalFact])
  morelinq: n/a
pr:
---

# B07: `flp.range` (backfill)

## 1. Goal
`flp.range(start, count)` mirrors `Enumerable.Range` but has no ported tests and deviates on argument handling: a negative `count` silently yields nothing (.NET throws `ArgumentOutOfRangeException("count")` at call time), `None` arguments fail with an unrelated `TypeError` from `None + count`, and the signature (`start, count`) differs from `builtins.range(start, stop)` without any warning in the docstring. This card fixes validation, resolves board open question 4 (the name), and ports `RangeTests.cs`.

## 2. Scope
**In:** `flp.range` in `src/flpit/flp.py`; eager validation; docstring; port of `RangeTests.cs` (the `RangeTestsBase` tests run once against `flp.range`).
**Out:** the `SequenceAsRangeTests` subclass (re-parametrised over `flp.sequence` by N12); Int32 overflow emulation (decided below); O(1) `last()`/`element_at()` on ranges (belongs to the Sequence fast paths of L08/L10).

## 3. Detailed design
### 3.1 Signatures
```python
def range(start: int, count: int) -> FlpIt[int]: ...
```
.NET `Range(int start, int count)` maps 1:1 (single overload).

### 3.2 Semantics
- Kind: factory (deferred: no work until enumeration). Buffering: none (O(1) memory). Re-iterable: yes, every enumeration restarts at `start`; independent iterators per `iter()` call.
- Validation (eager): `start = operator.index(start)`, `count = operator.index(count)`; `None` → `ArgumentNoneError("start"/"count")`; `1.5` → `TypeError`; `count < 0` → `ArgumentOutOfRangeError("count", count)`, parameter name `count` as .NET (message format owned by F05). `count == 0` → empty for any `start`.
- **Overflow: not emulated.** .NET throws when `start + count - 1 > int.MaxValue`; Python ints are unbounded, so `flp.range(2**31 - 1, 1000)` simply yields 1000 values. **README deviation entry** ("integer factories are not limited to Int32").
- **Name (open question 4): keep `flp.range(start, count)`.** It is the documented .NET mapping and renaming would break users. Mitigations: the docstring opens with "`count`, not `stop`: `flp.range(1, 10)` yields 1..10"; `"range"` is removed from `flp.__all__` so `from flpit.flp import *` can no longer shadow the builtin (attribute access `flp.range` unchanged).
- `bool` arguments are accepted as ints (documented).

### 3.3 Implementation sketch
```python
def range(start: int, count: int) -> FlpIt[int]:
    start = _require_index(start, "start")
    count = _require_index(count, "count")
    if count < 0:
        raise ArgumentOutOfRangeError("count", count)
    return FlpIt(builtins.range(start, start + count))
```
- Wrapping the `builtins.range` object (a re-iterable `Sequence`) keeps C-speed iteration and lets the generic `Sequence` fast paths of other cards (`last`, `element_at`, `count`, `try_get_non_enumerated_count`) apply in O(1).
- No FlpList involvement.

### 3.4 Registry entry
```toml
[operators.range]
category = "generation"
kind = "factory"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Range"
python_equivalent = "range(start, start + count)"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_range.py` from `RangeTests.cs` (27 = 25 + 2 `[ConditionalFact]`):
  - Ported now (16): `Range_ThrowExceptionOnNegativeCount` (`-1`, `-2**31`), `Range_ProduceCorrectSequence`, `Range_ToArray_ProduceCorrectResult` (64 rows), `Range_ToList_ProduceCorrectResult`, `Range_ZeroCountLeadToEmptySequence` (starts `1`, `-2**31`, `2**31 - 1`), `Range_NotEnumerateAfterEnd` (`next(it, sentinel)` twice after the end), `Range_GetEnumeratorReturnUniqueInstances` (`iter(q) is not iter(q)`), `Range_ToInt32MaxValue`, `RepeatedCallsSameResults`, `NegativeStart`, `ArbitraryStart`, `Take`, `TakeExcessive`, `ElementAt`, `ElementAtExcessiveThrows` (`IndexError`), `First` (count 1e9, lazy).
  - Written now, active once other cards land (8, F08 `requires_op` marker): `Skip`, `SkipExcessive`, `SkipTakeCanOnlyBeOne` (L01); `ElementAtOrDefault`, `ElementAtOrDefaultExcessiveIsDefault` (L10, `default=0` because .NET `default(int)` is `0`); `FirstOrDefault` (L07); `Last`, `LastOrDefault` (`[ConditionalFact]` speed tests over 1e9 elements: L08 plus an O(1) `Sequence` fast path in `last`, else `LONG_RUNNING`).
  - Skips: `NO_VALUE_TYPES` 1 (`Range_ThrowExceptionOnOverflow`); `INTERNAL_OPTIMIZATION` 2 (`Range_EnumerableAndEnumeratorAreSame`, `IListImplementationIsValid`).
  - Target: 24/27 ≈ 89 % once L01/L07/L08/L10 are merged; 16/27 ≈ 59 % at merge time if none of them has landed.
- **Own unit tests** (`tests/unit/test_range.py`):
  - `flp.range(None, 1)`, `flp.range(0, None)`, `flp.range(0, 1.5)` raise at call time with the right parameter name.
  - `flp.range(5, -3)` now raises (the luna test asserting `[]` is updated; CHANGELOG "Changed").
  - `flp.range(2**31 - 1, 3)` → three values beyond Int32 (deviation test).
  - Re-enumeration and two interleaved iterators.
  - `"range" not in flp.__all__`; `flp.range` still importable.
- **Contracts** (auto, `kind = "factory"`): construction does no work; re-iterable.
- **Typing**: `assert_type(flp.range(0, 3), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/range.toml`: `start ∈ {-5, 0, 1, 12, 2**31-4}`, `count ∈ {0, 1, 4, 100}`; invalid `count ∈ {-1, -2**31}` → `ArgumentOutOfRange`; overflow pairs (`(1000, 2**31-1)`, `(2**31-1, 1000)`) → `EXPECTED_DIFFERENCE` (no Int32 limit). Composed probes `.take(k)`, `.first()`, `.element_at(i)`. Expected: MATCH otherwise.

## 6. Benchmarks
`tests/benchmarks/test_bench_range.py`, sizes 1e3 and 1e5:
- `native`: `list(range(s, s + n))`; `flpit`: `flp.range(s, n).to_list()`; pipeline case `flp.range(0, n).where(even).to_list()` vs `[x for x in range(n) if x % 2 == 0]`.
- Target ≤ 1.3× for the plain factory (today ≈ 1.1×), ≤ 1.5× for the pipeline. (Only one flpit variant: there is no FlpList form of a factory; the group records `flpit-FlpIt` and `native`.)

## 7. Docs
- Docstring: `.NET: Enumerable.Range(start, count)`; "**count, not stop**" with the example; eager validation; re-iterable; no Int32 limit. Doctest: `flp.range(3, 4).to_list()` → `[3, 4, 5, 6]`.
- README deviation entry: no Int32 overflow check. README note on the `start, count` signature.
- Translation map: `Enumerable.Range(s, n)` / `range(s, s + n)` → `flp.range(s, n)`.

## 8. Expected outcomes
- Negative counts fail fast like .NET; the signature pitfall is documented and star-import shadowing is gone.
- 16 ported tests green now, 24 once the dependent cards land.

## 9. Verification
VERIFY-std with `<op>=range`, plus:
```bash
uv run pytest -q tests/nettests/test_range.py -rs
uv run python -c "from flpit import flp; print(flp.range(3, 4).to_list())"   # [3, 4, 5, 6]
uv run python -c "from flpit import flp; flp.range(1, -1)"                   # ArgumentOutOfRangeError ... 'count'
```

## 10. Definition of Done
DoD-std, plus: board README open question 4 marked resolved (keep name, drop from `__all__`); luna test updated; CHANGELOG "Changed" entry for negative counts.

## 11. Risks / open questions
- Raising on negative `count` is a behaviour change (previously `[]`); low risk, aligned with .NET.
- Removing `range` from `flp.__all__` affects only star imports; if a docs generator lists `__all__`, it must read the registry instead (F06).
