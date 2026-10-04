---
id: M01
title: pairwise
status: todo
priority: 062
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Pairwise.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7)
pr:
---

# M01: `pairwise`

## 1. Goal
Pairing each element with its successor (deltas, transitions, "previous vs current" comparisons) is one of the most requested sequence helpers. MoreLINQ ships it as `Pairwise(resultSelector)`, Python as `itertools.pairwise` (3.10+). It is the first MoreLINQ card: it proves the M-card path (own tests under `tests/unit/morelinq/`, MoreLINQ NuGet as difftest oracle) on a small operator with a C-level native equivalent.

## 2. Scope
**In:** `pairwise()` and `pairwise(result_selector)` on `_LinqOps`; own behavioural tests; MoreLINQ oracle op.
**Out:** `lag`/`lead` (M05/M06: offset and default value); windows of size > 2 (M02).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def pairwise(self) -> FlpIt[tuple[TItem, TItem]]: ...
@overload
def pairwise(self, result_selector: Callable[[TItem, TItem], TResult]) -> FlpIt[TResult]: ...
```
MoreLINQ has a single overload, `Pairwise(resultSelector)`. The selector-less form is a Python addition that yields `(previous, current)` tuples, matching `itertools.pairwise` and flpit's own `zip()` default. Decision: optional `result_selector` with the `_SENTINEL` default.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (holds the previous element). Short-circuit: `pairwise().first()` pulls exactly 2 elements.
- Output length `max(0, n - 1)`: empty and single-element sources yield nothing.
- `result_selector(previous, current)` is called exactly `n - 1` times, lazily, once per yielded item.
- Validation (eager): explicit `result_selector=None` → `ArgumentNoneError("result_selector")`.
- `None` elements are ordinary values (`(None, 1)` is a valid pair).
- Re-enumeration re-enumerates the source; one-shot stays one-shot.
- Selector exceptions propagate at the pair being produced; earlier results were already yielded.

### 3.3 Implementation sketch
```python
def pairwise(self, result_selector=_SENTINEL):
    if result_selector is None:
        raise ArgumentNoneError("result_selector")
    if result_selector is _SENTINEL:
        def _generator():
            return itertools.pairwise(self)
    else:
        def _generator():
            return itertools.starmap(result_selector, itertools.pairwise(self))
    return FlpIt(_FactoryIterable(_generator))
```
- Fully C-level iteration; O(n) time, O(1) memory. `itertools.pairwise` pulls two elements before its first yield, the same pull pattern as MoreLINQ.
- **FlpList fast path** (`zip(data, data[1:])`): rejected; it copies the list and is not faster than `pairwise`.

### 3.4 Registry entry
```toml
[operators.pairwise]
category = "windowing"
kind = "intermediate"
buffering = "partial"          # previous element only
short_circuit = false
morelinq = "MoreEnumerable.Pairwise"
python_equivalent = "itertools.pairwise(xs)"
since = "0.3.0"                # next minor at merge time
```

## 4. Tests
- **Own tests** `tests/unit/morelinq/test_pairwise.py` (written from scratch, D7):
  - Lengths 0, 1, 2, 5 → 0, 0, 1, 4 results; tuple form and selector form agree (`pairwise(f)` == `pairwise().select(lambda t: f(*t))`).
  - Laziness: construction does not iterate (`NoIterList`); selector not called before enumeration; selector call count `n - 1` (tracker).
  - Pull pattern: `.first()` pulls exactly 2 elements from a counting source; infinite source + `.take(3)` terminates.
  - `None` elements, strings (`"abcd"` → `ab, bc, cd`), `pairwise(None)` raises at call time.
  - One-shot generator: second enumeration empty; list source: repeatable.
  - Selector raising on the 3rd pair: first two results yielded, then the exception.
  - `flp.lst(data).pairwise()` does not mutate the `FlpList`; `order_by(k).pairwise()` pairs in sorted order.
- **Contracts** (auto) + `elements_pulled(first) == 2`.
- **Typing** `tests/typing/test_types_pairwise.py`: `assert_type(flp.it([1]).pairwise(), FlpIt[tuple[int, int]])`; `assert_type(flp.it([1]).pairwise(lambda a, b: b - a), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/pairwise.toml`, oracle = MoreLINQ NuGet `Pairwise`: sources {empty, singleton, two elements, ints, strings, nullable ints}; selectors `(a, b) => b - a`, `(a, b) => a + b` (strings: concatenation); the tuple form uses oracle selector `(a, b) => (a, b)` (`ValueTuple` serialised as a 2-array, compared to the Python tuple). Probe `elements_pulled` for `.first()` (2). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_pairwise.py`, sizes 1e3 and 1e5:
- `native`: `list(itertools.pairwise(data))`; selector case `[b - a for a, b in itertools.pairwise(data)]`.
- `flpit-FlpIt`, `flpit-FlpList`: `.pairwise().to_list()`, `.pairwise(lambda a, b: b - a).to_list()`.
- Target ≤ 1.5× (same C iterator; overhead is the factory call and `to_list`).

## 7. Docs
- Docstring: `MoreLINQ: MoreEnumerable.Pairwise(resultSelector)`; Python `itertools.pairwise`; deferred, pulls two elements before the first result; `n - 1` results. Doctests: `flp.it([1, 2, 3]).pairwise().to_list()` → `[(1, 2), (2, 3)]`; `flp.it("abcd").pairwise(lambda a, b: a + b).to_list()` → `['ab', 'bc', 'cd']`.
- README operator matrix row (generated, MoreLINQ section).
- Translation map: MoreLINQ `.Pairwise((a, b) => ...)` / .NET `xs.Zip(xs.Skip(1), f)` / `itertools.pairwise(xs)` / `zip(xs, xs[1:])` → `.pairwise(f)` / `.pairwise()`.

## 8. Expected outcomes
- `pairwise` available on all query types with precise typing for both forms.
- MoreLINQ oracle wired into the difftest job (first M-card), 0 MISMATCH.
- Benchmark ≈ native.

## 9. Verification
VERIFY-std with `<op>=pairwise`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_pairwise.py
uv run python -c "from flpit import flp; print(flp.it('abcd').pairwise(lambda a, b: a + b).to_list())"   # ['ab', 'bc', 'cd']
```
Manual: no file under `tests/` or `src/` contains MoreLINQ code or test text (D7 review checklist item).

## 10. Definition of Done
DoD-std (own tests instead of ported ones), plus: the difftest oracle project references the MoreLINQ NuGet package with a pinned version, and the license note (Apache-2.0, runtime oracle only) is in `difftest/README`.

## 11. Risks / open questions
- If F09's oracle project does not yet reference MoreLINQ, this card adds the package reference (pinned) and the license note.
- Name clash with `itertools.pairwise` is intentional (same meaning); no conflict with a builtin.
