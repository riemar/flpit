---
id: M14
title: zip_longest
status: todo
priority: 075
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (Enumerable.Zip stops at the shortest; see N08)
  morelinq: ZipLongest.cs, ZipImpl.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; ZipLongestTest.cs has 3 [Test]/[TestCase] methods, one data-driven)
pr:
---

# M14: `zip_longest`

## 1. Goal
`zip_longest` zips sequences until the **longest** is exhausted, filling the gaps. It is `itertools.zip_longest` in fluent form, the counterpart to `zip` (shortest) and `equi_zip` (M15, equal lengths). Delivering it as a method keeps pipelines flat and gives it the same `result_selector` shape as `zip`.

## 2. Scope
**In:** `zip_longest(*others, fillvalue=None, result_selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`), 1 to 3 typed `others` plus an untyped variadic fallback.
**Out:** per-sequence fill values (MoreLINQ uses `default(T)` per type; Python has one `fillvalue`, like `itertools`); `ZipShortest` (that is the existing `zip`).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `ZipLongest(second, Func<T1?, T2?, TResult>)` | `zip_longest(second, result_selector=f)` |
| `ZipLongest(second, third, Func<T1?, T2?, T3?, TResult>)` | `zip_longest(second, third, result_selector=f)` |
| `ZipLongest(second, third, fourth, Func<...>)` | `zip_longest(second, third, fourth, result_selector=f)` |
| (none) | no selector → tuples; `fillvalue=` replaces `default(T)`; more than 3 others accepted (`tuple[Any, ...]`) |

`result_selector` is keyword-only because `others` is variadic (consistent with M15/M16 and with the variadic shape N08 should adopt for 3-way `zip`).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def zip_longest(self, second: Iterable[T2], /) -> FlpIt[tuple[TItem | None, T2 | None]]: ...
@overload
def zip_longest(self, second: Iterable[T2], /, *, fillvalue: TFill) -> FlpIt[tuple[TItem | TFill, T2 | TFill]]: ...
@overload
def zip_longest(self, second: Iterable[T2], /, *, fillvalue: TFill = ...,
                result_selector: Callable[[TItem | TFill, T2 | TFill], TResult]) -> FlpIt[TResult]: ...
# same three shapes for (second, third) and (second, third, fourth)
@overload
def zip_longest(self, *others: Iterable[Any], fillvalue: Any = None,
                result_selector: Callable[..., TResult]) -> FlpIt[TResult]: ...
@overload
def zip_longest(self, *others: Iterable[Any], fillvalue: Any = None) -> FlpIt[tuple[Any, ...]]: ...
```
(Without `fillvalue`, the selector overloads use `None` in place of `TFill`; the PR may collapse the fill/no-fill pairs once pyrefly supports PEP 696 TypeVar defaults on 3.12.) New TypeVars `T2`, `T3`, `T4`, `TFill` (shared with M15, M16, N08).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: stops when every sequence is exhausted.
- Each round calls `next` on every not-yet-exhausted iterator in argument order; an exhausted iterator is never called again (MoreLINQ disposes and nulls it; CPython's `zip_longest` drops it). Exhausted positions get `fillvalue`.
- Ends when all are exhausted; the round that discovers the last exhaustion yields nothing. All empty → empty.
- Validation (eager): at least one other, else `TypeError("zip_longest() requires at least one other sequence")` (MoreLINQ minimum is two sequences); `None` in `others` → `ArgumentNoneError("others")`; `result_selector=None` → `ArgumentNoneError("result_selector")`.
- `fillvalue` can be any object, including a callable or a mutable object (shared, not copied).
- Exceptions from any iterator or the selector propagate at enumeration.
- Re-enumeration re-iterates all sequences.

### 3.3 Implementation sketch
```python
def zip_longest(self, *others, fillvalue=None, result_selector=_SENTINEL):
    _require_others(others, "zip_longest")                 # shared with M15/M16
    if result_selector is not _SENTINEL:
        _require_callable(result_selector, "result_selector")
    src = self._source()
    def _generator():
        rows = itertools.zip_longest(src, *others, fillvalue=fillvalue)
        return rows if result_selector is _SENTINEL else starmap(result_selector, rows)
    return FlpIt(_FactoryIterable(_generator))
```
- Fully C-level; O(total) time, O(k) memory.
- **FlpList fast path**: none.
- `iter()` timing: `itertools.zip_longest` calls `iter()` on all inputs when the generator body starts (first `next`), MoreLINQ calls `GetEnumerator` on all inputs at the same point. Equivalent.

### 3.4 Registry entry
```toml
[operators.zip_longest]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.ZipLongest"
python_equivalent = "itertools.zip_longest(a, b, fillvalue=x)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `ZipLongestTest.cs` (3 methods; one data-driven over shorter/longer/equal pairs) as checklist:
  - covered: data-driven value matrix, laziness.
  - `OTHER` (no `IDisposable`): "dispose sequences eagerly" and "disposes inner sequences when GetEnumerator throws". The own test instead asserts an exhausted iterator receives no further `next` calls, which is the observable half of "dispose eagerly".
  - Target: 100 % of applicable behaviours.
- **Own unit tests** (`tests/unit/morelinq/test_zip_longest.py`, both `flp_type`s):
  - `[1, 2, 3].zip_longest("ab")` → `[(1, 'a'), (2, 'b'), (3, None)]`; `fillvalue='-'`; first shorter, second shorter, equal, both empty.
  - 3 and 4 sequences; 5 sequences through the variadic fallback.
  - `result_selector` called once per row with positional args.
  - No `next` after exhaustion (instrumented iterator); infinite sequence + `take`.
  - Validation: zero others, `None` other, `result_selector=None`, all raised at call time.
  - One-shot vs list re-enumeration.
- **Contracts:** auto via registry.
- **Typing** (`tests/typing/test_types_zip_longest.py`): `assert_type(flp.it([1]).zip_longest(["a"]), FlpIt[tuple[int | None, str | None]])`, `fillvalue=0` → `tuple[int, str | int]`, selector forms, 3/4-arity, fallback.

## 5. Differential harness
`difftest/specs/zip_longest.toml`, oracle calls the 2/3/4-sequence `MoreEnumerable.ZipLongest` overloads with a tuple-building selector (pinned `morelinq` NuGet). Domains: lengths from {0, 1, 3, 5} per sequence, int and string sources; on the Python side `fillvalue` is set to the oracle's `default(T)` per case (`0` for ints, `None` for strings; mixed int/string zips compare per-position defaults and are classified `EXPECTED_DIFFERENCE: one fillvalue vs default(T) per type` when they differ). Probes: values, `move_next` trace per sequence. Expected: MATCH otherwise.

## 6. Benchmarks
`tests/benchmarks/test_bench_zip_longest.py`, sizes 1e3 / 1e5, second sequence 90 % of the first:
- `native`: `list(itertools.zip_longest(a, b, fillvalue=0))`.
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(a).zip_longest(b, fillvalue=0).to_list()`; extra group with `result_selector=operator.add` vs `list(starmap(add, zip_longest(...)))`.
- Target ratio ≤ 1.5×.

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.ZipLongest(...)`; Args (`fillvalue`, `result_selector`); Raises; `Execution:` deferred, streaming, ends with the longest.
- Doctest:
  ```python
  >>> flp.it([1, 2, 3]).zip_longest("ab").to_list()
  [(1, 'a'), (2, 'b'), (3, None)]
  >>> flp.it([1, 2, 3]).zip_longest("ab", fillvalue="-").to_list()
  [(1, 'a'), (2, 'b'), (3, '-')]
  ```
- Translation map: `.ZipLongest(b, f)` / `itertools.zip_longest(a, b, fillvalue=x)` → `.zip_longest(b, fillvalue=x, result_selector=f)`.
- Deviations (README): single `fillvalue` (default `None`) instead of `default(T)` per sequence.

## 8. Expected outcomes
- `zip_longest` on all four types with 1 to 3 typed others; ~12 own tests; difftest 0 MISMATCH; benchmark ≈ native.

## 9. Verification
VERIFY-std with `<op>=zip_longest`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_zip_longest.py
uv run python -c "from flpit import flp; print(flp.it([1,2,3]).zip_longest('ab', fillvalue='-').to_list())"   # [(1, 'a'), (2, 'b'), (3, '-')]
```

## 10. Definition of Done
DoD-std, plus the shared `_require_others` helper and TypeVars `T2..T4`/`TFill` defined once (used by M15, M16).

## 11. Risks / open questions
- Cross-card: N08 (`zip` 3-way) should use the same variadic + keyword-only `result_selector` shape; today `zip(second, result_selector)` takes the selector positionally. Proposal: N08 keeps the positional 2-arg form for .NET parity and adds keyword support, so both spellings work.
- Overload count (~11) is high but mechanical; generate it in the PR with a small script if it gets error-prone.
