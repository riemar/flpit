---
id: M11
title: fill_forward / fill_backward
status: todo
priority: 072
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: FillForward.cs, FillBackward.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; FillForwardTest.cs 4 + FillBackwardTest.cs 3 [Test]/[TestCase])
pr:
---

# M11: `fill_forward` / `fill_backward`

## 1. Goal
Gap filling for sparse data: carry the last known value forward (sensor readings, spreadsheet-style merged cells) or pull the next known value backward. Python users reach for pandas `ffill`/`bfill` or a hand-written loop; these two operators give the same on any iterable, lazily, without a dependency.

## 2. Scope
**In:** `fill_forward(predicate=..., fill_selector=...)` and `fill_backward(predicate=..., fill_selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`). Default "blank" test: `x is None`.
**Out:** limit on the number of filled elements per gap (pandas `limit=`; not in MoreLINQ); NaN-as-blank by default (use `predicate=math.isnan`-style callables).

**MoreLINQ overload mapping** (3 + 3)
| MoreLINQ | flpit |
|---|---|
| `FillForward()` / `FillBackward()` (blank = `null`) | `fill_forward()` / `fill_backward()` (blank = `is None`) |
| `FillForward(predicate)` / `FillBackward(predicate)` | `fill_forward(predicate)` / `fill_backward(predicate)` |
| `FillForward(predicate, fillSelector(blank, seed))` | `fill_forward(predicate, fill_selector)` |
| `FillBackward(predicate, fillSelector(blank, next))` | `fill_backward(predicate, fill_selector)` |
| (none) | `fill_*(fill_selector=f)` with the default predicate: Python superset, keyword use only |

## 3. Detailed design
### 3.1 Signatures
```python
def fill_forward(
    self,
    predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    fill_selector: Callable[[TItem, TItem], TItem] | _Sentinel = _SENTINEL,
) -> FlpIt[TItem]: ...
def fill_backward(
    self,
    predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    fill_selector: Callable[[TItem, TItem], TItem] | _Sentinel = _SENTINEL,
) -> FlpIt[TItem]: ...
```
Return type stays `FlpIt[TItem]` (MoreLINQ: `IEnumerable<T>`, selector returns `T`). Dropping `None` from the element type (`FlpIt[T | None]` → `FlpIt[T]`) is not expressible because leading (forward) or trailing (backward) blanks survive.

### 3.2 Semantics
- **fill_forward**: Kind: intermediate, deferred. Buffering: streaming (O(1): last non-blank). For each element: if `predicate(x)` is truthy and a non-blank was already seen → yield `fill_selector(x, last)` or `last`; if no non-blank seen yet → yield `x` unchanged (**leading blanks survive**, `fill_selector` not called); otherwise yield `x` and remember it.
- **fill_backward**: Buffering: partial (the current run of blanks). Blanks are buffered until the next non-blank `y`; then each buffered blank `b` is yielded as `fill_selector(b, y)` or `y`, followed by `y`. **Trailing blanks are yielded unchanged** at the end, `fill_selector` not called.
- `predicate` is called exactly once per element, in order; `fill_selector` once per filled element (backward: in buffer order, when the filler arrives).
- Validation (eager): `predicate=None` / `fill_selector=None` passed explicitly → `ArgumentNoneError`.
- The filler is the element itself, not a copy (mutable objects are shared, as in MoreLINQ).
- Empty source → empty. All blanks → unchanged.
- Exceptions: propagate at enumeration; for `fill_backward`, buffered blanks of an interrupted run are never yielded.
- Re-enumeration re-runs the source; the "last seen" state is per enumeration.

### 3.3 Implementation sketch
```python
def fill_forward(self, predicate=_SENTINEL, fill_selector=_SENTINEL):
    _validate_optional_callables(predicate=predicate, fill_selector=fill_selector)
    src = self._source()
    def _generator():
        missing = _MISSING
        last = missing
        if predicate is _SENTINEL and fill_selector is _SENTINEL:   # hot default path, no call per element
            for x in src:
                if x is None:
                    yield x if last is missing else last
                else:
                    last = x
                    yield x
            return
        is_blank = (lambda v: v is None) if predicate is _SENTINEL else predicate
        for x in src:
            if is_blank(x):
                yield x if last is missing else (last if fill_selector is _SENTINEL else fill_selector(x, last))
            else:
                last = x
                yield x
    return FlpIt(_FactoryIterable(_generator))
```
- `fill_backward`: same shape with `blanks: list`, `yield from` the filled buffer (`repeat(y, len(blanks))` on the default path), then `blanks.clear()`.
- O(n) time; memory O(1) forward, O(longest gap) backward. **FlpList fast path**: none.
- itertools alternative for forward (`accumulate(xs, lambda a, x: a if x is None else x)`) differs on leading blanks and is not faster with a Python lambda; not used.

### 3.4 Registry entries
```toml
[operators.fill_forward]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.FillForward"
python_equivalent = "loop carrying the last non-None value (pandas ffill)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut

[operators.fill_backward]
category = "projection"
kind = "intermediate"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.FillBackward"
python_equivalent = "loop buffering None runs until the next value (pandas bfill)"
since = "0.4.0"
```

## 4. Tests
- **Ported:** none (D7). Checklists: `FillForwardTest.cs` (4: laziness, fill, fill selector, null filler) and `FillBackwardTest.cs` (3: laziness, fill, fill selector), all applicable and covered. Target: 100 %.
- **Own unit tests** (`tests/unit/morelinq/test_fill_forward.py`, `test_fill_backward.py`, both `flp_type`s):
  - Defaults: `[None, 1, None, None, 2, None]` → forward `[None, 1, 1, 1, 2, 2]`, backward `[1, 1, 2, 2, 2, None]`.
  - Custom predicate (`x == 0`, `math.isnan`), fill selector receives `(blank, filler)` in that order; leading (forward) / trailing (backward) blanks never reach the selector.
  - Falsy non-blanks (`0`, `""`, `False`) are not treated as blank by default.
  - Callback counts: predicate n calls; selector exactly once per filled element.
  - Backward buffering: with a counting source, the first output after a blank run appears only once the filler is pulled; an exception inside a blank run drops the buffered blanks.
  - Explicit `None` callables raise at call time; one-shot vs list re-enumeration.
- **Contracts:** auto via registry (forward streaming, backward partial).
- **Typing:** `tests/typing/test_types_fill_forward.py` / `..._fill_backward.py`: `assert_type(flp.it([1, None]).fill_forward(), FlpIt[int | None])`.

## 5. Differential harness
`difftest/specs/fill_forward.toml`, `fill_backward.toml`; oracle calls the three overloads of each (pinned `morelinq` NuGet) over nullable sources (`int?[]`, `string[]`). Domains: empty, all null, leading/trailing/interior gaps, no gaps; predicates `is_null`, `eq(0)`, `throws_on(k)`; fill selectors `second` (returns filler), `concat`. Probes: values, predicate and selector call logs (trace), exception position. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_fill_forward.py` / `..._fill_backward.py`, sizes 1e3 / 1e5, ~30 % `None`:
- `native` forward: loop with `last` variable building a list; backward: reversed forward fill over a list (`list(reversed(ffill(reversed(data))))`), the idiom a reviewer would write for an in-memory list.
- `flpit-FlpIt` / `flpit-FlpList`: `fill_forward().to_list()` / `fill_backward().to_list()`.
- Target ratio ≤ 1.5× forward (streaming), ≤ 1.3× backward (partial).

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.FillForward/FillBackward`; Args (default blank = `is None`, selector argument order); `Execution:`; note on leading/trailing blanks.
- Doctest:
  ```python
  >>> flp.it([None, 1, None, None, 2, None]).fill_forward().to_list()
  [None, 1, 1, 1, 2, 2]
  >>> flp.it([None, 1, None, None, 2, None]).fill_backward().to_list()
  [1, 1, 2, 2, 2, None]
  >>> flp.it([1, None, None, 4]).fill_forward(fill_selector=lambda blank, last: last * 10).to_list()
  [1, 10, 10, 4]
  ```
- Translation map: `.FillForward()` / `Series.ffill()` → `.fill_forward()`; `.FillBackward()` / `Series.bfill()` → `.fill_backward()`.
- Deviations (README): blank test is `is None` (MoreLINQ `== null`); NaN is not blank by default.

## 8. Expected outcomes
- Both operators on all four types; ~16 own tests; two difftest specs 0 MISMATCH; benchmarks recorded.

## 9. Verification
VERIFY-std with `<op>=fill_forward` and `<op>=fill_backward`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_fill_forward.py tests/unit/morelinq/test_fill_backward.py
uv run python -c "from flpit import flp; print(flp.it([None,1,None,2]).fill_backward().to_list())"   # [1, 1, 2, 2]
```

## 10. Definition of Done
DoD-std for both operators (two registry entries, two specs, two benchmark files).

## 11. Risks / open questions
- Positional `fill_forward(None)` raises `ArgumentNoneError` instead of meaning "default predicate": intended (consistent with §3.1 conventions), called out in the docstring.
- pandas users may expect `limit=`; out of scope, could be a later keyword without breaking changes.
