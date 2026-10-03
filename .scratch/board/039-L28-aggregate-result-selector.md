---
id: L28
title: aggregate result-selector overload + backfill
status: todo
priority: 039
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: AggregateTests.cs @ dotnet/runtime main 6f1d9331 (21 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L28: `aggregate` result-selector overload + backfill

## 1. Goal
`aggregate` lacks the third .NET overload `Aggregate(seed, func, resultSelector)`, which finishes a fold with a projection (e.g. accumulate `(sum, count)` and return the mean) without leaving the pipeline. The operator also has no ported tests and validates `func` only by accident. Small card that completes `aggregate` and pins its behaviour.

## 2. Scope
**In:** `aggregate(func, seed, result_selector)` overload; eager validation; switch to C-level `functools.reduce`; port of `AggregateTests.cs`.
**Out:** `aggregate_by` (N03); MoreLINQ `Aggregate` with multiple accumulators and `Fold` (M31).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def aggregate(self, func: Callable[[TItem, TItem], TItem]) -> TItem: ...
@overload
def aggregate(self, func: Callable[[TAccumulate, TItem], TAccumulate], seed: TAccumulate) -> TAccumulate: ...
@overload
def aggregate(self, func: Callable[[TAccumulate, TItem], TAccumulate], seed: TAccumulate,
              result_selector: Callable[[TAccumulate], TResult]) -> TResult: ...
```
`.NET` overload map: `Aggregate(func)` → `aggregate(func)`; `Aggregate(seed, func)` → `aggregate(func, seed)`; `Aggregate(seed, func, resultSelector)` → `aggregate(func, seed, result_selector)`. The Python argument order (`func` first) is the existing public API and matches `functools.reduce(function, iterable, initial)`; it is kept and documented in the translation map rather than broken.

### 3.2 Semantics
- Kind: terminal. Buffering: streaming (O(1) memory beyond the accumulator). Short-circuit: none.
- Validation (eager, before touching the source): `func is None` → `ArgumentNoneError("func")`; explicit `result_selector=None` → `ArgumentNoneError("result_selector")`; `result_selector` without `seed` is impossible positionally and rejected for keywords with `TypeError` (no such .NET overload). **Bug fixes**: today `aggregate(None, 5)` on an empty source returns `5`, and `aggregate(None)` on an empty source raises `EmptySequenceError` instead of an argument error (.NET checks `func` first).
- No seed: empty source → `EmptySequenceError`; one element → that element, `func` never called.
- With seed: `None` is a valid seed (the `_SENTINEL` default distinguishes "no seed"); empty source → `seed` (then `result_selector(seed)`).
- `result_selector` is called exactly once, after the fold, also for an empty source (`NoElementsSeedResultSeletor`: `2 + 5.0 == 7.0`).
- Exceptions from `func`/`result_selector` propagate unchanged (no relabelling of user `ValueError`, existing regression tests).

### 3.3 Implementation sketch
```python
def aggregate(self, func, seed=_SENTINEL, result_selector=_SENTINEL):
    _require_callable(func, "func")
    if result_selector is not _SENTINEL:
        if seed is _SENTINEL: raise TypeError("result_selector requires seed")
        _require_callable(result_selector, "result_selector")
    if seed is _SENTINEL:
        it = iter(self)
        first = next(it, _MISSING)
        if first is _MISSING: raise EmptySequenceError()
        return reduce(func, it, first)
    acc = reduce(func, self, seed)
    return acc if result_selector is _SENTINEL else result_selector(acc)
```
- `functools.reduce` keeps the loop in C: O(n) time, O(1) memory.
- **FlpList fast path**: none; the `FlpList.aggregate` delegate disappears with the F05 mixin (today it forwards `seed=seed` and would need a third argument).

### 3.4 Registry entry
```toml
[operators.aggregate]             # existing entry, updated
category = "aggregation"
kind = "terminal"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Aggregate"
python_equivalent = "functools.reduce(func, xs, seed)"
overloads = ["func", "func+seed", "func+seed+result_selector"]
```

## 4. Tests
- **Ported** `tests/nettests/test_aggregate.py` from `AggregateTests.cs` (21). `CreateSources` maps to the F08 source fixtures, `RunOnce` to the `run_once` fixture; `long`/`double` results become Python `int`/`float` (`NoElementsSeedResultSeletor` expects `7.0`). Argument order is translated (`Aggregate(seed, f)` → `aggregate(f, seed)`).
  - Expected skips: none (no overflow-dependent cases). Target: 100 % ported.
- **Own unit tests** (`tests/unit/test_aggregate.py`): `func=None` raises before the source is touched (spy) for all three forms, including empty sources; `seed=None` is a real seed; `result_selector` called once, also on empty input; single element without seed never calls `func`; one-shot source; keyword call `aggregate(func, seed=0, result_selector=str)`; `result_selector` without `seed` → `TypeError`.
- **Contracts**: auto (terminal).
- **Typing**: `assert_type(flp.it([1]).aggregate(lambda a, b: a + b), int)`; `assert_type(flp.it([1]).aggregate(lambda acc, x: acc + str(x), ""), str)`; `assert_type(flp.it([1]).aggregate(lambda a, x: a + x, 0, float), float)`.

## 5. Differential harness
`difftest/specs/aggregate.toml`: sources empty, singleton, `[5, 6, 2, -4]`, strings; funcs `+`, `*`, string concat; seeds `{none, 0, 2, ""}`; result selectors `{none, x + 5.0, str}`; probes `result`, `exception_type`, `func_calls`, `result_selector_calls`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_aggregate.py`, sizes 1e3 / 1e5:
- `native`: `functools.reduce(operator.add, data, 0)` and `str(functools.reduce(operator.add, data, 0))`
- `flpit-FlpIt` / `flpit-FlpList`: `.aggregate(operator.add, 0)` and `.aggregate(operator.add, 0, str)`.
- Target ratio ≤ 1.1× (same C loop; previously a Python loop).

## 7. Docs
- Docstring: `.NET: Enumerable.Aggregate` with the three overloads and the argument-order note; empty-source rules; `Execution: Terminal, streaming`.
- Doctest:
  ```python
  >>> flp.it([5, 6, 2, -4]).aggregate(lambda acc, x: acc * x, 2, lambda acc: acc + 5)
  -475
  ```
- Translation map: `functools.reduce(f, xs, seed)` / `.Aggregate(seed, f, r)` → `.aggregate(f, seed, r)`.

## 8. Expected outcomes
- All three `Aggregate` overloads available; argument validation eager; 21 ported tests green; faster `aggregate` via `reduce`.

## 9. Verification
VERIFY-std with `<op>=aggregate`, plus:
```bash
uv run pytest -q tests/nettests/test_aggregate.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([]).aggregate(lambda a, x: a * x, 2, lambda a: a + 5.0))"   # 7.0
uv run python -c "from flpit import flp; flp.it([]).aggregate(None, 5)"                                          # ArgumentNoneError
```

## 10. Definition of Done
DoD-std.

## 11. Risks / open questions
- The Python argument order differs from .NET (`func` before `seed`); swapping it now would break every existing caller. Kept; the docstring and skill translation map make the mapping explicit.
