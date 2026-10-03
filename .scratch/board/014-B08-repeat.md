---
id: B08
title: flp.repeat
status: todo
priority: 014
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: RepeatTests.cs @ dotnet/runtime main 6f1d9331 (30 [Fact]/[Theory] + 1 [ConditionalFact])
  morelinq: n/a
pr:
---

# B08: `flp.repeat` (backfill)

## 1. Goal
`flp.repeat(element, count)` is implemented as `FlpIt(element for _ in range(count))`, i.e. over a **generator expression**, so the query is **one-shot**: `q = flp.repeat(1, 3); list(q); list(q)` gives `[1, 1, 1]` then `[]`. .NET `Repeat` is re-enumerable (`SameResultsRepeatCalls*`, `Repeat_GetEnumeratorReturnUniqueInstances`). A negative `count` also yields nothing instead of throwing `ArgumentOutOfRangeException("count")`, and the generator is ~12× slower than `itertools.repeat` (3.73 ms vs 0.30 ms for 1e5). This card fixes all three and ports `RepeatTests.cs`.

## 2. Scope
**In:** `flp.repeat` in `src/flpit/flp.py`; re-iterable implementation over `itertools.repeat`; eager validation; port of `RepeatTests.cs`.
**Out:** an infinite `repeat(element)` without count (MoreLINQ `Repeat(x)`, Python `itertools.repeat(x)`; candidate for N12 `infinite_sequence` family, not a .NET `Repeat` overload); O(1) `count()`/`last()` (generic Sized/Sequence fast paths belong to N10/L08/L10).

## 3. Detailed design
### 3.1 Signatures
```python
def repeat(element: TItem, count: int) -> FlpIt[TItem]: ...
```
.NET `Repeat<TResult>(TResult element, int count)` maps 1:1.

### 3.2 Semantics
- Kind: factory (deferred). Buffering: none, O(1) memory. Re-iterable: every `iter()` starts a fresh `itertools.repeat` (independent iterators).
- The same object is yielded `count` times (identity preserved, `Repeat_ProduceSameObject`); `element` may be `None`.
- Validation (eager): `count = operator.index(count)` (`None` → `ArgumentNoneError("count")`, `2.5` → `TypeError`); `count < 0` → `ArgumentOutOfRangeError("count", count)` (message format owned by F05, parameter name as .NET). `count == 0` → empty.
- Large counts (`2**31 - 1` and beyond) are fine lazily; no Int32 limit (same deviation note as B07).
- Mutable `element`: all positions share one object (`flp.repeat([], 3)` yields the same list three times), exactly as .NET with reference types. Documented because it is a classic Python pitfall (`[[]] * 3`).

### 3.3 Implementation sketch
```python
def repeat(element: TItem, count: int) -> FlpIt[TItem]:
    count = _require_index(count, "count")
    if count < 0:
        raise ArgumentOutOfRangeError("count", count)
    return FlpIt(_FactoryIterable(partial(itertools.repeat, element, count)))
```
- `functools.partial` avoids a Python-level closure call per `iter()`; iteration is C-level `itertools.repeat`. O(count) time, O(1) memory.
- Considered: a private `_RepeatSequence(Sequence)` with `__len__`/`__getitem__` for O(1) `count`/`last`/`element_at`. Deferred to N10, which decides how `Sized` sources are exploited across operators; this card keeps the minimal re-iterable fix.

### 3.4 Registry entry
```toml
[operators.repeat]
category = "generation"
kind = "factory"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Repeat"
python_equivalent = "itertools.repeat(x, n)"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_repeat.py` from `RepeatTests.cs` (31 = 30 + 1 `[ConditionalFact]`):
  - Ported now (22): `Repeat_ProduceCorrectSequence`, `Repeat_ToArray_ProduceCorrectResult`, `Repeat_ToList_ProduceCorrectResult`, `Repeat_ProduceSameObject` (`is`), `Repeat_WorkWithNullElement`, `Repeat_ZeroCountLeadToEmptySequence`, `Repeat_ThrowExceptionOnNegativeCount`, `Repeat_NotEnumerateAfterEnd`, `Repeat_GetEnumeratorReturnUniqueInstances`, `SameResultsRepeatCallsIntQuery`, `SameResultsRepeatCallsStringQuery` (both fail today: one-shot), `CountOneSingleResult`, `RepeatArbitraryCorrectResults`, `RepeatNull`, `Take`, `TakeExcessive`, `First`, `Last`, `ElementAt`, `ElementAtExcessive` (`IndexError`), `Count`, plus `TakeCanOnlyBeOne` minus its `Skip` lines (full version once L01 lands).
  - Written now, active once other cards land (7, F08 `requires_op`): `Skip`, `SkipExcessive`, `SkipNone` (L01); `FirstOrDefault` (L07); `LastOrDefault` (L08); `ElementAtOrDefault`, `ElementAtOrDefaultExcessive` (L10, `default=0` for .NET `default(int)`).
  - Skips: `INTERNAL_OPTIMIZATION` 2 (`Repeat_EnumerableAndEnumeratorAreSame`; `ICollectionImplementationIsValid`, the `[ConditionalFact]` asserting `IList<T>` members).
  - Target: 29/31 ≈ 94 % once L01/L07/L08/L10 are merged; 22/31 ≈ 71 % at merge time otherwise.
- **Own unit tests** (`tests/unit/test_repeat.py`):
  - Re-enumeration regression: `list(q) == list(q) == [1, 1, 1]`; two interleaved iterators are independent.
  - `flp.repeat(1, -1)` raises (luna test asserting `[]` updated; CHANGELOG "Changed"); `flp.repeat(1, None)` / `flp.repeat(1, 2.5)` raise at call time.
  - `flp.repeat(x, 2**40).take(3)` is fast (lazy).
  - Shared mutable element identity documented by test.
- **Contracts** (auto, `kind = "factory"`).
- **Typing**: `assert_type(flp.repeat("a", 2), FlpIt[str])`; `flp.repeat(None, 2)` is `FlpIt[None]`.

## 5. Differential harness
`difftest/specs/repeat.toml`: `element ∈ {-3, 12, "SSS", "", null}`, `count ∈ {0, 1, 4, 99}`; invalid `count = -1` → `ArgumentOutOfRange`; probes: enumerate twice (re-enumeration), `.take(k)`, `.element_at(i)`, `.count()`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_repeat.py`, sizes 1e3 and 1e5:
- `native`: `list(itertools.repeat(x, n))`; `flpit`: `flp.repeat(x, n).to_list()`.
- Target ≤ 1.3× (today ≈ 12×; after the fix the remaining cost is the `FlpList` wrapper, B09).

## 7. Docs
- Docstring: `.NET: Enumerable.Repeat(element, count)`; re-iterable; same object repeated (mutable pitfall); eager validation. Doctest: `flp.repeat("x", 3).to_list()` → `['x', 'x', 'x']`.
- Translation map: `Enumerable.Repeat(x, n)` / `itertools.repeat(x, n)` / `[x] * n` → `flp.repeat(x, n)`.

## 8. Expected outcomes
- `flp.repeat` queries can be enumerated repeatedly, like every other re-iterable source.
- Negative counts fail fast; ~12× faster enumeration.
- 22 ported tests green now, 29 once dependencies land.

## 9. Verification
VERIFY-std with `<op>=repeat`, plus:
```bash
uv run pytest -q tests/nettests/test_repeat.py -rs
uv run python -c "from flpit import flp; q = flp.repeat(1, 3); print(list(q), list(q))"   # [1, 1, 1] [1, 1, 1]
uv run python -c "from flpit import flp; flp.repeat(1, -1)"                               # ArgumentOutOfRangeError ... 'count'
```

## 10. Definition of Done
DoD-std, plus: re-enumeration regression test; luna test updated; CHANGELOG "Fixed" (one-shot) and "Changed" (negative count) entries.

## 11. Risks / open questions
- Behaviour change for negative counts (previously `[]`); aligned with .NET and with B07.
- An infinite `repeat(x)` is a frequent Python need; proposed for N12 rather than overloading `count` with `None`.
