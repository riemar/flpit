---
id: N08
title: zip 3-way + ZipTests backfill
status: todo
priority: 052
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ZipTests.cs @ dotnet/runtime main 6f1d9331 (64 [Fact]/[Theory])
  morelinq: n/a (EquiZip / ZipLongest are M15 / M14)
pr:
---

# N08: `zip` 3-way overload + `ZipTests` backfill

## 1. Goal
`zip` exists but has no ported .NET tests, validates nothing eagerly, and lacks the .NET 6 three-sequence overload `Zip(second, third)`. This card completes the overload set, fixes the validation and per-element overhead found while reading the implementation, and ports all of `ZipTests.cs`, so `zip` gets the same level of verification as the newer operators.

## 2. Scope
**In:** `zip(second)`, `zip(second, third)` (new), `zip(second, result_selector)` on `_LinqOps`; eager validation; C-level implementation; ported `ZipTests.cs`.
**Out:** N-ary zip (> 3 sequences; not in .NET, use `select` on nested zips or Python's `zip`); `strict=` length checking (MoreLINQ `EquiZip`, M15); padding to the longest (`ZipLongest`, M14); a 3-way result-selector overload (not in .NET). Named-tuple results: **zip keeps plain tuples** (N01 decision).

### Current implementation issues (fixed in scope)
| Issue (linq.py today) | .NET behaviour | Fix |
|---|---|---|
| `zip(None)` fails lazily (`TypeError: 'NoneType' object is not iterable` on enumeration) | `ArgumentNullException("second")` at call | `ArgumentNoneError("second")` at call |
| `zip(xs, None)` treats `None` as a selector, fails lazily when called | `ArgumentNullException("resultSelector")` at call | eager `ArgumentNoneError` (see dispatch) |
| `result_selector is not _SENTINEL` tested per element inside the Python generator | n/a | dispatch once at call time; `zip`/`map` do the loop in C |
| `FlpList.zip` duplicate | n/a | removed by F05 (mixin) |

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def zip(self, second: Iterable[TSecond]) -> FlpIt[tuple[TItem, TSecond]]: ...
@overload
def zip(self, second: Iterable[TSecond], third: Iterable[TThird], /) -> FlpIt[tuple[TItem, TSecond, TThird]]: ...
@overload
def zip(
    self, second: Iterable[TSecond], result_selector: Callable[[TItem, TSecond], TResult]
) -> FlpIt[TResult]: ...

def zip(self, second, third_or_selector=_SENTINEL, *, result_selector=_SENTINEL): ...  # implementation
```
| .NET overload | flpit |
|---|---|
| `Zip(second)` → `(First, Second)` | `zip(second)` → `tuple[T, S]` |
| `Zip(second, third)` → `(First, Second, Third)` | `zip(second, third)` → `tuple[T, S, U]` |
| `Zip(second, resultSelector)` | `zip(second, result_selector)` (positional or keyword) |

- **Runtime dispatch** of the second positional argument (C# resolves this at compile time): an `Iterable` (has `__iter__`) is `third`; otherwise a callable is `result_selector`; otherwise `TypeError`. An object that is both iterable and callable is treated as `third` (documented). Passing a positional argument and `result_selector=` together → `TypeError`.
- `second` stays positional-or-keyword as today (`zip(second=xs)` keeps working). `third` is positional-only in the typed overload; the implementation parameter `third_or_selector` is private by convention (not documented, not in the overloads).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: stops at the **shortest** input.
- Validation (eager): `second` `None` → `ArgumentNoneError("second")`; positional `None` as second argument → `ArgumentNoneError("third")`; `result_selector=None` → `ArgumentNoneError("result_selector")`.
- Pull order per step (same as .NET `e1.MoveNext() && e2.MoveNext() && e3.MoveNext()` and Python `zip`): `self`, then `second`, then `third`; when one is exhausted the later ones are **not** advanced for that step. All iterators are obtained (`iter()`) at enumeration start, in argument order.
- `None` elements are passed through untouched (never truth-tested).
- Re-enumeration re-iterates every input; one-shot inputs stay one-shot.
- Exceptions from any input or the selector propagate at enumeration, after the pairs already yielded.
- Plain tuples, no `first`/`second` attribute names (N01 exception; `Zip2_TupleNames` skipped).

### 3.3 Implementation sketch
```python
def zip(self, second, third_or_selector=_SENTINEL, *, result_selector=_SENTINEL):
    _require_not_none(second, "second")
    src = self._source()
    if third_or_selector is not _SENTINEL:
        if result_selector is not _SENTINEL:
            raise TypeError("zip() got both a positional third/result_selector and result_selector=")
        _require_not_none(third_or_selector, "third")
        if isinstance(third_or_selector, Iterable):
            third = third_or_selector
            return FlpIt(_FactoryIterable(lambda: builtins.zip(src, second, third)))
        result_selector = third_or_selector
    if result_selector is _SENTINEL:
        return FlpIt(_FactoryIterable(lambda: builtins.zip(src, second)))
    _require_callable(result_selector, "result_selector")
    return FlpIt(_FactoryIterable(lambda: map(result_selector, src, second)))
```
- All three forms run in C (`zip`, multi-argument `map`), O(1) per step, O(1) memory.
- `builtins.zip` is spelled out for readability next to the `zip` method (inside the method body plain `zip` already resolves to the builtin).
- **FlpList fast path**: none needed.
- N10 count provider: `min` of the inputs' cheap counts when all are known.

### 3.4 Registry entry
```toml
[operators.zip]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = true
origin = "dotnet"
dotnet = "Enumerable.Zip"
python_equivalent = "zip(xs, ys[, zs]) / map(f, xs, ys)"
since = "0.1.0"
card = "N08"
notes = "3-way overload added in 0.4.0; plain tuples (no named fields); stops at shortest."
```

## 4. Tests
- **Ported** `tests/nettests/test_zip.py` from `ZipTests.cs` (64 cases):
  - Result-selector block (`FirstIsNull` … `RunOnce`), `Zip2_*` block and `Zip3_*` block ported 1:1 with `run_once` and `tests.helpers` throwing iterables (`ThrowsOnMatchEnumerable` becomes a generator raising on a given value).
  - `*ImplicitTypeParameters` / `*ExplicitTypeParameters` (6 tests): both collapse to the same Python call; kept for traceability.
  - `FirstIsNull` → `flp.it(None)` raises `SourceNoneError`; `SecondIsNull`, `FuncIsNull`, `Zip3_ThirdIsNull` assert the eager `ArgumentNoneError` param names.
  - `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(query, Iterator)`.
  - `Zip2_NestedTuple`: ported (plain tuples compare equal).
  - `OTHER`: `Zip2_TupleNames` (`t.First` / `t.Second` names; zip yields plain tuples by decision N01).
  - Target: 63/64 (98 %).
- **Own unit tests** (`tests/unit/test_zip.py`): dispatch rules (iterable vs callable vs both, positional + keyword conflict); pull-order log with three counting generators of different lengths (shorter first input never advances the others past the end); eager errors without touching sources (`NoIterList`); string as `third` (iterable, not callable); existing `zip(second, result_selector=f)` keyword call still works.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).zip(["a"], [True]), FlpIt[tuple[int, str, bool]])`; 2-way and selector overloads unchanged.

## 5. Differential harness
`difftest/specs/zip.toml`: forms 2-way, 3-way, selector (`(a, b) => a + b` on ints); lengths `{0, 1, 3, 5}` for each input (all combinations); elements with nulls. Probes: values (tuples as arrays), `elements_pulled` per input (proves the left-to-right short-circuit), exception type for null arguments. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_zip.py`, sizes 1e3 and 1e5:
- `native`: `list(zip(a, b))`, `list(zip(a, b, c))`, `list(map(operator.add, a, b))`.
- `flpit-FlpIt` / `flpit-FlpList`: the three forms with `.to_list()`.
- Target ratio ≤ 1.3× (C-level loops; overhead is `FlpList` construction). Record the before/after for the selector form (per-element sentinel check removed).

## 7. Docs
- Docstring: "Combines elements at the same position from two or three sequences, stopping at the shortest."; `.NET: Enumerable.Zip`; Args with the dispatch rule; Raises; Execution (deferred, streaming, pull order). Example:
  ```python
  >>> flp.it([1, 2, 3]).zip("ab", [True, False, True]).to_list()
  [(1, 'a', True), (2, 'b', False)]
  >>> flp.it([1, 2]).zip([10, 20], lambda a, b: a + b).to_list()
  [11, 22]
  ```
- README matrix row; the "Named tuple results" section (N01) mentions the zip exception.
- Translation map: `zip(a, b, c)` / `.Zip(b, c)` → `.zip(b, c)`; `map(f, a, b)` / `.Zip(b, f)` → `.zip(b, f)`.

## 8. Expected outcomes
- 3-way `zip` available; argument errors are eager; selector form ~C speed.
- 63 ported .NET tests green (1 categorised skip); README "Migrated .NET Unit Tests" table gains `test_zip.py`.
- Benchmark recorded; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=zip`, plus:
```bash
uv run pytest -q tests/nettests/test_zip.py -rs          # 1 skip: Zip2_TupleNames
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3]).zip('ab', [True, False, True]).to_list())"
# [(1, 'a', True), (2, 'b', False)]
uv run python -c "from flpit import flp; flp.it([1]).zip(None)"   # ArgumentNoneError at call
```

## 10. Definition of Done
DoD-std, plus the CHANGELOG notes the behaviour change "zip validates arguments at call time" under `Changed`.

## 11. Risks / open questions
- Runtime dispatch is a Python necessity; an object that is both iterable and callable is rare but possible (documented, iterable wins). Alternative considered: keyword-only `third=`. Rejected because `zip(b, c)` mirrors both .NET and Python's `zip`.
- Positional `None` reported as `third` is a heuristic; a user meaning `result_selector=None` gets a slightly misleading name. Acceptable: both are errors either way.
