---
id: L27
title: min / max selector overloads + MinBy/MaxBy backfill
status: todo
priority: 043
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: MinTests.cs (73 [Fact]/[Theory]) + MaxTests.cs (80 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331; MinBy/MaxBy tests live in the same files
  morelinq: n/a
pr:
---

# L27: `min` / `max` selector overloads + `min_by`/`max_by` backfill

## 1. Goal
`Min(selector)`/`Max(selector)` ("largest order total", `orders.max(lambda o: o.total)`) are among the most common .NET calls and are missing; users fall back to `select(...).max()`. The existing `min`/`max`/`min_by`/`max_by` have no ported tests and several divergences from .NET found while reading the code (see 3.2). This card adds the selector overloads, defines the Python mapping of .NET's `None`/`NaN` rules consistently with `sum`/`average`, and ports both test files.

## 2. Scope
**In:** `min(selector=...)`, `max(selector=...)`; fixes to `min`, `max`, `min_by`, `max_by` on `_LinqOps`; removal of the `FlpList` `_guard_empty` overrides (they become wrong under the new rules); port of `MinTests.cs` and `MaxTests.cs`.
**Out:** comparer overloads (D3: `Min(IComparer)` → `min_by(key)`); MoreLINQ `Minima`/`Maxima` (M19).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def min(self) -> TItem: ...
@overload
def min(self, selector: Callable[[TItem], TResult]) -> TResult: ...
def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem: ...
# max / max_by: same shapes
```
`.NET` overload map: the 10 typed `Min(IEnumerable<int|long|float|double|decimal[?]>)` overloads and `Min<TSource>()` → `min()`; the 10 typed `Min(Func<TSource, number[?]>)` overloads and `Min<TSource,TResult>(Func<TSource,TResult>)` → `min(selector)`; `MinBy(keySelector)` → `min_by`; `Min(IComparer)` and `MinBy(..., IComparer)` omitted (D3; rewrite as `min_by(key)`). Same for `Max`/`MaxBy`.

### 3.2 Semantics
Python cannot tell `int` from `int?` (`NO_NULLABLE_DISTINCTION`), so one rule set is chosen:
- **`None` values are skipped** (elements for `min()`, projected values for `min(selector)`), as .NET does for nullable and reference types, and as flpit's `sum`/`average` already do.
- **Empty source → `EmptySequenceError`** (.NET non-nullable rule; keeps the existing, tested flpit contract and the `TItem` return type).
- **Non-empty but every value is `None` → returns `None`** (.NET nullable rule; `None` is a valid `TItem`/`TResult` in that case, so typing stays exact).
- Deviation recorded in README: .NET returns `null` for an empty nullable/reference sequence; flpit raises. Per D21 `average()` is aligned in this card: an empty source now raises `EmptySequenceError` (breaking; today it returns `None`), an all-`None` source returns `None`.
- **`NaN` total order (float values)**: `NaN` is smaller than every number, as in .NET. `min` returns the first `NaN` immediately (short-circuit, as .NET; `repeat(nan, 2**31 - 1).min()` is instant). `max` ignores `NaN` unless every non-`None` value is `NaN`. Today the result depends on position (`[1.0, nan, 0.5].min()` gives `0.5`, `.NET` gives `NaN`). The rule applies to `float` and subclasses; `Decimal('NaN')` comparisons raise `InvalidOperation`, which propagates.
- Ordering otherwise uses `<` / `>`; incomparable values raise `TypeError`. Ties keep the **first** occurrence (object identity matters for `min_by`/`max_by`).
- `min_by`/`max_by`: `None` keys are skipped; if all keys are `None`, the **first element** is returned (`MinBy_*AllKeysAreNull_ReturnsFirstElement`); empty → `EmptySequenceError`; `NaN` keys follow the same total order (smallest). Today `None` keys raise `TypeError`.
- Validation (eager, before touching the source): explicit `selector=None` / `key_selector=None` → `ArgumentNoneError`. **Bug fix**: today `min_by(None)` and `max_by(None)` silently behave like `min()`/`max()` (`builtins.min(key=None)`), on both `FlpIt` and `FlpList`.
- Kind: terminal. Buffering: streaming (O(1) memory). Short-circuit: `min`/`min(selector)` on the first `NaN`; otherwise full enumeration.

### 3.3 Implementation sketch
```python
def _extreme(values, is_max):                     # values: Iterator, None not yet filtered
    first = next(values, _MISSING)
    if first is _MISSING: raise EmptySequenceError()
    best = _MISSING
    for v in chain((first,), values):
        if v is None: continue
        if best is _MISSING: best = v
        elif is_max:
            if v > best or _is_nan(best): best = v          # NaN loses unless all NaN
        else:
            if v < best: best = v
            elif _is_nan(v): return v                        # NaN wins, short-circuit
        if not is_max and _is_nan(best): return best
    return None if best is _MISSING else best
# _is_nan(v) = isinstance(v, float) and v != v     (covers float subclasses such as numpy.float64)

def min(self, selector=_SENTINEL):
    if selector is None: raise ArgumentNoneError("selector")
    return _extreme(iter(self) if selector is _SENTINEL else map(selector, self), is_max=False)
```
`min_by`/`max_by` use the same loop over `(key, item)` pairs, tracking the first element for the all-`None`-keys case. O(n) time, O(1) memory. A Python-level loop replaces `builtins.min`, because correct `None` skipping and the `NaN` order cannot be expressed with a C-level `min` without a per-element key call.
- **FlpList fast path**: none; the existing `_guard_empty` overrides are deleted (they called `builtins.min` directly and would bypass the new rules).

### 3.4 Registry entry
```toml
[operators.min]                   # max analogous, short_circuit = false
category = "aggregation"
kind = "terminal"
buffering = "streaming"
short_circuit = true              # first NaN
dotnet = "Enumerable.Min"
python_equivalent = "min(x for x in xs if x is not None)"

[operators.min_by]                # max_by analogous
category = "aggregation"
kind = "terminal"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.MinBy"
python_equivalent = "min(xs, key=k)"
```

## 4. Tests
- **Ported** `tests/nettests/test_min.py` and `test_max.py` (73 + 80). Typed families (`Int`, `Long`, `Float`, `Double`, `Decimal`, `DateTime`, `String`, `Bool`) map to `int`, `float`, `Decimal`, `datetime`, `str`, `bool`; `Min_AllTypes` uses one representative per Python numeric type. Nullable families use `None`. Expected skips:
  - `NO_NULLABLE_DISTINCTION`: theory rows whose source is empty and expected `null` (`Min_NullableInt` etc., `Min_String` empty row), `MinBy_Generic_EmptyNullableSource_ReturnsNull`, `MinBy_Generic_EmptyReferenceSource_ReturnsNull`, `Max_NullableDateTime_EmptySourceWithSelector`, and the `Max`/`MaxBy` counterparts.
  - `COMPARER_NOT_SUPPORTED`: `Min/Max_Generic_*` and `MinBy/MaxBy_Generic_*` rows with a reversed **string** comparer (no key equivalent). Reversed int comparers become `min_by(lambda x: -x)`, constant comparers become `min_by(lambda x: 0)` (first element wins), keeping intent.
  - `OTHER` (no int/float overflow distinction): none expected; `float.MinValue` rows use `-3.4028234663852886e38`.
  - Ported thanks to the short-circuit: the `Repeat(NaN, int.MaxValue)` row of `Min_Float_TestData`/`Min_Double_TestData`.
  - Target: ≥ 90 % of test functions ported (row-level skips counted separately in the PR).
- **Own unit tests** (`tests/unit/test_min_max.py`): the three-way rule (empty raises, all-`None` returns `None`, mixed skips `None`) for `min`, `min(selector)`, `max`, `max(selector)`; `NaN` position independence; `min` stops at the first `NaN` (spy source); ties return the first object; `min_by` all-`None` keys returns the first element; `min_by(None)` raises before touching the source on both `FlpIt` and `FlpList`; incomparable types raise `TypeError`; user `ValueError` from a selector is not relabelled (existing regression tests keep passing).
- **Contracts**: auto (terminal, short-circuit for `min`).
- **Typing**: `assert_type(flp.it([1]).min(), int)`; `assert_type(flp.it(["a"]).max(len), int)`; `assert_type(flp.it([1, None]).min(), int | None)`; `assert_type(flp.lst(["a"]).min_by(len), str)`.

## 5. Differential harness
`difftest/specs/min.toml`, `max.toml`, `min_by.toml`, `max_by.toml`: domains ints, floats with `NaN`/`±inf` at start/middle/end, nullable ints with `None` mixes, strings, keys with `None`; probes `result`, `exception_type`, `elements_pulled` (NaN short-circuit). Empty nullable/reference sources are `EXPECTED_DIFFERENCE: empty raises in flpit (README deviation)`. Expected: all MATCH otherwise.

## 6. Benchmarks
`tests/benchmarks/test_bench_min_max.py`, sizes 1e3 / 1e5, ints and floats:
- `native`: `min(x for x in data if x is not None)` (the honest equivalent of the `None`-skipping semantics) and, for information only, `min(data)`; `max(map(f, data))` for the selector form; `min(data, key=k)` for `min_by`.
- `flpit-FlpIt` / `flpit-FlpList`: `.min()`, `.max(f)`, `.min_by(k)`.
- Target ratio ≤ 1.5× against the `None`-skipping baseline (terminal). The ratio against plain `min(data)` (~3×) is recorded in the PR as the cost of .NET-correct `None`/`NaN` handling.

## 7. Docs
- Docstrings: `.NET: Enumerable.Min/Max/MinBy/MaxBy` with the overload map; the three-way `None` rule; `NaN` order; ties; `Execution: Terminal, streaming, min short-circuits on NaN`.
- Doctests:
  ```python
  >>> flp.it([3, None, 1, 2]).min()
  1
  >>> flp.it(["pear", "fig"]).max(len)
  4
  >>> flp.it([float("nan"), 1.0]).max()
  1.0
  >>> flp.it(["pear", "fig"]).min_by(len)
  'fig'
  ```
- README deviations: "empty `min`/`max` raise even for nullable data"; translation map: `max(map(f, xs))` / `.Max(x => f(x))` → `.max(f)`.

## 8. Expected outcomes
- `min(selector)`/`max(selector)` available and typed; `None`/`NaN` handling matches .NET except the documented empty case.
- ~140 ported test functions green across both files; `min_by(None)` bug fixed.

## 9. Verification
VERIFY-std with `<op>=min_max` (benchmark file) and `<op>` in {min, max, min_by, max_by} for difftest, plus:
```bash
uv run pytest -q tests/nettests/test_min.py tests/nettests/test_max.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([1.0, float('nan'), 0.5]).min(), flp.it([None, None]).max())"   # nan None
uv run python -c "from flpit import flp; flp.lst([1]).min_by(None)"   # ArgumentNoneError
```

## 10. Definition of Done
DoD-std, plus the README deviation entry and removal of `_guard_empty` if no other caller remains.

## 11. Risks / open questions
- **Resolved (D21)**: `min`, `max` and `average` all raise `EmptySequenceError` on an empty source and return `None` for an all-`None` source. **In scope here**: change `average()` accordingly, update `tests/nettests/test_average.py` expectations that relied on `None`-for-empty (re-port the affected upstream asserts, which expect `InvalidOperationException` for non-nullable empty sources), and add a CHANGELOG `Changed` entry. `min_by(None)` is already rejected by F05 validation; this card keeps its regression test.
- Behaviour change: sequences containing `None` that used to raise `TypeError` now succeed; listed in `CHANGELOG.md` under "Changed".
