---
id: L12
title: default_if_empty
status: todo
priority: 030
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: DefaultIfEmptyTests.cs @ dotnet/runtime main 6f1d9331 (10 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L12: `default_if_empty`

## 1. Goal
`DefaultIfEmpty` guarantees at least one element: "show a placeholder row", "aggregate over an empty group without special-casing", and it is the building block for left joins written by hand (`group_join(...).select_many(lambda g: g.default_if_empty())`) until N04 lands. It is a tiny streaming operator with no Python one-liner for iterators.

## 2. Scope
**In:** `default_if_empty()` and `default_if_empty(default)` on `_LinqOps`; the DefaultIfEmpty section of `ContainsTests.FollowingVariousOperators` deferred by L06.
**Out:** FlpList override (no measurable gain over the generator, see 3.3).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def default_if_empty(self) -> FlpIt[TItem | None]: ...
@overload
def default_if_empty(self, default: TDefault) -> FlpIt[TItem | TDefault]: ...
```
| .NET | Python |
|---|---|
| `DefaultIfEmpty()` | `default_if_empty()` → yields `None` when empty |
| `DefaultIfEmpty(TSource defaultValue)` | `default_if_empty(default)` (positional or keyword) |

`default` is positional-or-keyword here (no predicate competes for the first position, unlike D5's `*_or_default`), and uses the same parameter name as D5 for consistency.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (one element of look-ahead to detect emptiness). Short-circuit: n/a.
- Non-empty source → elements unchanged. Empty source → exactly one element, `default` (`None` if omitted).
- The default object is yielded as-is, not copied: a mutable default (e.g. `[]`) is the same object on every enumeration. Documented.
- `.NET default(T)` for value types is `0`/`false`; flpit yields `None` (`NO_VALUE_TYPES`), so `xs.default_if_empty()` over ints gives `[None]`, not `[0]`. Pass `0` explicitly to get .NET's value-type behaviour. Listed under the existing value-type note in README deviations.
- No argument validation (any value, including `None`, is a valid default).
- Re-enumeration re-checks emptiness; one-shot sources stay one-shot (a second enumeration of an exhausted generator yields `[default]`, the same as .NET for an exhausted source).
- Source exceptions propagate from the `next()` that triggers them.

### 3.3 Implementation sketch
```python
def default_if_empty(self, default=None):
    def _generator():
        it = iter(self)
        first = next(it, _MISSING)
        if first is _MISSING:
            yield default
            return
        yield first
        yield from it
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(1) memory; after the first element it is a C-level `yield from`.
- **FlpList fast path:** `iter(data) if data else iter((default,))` saves one generator frame per enumeration only. Rejected unless the benchmark shows > 10 % gain for size 1e3; decision recorded in the PR.
- No collapse of `default_if_empty().default_if_empty()` (no observable benefit).

### 3.4 Registry entry
```toml
[operators.default_if_empty]
category = "element"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.DefaultIfEmpty"
python_equivalent = "xs or [default]  # lists only"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_default_if_empty.py` from `DefaultIfEmptyTests.cs` (10):
  - `DefaultIfEmpty` / `DefaultIfEmptyRunOnce` theories (7 rows): rows with `defaultValue == 0` also check the parameterless form; its expected `[0]` is rewritten to `[None]` (`# NO_VALUE_TYPES`), the explicit-default half is unchanged.
  - `NullableArray_Empty_*` (2), `SameResultsRepeatCalls*` (2), `NullSource_ThrowsArgumentNullException` (`SourceNoneError`): ported.
  - `First_Last_ElementAt`: ported; the `ElementAt(-1)` throws assert is dropped (`NO_INDEX_RANGE_TYPE`, `-1` is "last" in flpit, L10); `ElementAt(4)`/`ElementAt(1)` assert `IndexError`.
  - `ElementAtOrDefault_OutOfBounds_ReturnsTypeDefault` (regression dotnet/runtime#119834): ported; `element_at_or_default(1)` and `(2)` are `None` (not the `default_if_empty` value); the `(-1)` line is dropped (`NO_INDEX_RANGE_TYPE`). It guards any future fast path from leaking the default value into `element_at_or_default`.
  - `INTERNAL_OPTIMIZATION`: `ForcedToEnumeratorDoesntEnumerate`.
  - Target: 9 of 10 (90 %).
- **Extended** `tests/nettests/test_contains.py::FollowingVariousOperators` with the DefaultIfEmpty block (`DefaultIfEmpty().Contains(0)` rewritten as `default_if_empty().contains(None)`).
- **Own unit tests** (`tests/unit/test_default_if_empty.py`): exactly one element pulled before the first yield; mutable default identity across enumerations; `default_if_empty(None)` equals `default_if_empty()`; on `order_by(...)` the sort happens first; composition `where(lambda _: False).default_if_empty(0).single() == 0`.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated.
- **Typing**: `assert_type(flp.it([1]).default_if_empty(), FlpIt[int | None])`, `assert_type(flp.it([1]).default_if_empty(0), FlpIt[int])`, `assert_type(flp.it([1]).default_if_empty("x"), FlpIt[int | str])`.

## 5. Differential harness
`difftest/specs/default_if_empty.toml`: oracle element type `int?` so the parameterless form yields `null` on both sides; sources empty, singleton, many, `None`-containing; defaults `{omitted, 0, -10, None}`; probes `result`, `elements_pulled_before_first_yield` (1, or 1 exhausting `next()` for empty). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_default_if_empty.py`, sizes 1e3 / 1e5 (non-empty) plus an empty-source group:
- `native` (list): `data or [0]`; (iterator): hand-written generator with the same look-ahead (no stdlib idiom)
- `flpit-FlpIt` / `flpit-FlpList`: `.default_if_empty(0).to_list()`
- Target ratio ≤ 1.5× (streaming).

## 7. Docs
- Docstring: `.NET: Enumerable.DefaultIfEmpty([defaultValue])`; `None` instead of `default(T)`; default not copied; Execution: Deferred, Streaming.
- Doctests: `flp.it([]).default_if_empty(0).to_list()` gives `[0]`; `flp.it([1, 2]).default_if_empty(0).to_list()` gives `[1, 2]`; `flp.it([]).default_if_empty().to_list()` gives `[None]`.
- Translation map: `xs or [d]` / `.DefaultIfEmpty(d)` → `.default_if_empty(d)`.

## 8. Expected outcomes
- `default_if_empty` on all four types; 9 ported methods green; the Contains/DefaultIfEmpty block re-enabled.

## 9. Verification
VERIFY-std with `<op>=default_if_empty`, plus:
```bash
uv run pytest -q tests/nettests/test_default_if_empty.py tests/nettests/test_contains.py -rs
uv run python -c "from flpit import flp; print(flp.it([]).default_if_empty().to_list(), flp.it([]).default_if_empty(0).to_list())"   # [None] [0]
```

## 10. Definition of Done
DoD-std, plus the README value-type note mentions `default_if_empty()` yielding `None`.

## 11. Risks / open questions
- None significant.
