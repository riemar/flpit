---
id: L16
title: select_indexed + SelectTests backfill
status: todo
priority: 027
effort: M
depends_on: [F05, F06, F07, F08, F09, L01, L08, L10, L15]
upstream:
  dotnet: SelectTests.cs @ dotnet/runtime main 6f1d9331 (90 [Fact]/[Theory], +2 [ConditionalFact])
  morelinq: n/a
pr:
---

# L16: `select_indexed` + SelectTests backfill

## 1. Goal
`select` is the second pillar of every pipeline and has no ported tests; like `where` it accepts `None` and fails only on enumeration. This card fixes validation, moves `select` onto C-level `map`, ports `SelectTests.cs` (90 cases, many of them chains `Select().Skip()/Take()/ElementAt()/First()/Last()` that also harden those operators), and adds `Select((item, index) => ...)` as `select_indexed` (D4) using the `_indexed` helper from L15.

## 2. Scope
**In:** eager validation for `select`; `select_indexed(selector)` on `_LinqOps`; full port of `SelectTests.cs`.
**Out:** .NET's `IPartition`/`IList` select specialisations (`Select(...).Skip(n)` computed by index, `Count()` without running the selector on some paths). These are internal; observable callback counts are pinned by own tests instead.

## 3. Detailed design
### 3.1 Signatures
```python
def select(self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]: ...
def select_indexed(self, selector: Callable[[TItem, int], TResult]) -> FlpIt[TResult]: ...
```
`.NET` overload map: `Select(Func<T,TResult>)` → `select`; `Select(Func<T,int,TResult>)` → `select_indexed` (D4).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: n/a (1:1 projection; downstream short-circuits stop the selector).
- Validation (eager): `selector is None` → `ArgumentNoneError("selector")` (F05 fixes the `SelectorNoneError` message that names `keySelector`). **Bug fix**: today `select(None)` fails lazily.
- The selector runs exactly once per element **that is pulled**; `select(f).count()` runs `f` for every element (.NET guarantees this too, `SelectSideEffectsExecutedOnCount`). No flpit fast path may skip selector calls (e.g. `FlpList.select(f).count()` must not shortcut to `len`).
- Index semantics as in L15 (0-based over source elements, restarts per enumeration, no overflow).
- `None` elements and `None` results pass through unchanged.
- Exceptions from source or selector propagate at enumeration; the generator is then finished (shared deviation from L15).

### 3.3 Implementation sketch
```python
def select(self, selector):
    _require_callable(selector, "selector")
    return FlpIt(_FactoryIterable(lambda: map(selector, self)))

def select_indexed(self, selector):
    _require_callable(selector, "selector")
    return FlpIt(_FactoryIterable(lambda: starmap(selector, _indexed(self))))
```
- Both are fully C-level apart from the user callback: O(n) time, O(1) memory.
- **FlpList fast path**: none; `map` over the backing list is already optimal and `len`-based shortcuts would change selector call counts.
- `_FactoryIterable(lambda: map(...))` keeps re-iterability: every `iter()` builds a fresh `map` over a fresh source iterator.

### 3.4 Registry entry
```toml
[operators.select_indexed]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Select(Func<TSource,int,TResult>)"
python_equivalent = "itertools.starmap(f, zip(xs, itertools.count()))"
since = "0.3.0"
```
The existing `[operators.select]` entry gets `python_equivalent = "map(f, xs)"`.

## 4. Tests
- **Ported** `tests/nettests/test_select.py` from `SelectTests.cs` (90). Source-type variants map to `tuple`/`list`/`Sequence` wrapper/`Collection` wrapper/`non_collection` (F08). `.Order()` becomes `order_by(lambda x: x)`; `Skip`, `ElementAtOrDefault`, `LastOrDefault` use L01/L10/L08 (hence `depends_on`). Expected skips:
  - `OTHER` (no `IEnumerator.Current`): five `*_CurrentIsDefaultOfTAfterEnumeration`.
  - `OTHER` (no `Reset`): `Select_ResetCalledOnEnumerator_ThrowsException`.
  - `OTHER` (no mutation detection on `list`): `Select_SourceListGetsModifiedDuringIteration_ExceptionIsPropagated`.
  - `OTHER` (no `IDisposable` on list enumerators): `Select_SourceIsIList_EnumeratorDisposedOnComplete`, `..._OnExplicitDispose`.
  - Adapted: the four `*_IteratorCanBeUsedAfterExceptionIsCaught` assert `StopIteration` after the exception (generator semantics); `MoveNextAfterDispose` becomes `it.close(); next(it)` → `StopIteration`; `ForcedToEnumerator*` become `not isinstance(q, Iterator)`; `Select_SourceIsAnIList_*` use a read-only `Sequence` wrapper.
  - [ConditionalFact] (not counted): `Overflow` skipped `OTHER` (no int overflow); `EnumerateFromDifferentThread` ported with `ThreadPoolExecutor` (4 concurrent `to_list()` calls on one re-iterable query).
  - Target: ≥ 88 % ported.
- **Own unit tests** (`tests/unit/test_select.py`): `select(None)`/`select_indexed(None)` raise at call time on empty and one-shot sources; selector call count equals elements pulled for `select(f).first()`, `select(f).take(2).to_list()`, `FlpList.select(f).count()`; `select_indexed` index restarts on re-enumeration.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).select_indexed(lambda x, i: str(x + i)), FlpIt[str])`; `assert_type(flp.lst(["a"]).select(len), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/select.toml` (extend) and `select_indexed.toml`: sources empty, singleton, ints, strings with `None`; selectors `{identity, x*2, str, (x, i) -> x + i}`; compositions `select().skip(2)`, `select().take(3).count()`, `select().element_at(1)`; probe `selector_calls`. Expected: all MATCH (selector calls equal on both sides because .NET's `IPartition` paths still run the selector for yielded elements; any mismatch in `selector_calls` for `Skip` on `IList` sources is classified `EXPECTED_DIFFERENCE: .NET skips selector for skipped IList elements` with that reason).

## 6. Benchmarks
`tests/benchmarks/test_bench_select.py` and `test_bench_select_indexed.py`, sizes 1e3 / 1e5:
- `native`: `list(map(f, data))` / `list(starmap(f, zip(data, count())))`; `flpit-FlpIt`: `flp.it(data).select(f).to_list()`; `flpit-FlpList`: `flp.lst(data).select(f).to_list()`.
- Target ratio ≤ 1.5× (streaming); expected ~1.1× after the switch to `map`.

## 7. Docs
- `select_indexed` docstring: `.NET: Enumerable.Select(source, Func<TSource, int, TResult>)`; index rule; selector-call guarantee; `Execution: Deferred, streaming`.
- Doctest:
  ```python
  >>> flp.it("abc").select_indexed(lambda c, i: f"{i}:{c}").to_list()
  ['0:a', '1:b', '2:c']
  ```
- Translation map: `map(f, xs)` / `.Select(f)` → `.select(f)`; `[f(x, i) for i, x in enumerate(xs)]` / `.Select((x, i) => ...)` → `.select_indexed(f)`.

## 8. Expected outcomes
- `select(None)` raises eagerly; `select_indexed` available and typed.
- ~80 ported `SelectTests` green; `select` throughput improves (C-level `map`).

## 9. Verification
VERIFY-std with `<op>=select` and `<op>=select_indexed`, plus:
```bash
uv run pytest -q tests/nettests/test_select.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it('abc').select_indexed(lambda c, i: c * i).to_list())"   # ['', 'b', 'cc']
```

## 10. Definition of Done
DoD-std, plus an own test pinning "selector runs for every element on `count()`" for both `FlpIt` and `FlpList`.

## 11. Risks / open questions
- Ported tests that chain `skip`/`element_at_or_default`/`last_or_default` need L01/L08/L10; if this card is picked earlier, those cases are temporarily marked `pytest.skip("OTHER: needs L01")` and un-skipped by the later card (tracked in the PR).
