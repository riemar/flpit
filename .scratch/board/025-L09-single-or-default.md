---
id: L09
title: single / single_or_default
status: todo
priority: 025
effort: S
depends_on: [F05, F06, F07, F08, F09, L04, L07]
upstream:
  dotnet: SingleTests.cs (16 [Fact]/[Theory]) + SingleOrDefaultTests.cs (23 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331
  morelinq: n/a
pr:
---

# L09: `single` / `single_or_default`

## 1. Goal
Add `single_or_default` in the D5 shape and backfill the never-ported `SingleTests.cs` for the existing `single`. "Exactly one or nothing" lookups (`config.single_or_default(lambda c: c.name == key)`) are a daily idiom; the subtle part is that `SingleOrDefault` still **throws** on more than one element, which tests must pin.

## 2. Scope
**In:** `single()` / `single(predicate)` (rewrite, same public signature) and `single_or_default()` / `(predicate)` / `(default=...)` / `(predicate, default=...)` on `_LinqOps`; length fast path on list-like sources via `_indexable()` (L04); bug fixes below; ported `test_single.py` and `test_single_or_default.py`.
**Out:** nothing else; no legacy shim needed (new operator, `single` keeps its signature).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def single(self) -> TItem: ...
@overload
def single(self, predicate: Callable[[TItem], object]) -> TItem: ...

@overload
def single_or_default(self) -> TItem | None: ...
@overload
def single_or_default(self, predicate: Callable[[TItem], object]) -> TItem | None: ...
@overload
def single_or_default(self, *, default: TDefault) -> TItem | TDefault: ...
@overload
def single_or_default(self, predicate: Callable[[TItem], object], *, default: TDefault) -> TItem | TDefault: ...
```
| .NET | Python |
|---|---|
| `Single()` / `Single(predicate)` | `single()` / `single(predicate)` |
| `SingleOrDefault()` / `SingleOrDefault(TSource defaultValue)` | `single_or_default()` / `single_or_default(default=v)` |
| `SingleOrDefault(predicate)` / `SingleOrDefault(predicate, TSource defaultValue)` | `single_or_default(predicate)` / `single_or_default(predicate, default=v)` |

### 3.2 Semantics
- Kind: terminal. Short-circuit: without predicate, stops after the 2nd element; with a predicate, stops at the 2nd match, otherwise scans the whole source (it must prove there is no second match).
- `single`: empty → `EmptySequenceError`; no match → `NoMatchError`; >1 element → `MultipleElementsError`; >1 match → `MultipleMatchesError`.
- `single_or_default`: empty / no match → `default` (`None` unless given); **>1 element/match still raises** `MultipleElementsError` / `MultipleMatchesError` (upstream `ManyElementIList`, `ManyElementsPredicateTrueForFirstAndFifth*`). Nothing is caught.
- Validation (eager): `predicate=None` → `ArgumentNoneError("predicate")`. Current bug: `single(None)` is routed through `where(None)`, so an empty source raises `NoMatchError` and a non-empty one `TypeError: 'NoneType' object is not callable`.
- List-like sources without predicate decide by `len()` without reading a second element (.NET does the same for `IList<T>` via `Count`); results and exceptions are identical.
- `None` elements are values; `single_or_default()` returning `None` is ambiguous by design (docs suggest a private sentinel default).

### 3.3 Implementation sketch
```python
def _single_or_missing(self, predicate):              # shared by single / single_or_default
    if predicate is _SENTINEL:
        seq = self._indexable()
        if seq is not None:
            n = len(seq)
            if n > 1:
                raise MultipleElementsError()
            return seq[0] if n else _MISSING
        it, too_many = iter(self), MultipleElementsError
    else:
        _require_not_none(predicate, "predicate")
        it, too_many = filter(predicate, self), MultipleMatchesError
    first = next(it, _MISSING)
    if first is not _MISSING and next(it, _MISSING) is not _MISSING:
        raise too_many()
    return first
```
- O(n) worst case, O(1) memory; `filter` keeps predicate calls at exactly one per pulled element. Replaces the `where()`-based version (one generator layer less).
- FlpList: covered by `_indexable()`; the delegating copy is removed.

### 3.4 Registry entry
```toml
[operators.single]
category = "element"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.Single"
python_equivalent = "(x,) = xs"
since = "0.1.0"

[operators.single_or_default]
category = "element"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.SingleOrDefault"
python_equivalent = "(x,) = xs  # with empty -> default handled manually"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_single.py` from `SingleTests.cs` (16, backfill): `CreateSources` → `flp_type` × {`list`, `non_collection`}; `NullSource` → `SourceNoneError`; `ThrowsOnNullPredicate` → `ArgumentNoneError`. Target 100 %.
- **Ported** `tests/nettests/test_single_or_default.py` from `SingleOrDefaultTests.cs` (23): `default(int)` → `is None` (`# NO_VALUE_TYPES`), `SingleOrDefault(v)` → `single_or_default(default=v)`. Target 100 %.
- **Own unit tests** (`tests/unit/test_single.py`):
  - Pull counts: without predicate on a generator, exactly 2 elements are pulled when there are ≥ 2; with a predicate, pulling stops right after the 2nd match.
  - Fast-path equivalence: for sources of length 0, 1, 2, 5, `flp.lst(xs).single()` / `single_or_default()` give the same result or exception as the `non_collection` path.
  - `single_or_default` raises on two elements/matches; returns `default` on empty/no match.
  - Eager `ArgumentNoneError` for both operators on an empty source.
  - Existing luna regressions (`test_single_uses_none_to_mean_no_predicate`, falsy predicate) keep passing.
- **Contracts** (auto): terminal, short-circuit probe (stops after the 2nd match), FlpList not mutated.
- **Typing**: `assert_type(xs.single(), int)`, `assert_type(xs.single_or_default(), int | None)`, `assert_type(xs.single_or_default(default=0), int)`.

## 5. Differential harness
`difftest/specs/single.toml`, `single_or_default.toml`: oracle sources `int?`/`string`; sources empty, singleton, two equal elements, many with 0/1/2+ matches; probes `result` or exception kind (`EmptySequence`, `NoMatch`, `MultipleElements`, `MultipleMatches` mapped to the .NET `InvalidOperationException` messages), `elements_pulled` on non-collection sources. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_single.py`, sizes 1e3 / 1e5, predicate matching exactly one element at `size // 2` (full scan):
- `native`: `it = filter(pred, data); x = next(it); assert next(it, None) is None`
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(data).single(pred)`, `.single_or_default(pred)`
- Target ratio ≤ 1.5×.

## 7. Docs
- Docstrings: `.NET: Enumerable.Single / SingleOrDefault`; "`single_or_default` still raises on more than one element"; D5 `default`; Execution: Terminal, short-circuits at the second element/match.
- Doctests: `flp.it([1, 2, 3]).single(lambda x: x > 2)` gives `3`; `flp.it([5]).single_or_default(default=0)` gives `5`; `print(flp.it([]).single_or_default())` prints `None`.
- Translation map: `(x,) = xs` / `.Single()` → `.single()`; `.SingleOrDefault(p, d)` → `.single_or_default(p, default=d)`.

## 8. Expected outcomes
- `single_or_default` on all four types; 39 newly ported .NET tests green; lazy-`None`-predicate bug fixed.

## 9. Verification
VERIFY-std with `<op>=single` and `<op>=single_or_default`, plus:
```bash
uv run pytest -q tests/nettests/test_single.py tests/nettests/test_single_or_default.py -rs
uv run python -c "from flpit import flp; print(flp.it([5]).single_or_default(default=0), flp.it([]).single_or_default(default=0))"   # 5 0
uv run python -c "from flpit import flp; flp.it([1, 2]).single_or_default()"   # raises MultipleElementsError
```

## 10. Definition of Done
DoD-std, plus a README note in the `*_or_default` family docs that "or default" covers only the empty / no-match case.

## 11. Risks / open questions
- None significant. `single` keeps its public signature, so no deprecation is required.
