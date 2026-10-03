---
id: L04
title: take_last
status: todo
priority: 015
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: TakeLastTests.cs @ dotnet/runtime main 6f1d9331 (6 [Fact]/[Theory]; theories expand to ~615 rows via SkipTakeData)
  morelinq: n/a (MoreLINQ's own TakeLast is superseded by the .NET operator, D16)
pr:
---

# L04: `take_last`

## 1. Goal
"The last n lines / samples" is a common request that today forces users out of the pipeline (`list(xs)[-n:]`, which also has the `n == 0` slicing trap). `TakeLast(n)` gives a bounded-memory tail on any iterable. This card also lands the private `_indexable()` helper that the following cards (L05 `skip_last`, L08 `last_or_default`, L10 `element_at`, L11 `reverse`) reuse for their `Sequence` fast paths.

## 2. Scope
**In:** `take_last(count)` on `_LinqOps`; a `Sequence` fast path for plain `list`/`tuple`/`range`/`str` sources and for `FlpList`; the shared `_indexable()` helper.
**Out:** `skip_last` (L05); `Take(Range)` with from-end bounds (N09).

## 3. Detailed design
### 3.1 Signatures
```python
def take_last(self, count: int) -> FlpIt[TItem]: ...
```
.NET mapping: `TakeLast(int count)` → `take_last(count)` (single overload).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (a ring buffer of at most `count` elements). Short-circuit: none; the whole source is enumerated on the **first** `next()` (matches `EvaluationBehavior`: nothing happens before the first `MoveNext`, everything happens during it).
- `count <= 0` → empty; the source is **never** iterated (upstream: "TakeLast can tell straightaway that it can return a sequence with no elements").
- `count >= len(source)` → the whole source.
- Validation (eager): `operator.index(count)`; `None` → `ArgumentNoneError("count")`; `1.5` → `TypeError`. Huge counts (`2**31 - 1`, `2**100`) are valid.
- Mutation before enumeration is observed (upstream `List_ChangesAfterTakeLast_ChangesReflectedInResults`): the tail is computed when enumeration starts, not when the query is built.
- Re-enumeration recomputes the tail. One-shot sources stay one-shot.
- Source exceptions propagate from the first `next()`.

### 3.3 Implementation sketch
```python
def _indexable(self) -> Sequence[TItem] | None:          # private, shared with L05/L08/L10/L11
    """Underlying random-access source, or None.
    Only for types that do not override __iter__ (FlpIt, FlpList, Grouping; never OrderedIt)."""
    src = self._source()                                   # F05 accessor; FlpList -> its internal list
    return src if type(src) in _INDEXABLE_TYPES else None  # (list, tuple, range, str)

def take_last(self, count):
    count = _require_index(count, "count")
    if count <= 0:
        return FlpIt(())                                   # L13 may swap in the shared empty singleton
    seq = self._indexable()
    if seq is not None:
        def _generator():
            n = len(seq)                                   # read at enumeration time
            return iter(seq[n - count:] if count < n else seq)
    else:
        def _generator():
            return iter(deque(self, maxlen=count))         # C-level ring buffer
    return FlpIt(_FactoryIterable(_generator))
```
- Generic path: O(n) time, O(min(n, count)) memory; `deque(maxlen=...)` does not preallocate, so `count = 2**31 - 1` is safe. `deque` rejects `maxlen > sys.maxsize`, so counts above `sys.maxsize` take the "whole source" path (`list(self)`), which is equivalent.
- Sequence path: O(count) time and memory (one slice copy), no scan of the head. Equivalence: lists, tuples, ranges and strings have no side effects on iteration, the slice is taken at enumeration start (same moment the generic path drains the source), and `n - count` is guarded so the `xs[-0:]` trap cannot occur. Tests run both a `list` source and the `non_collection` fixture.
- `range[...]` slicing returns a `range` (O(1)); `str` slicing returns a `str` whose iteration yields the same characters.

### 3.4 Registry entry
```toml
[operators.take_last]
category = "partitioning"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.TakeLast"
python_equivalent = "collections.deque(xs, maxlen=n)  # xs[-n:] only when n > 0"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_take_last.py` from `TakeLastTests.cs`:
  - `TakeLast` theory: 10 source sizes × 30 counts (`SkipTakeData.EnumerableData`, counts include ±1..±500, `±int.MaxValue`, `0`, `int.MinValue`) over `flp_type` and the `non_collection` fixture (stand-in for `CreateSources`). The `FirstOrDefault`/`LastOrDefault`/`ElementAt` sub-asserts are ported with the operators available at merge time (`first()`/`last()` on non-empty results, existing `element_at(i)`). `ElementAtOrDefault(-1)` is dropped with a `NO_INDEX_RANGE_TYPE` comment (in flpit `-1` means "last", see L10). `ElementAtOrDefault(Count())` is added by L10.
  - `EvaluationBehavior` (15 rows): ported with a counting iterator; the `Dispose` bit-flag asserts are skipped as `OTHER` (Python iterators are not disposed by consumers; see `take` docstring).
  - `RunOnce` (300 rows): ported with the `run_once` fixture.
  - `SkipLastThrowsOnNull` (sic, upstream name) → `flp_type(None)` raises `SourceNoneError`.
  - `List_ChangesAfterTakeLast_ChangesReflectedInResults`: ported for `flp.it(list)` and for `FlpList` (mutated via slice assignment `lst[0:2] = []`).
  - `List_Skip_ChangesAfterTakeLast_ChangesReflectedInResults`: needs `skip` (L01, merged earlier).
  - Target: 100 % of methods ported; only the dispose sub-asserts are skipped.
- **Own unit tests** (`tests/unit/test_take_last.py`):
  - `take_last(0)` and `take_last(-3)` never call `iter()` on the source (`NoIterList` helper).
  - Python slicing trap: `flp.lst([1, 2, 3]).take_last(0)` is empty (not the whole list).
  - Generic path pulls every element exactly once, all on the first `next()`.
  - `range` and `str` sources; `None` elements; `count > sys.maxsize`.
  - `order_by(...).take_last(2)` returns the two largest keys in stable order (OrderedIt uses the generic path).
- **Contracts** (auto): deferral, one-shot, FlpList not mutated; buffering `partial` declared.
- **Typing**: `assert_type(flp.it(range(3)).take_last(2), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/take_last.toml`: `count ∈ {int.MinValue, -1, 0, 1, 2, len-1, len, len+1, int.MaxValue}`, sources empty, singleton, ints with duplicates, strings, `None`-containing; probe `result` and `elements_pulled_before_first_yield` (n for count > 0, 0 for count ≤ 0). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_take_last.py`, sizes 1e3 and 1e5, `k = 10` and `k = size // 2`:
- `native` (list): `data[-k:]`; `native` (iterator): `list(collections.deque(iter(data), maxlen=k))`
- `flpit-FlpIt` over `data` (fast path) and over `iter(data)` (generic path); `flpit-FlpList`: `flp.lst(data).take_last(k).to_list()`
- Target ratio ≤ 1.3× for both paths (buffering op).

## 7. Docs
- Docstring: `.NET: Enumerable.TakeLast(count)`; `count <= 0` → empty without touching the source; Execution: Deferred, Partial buffering (`count` elements), whole source read on first iteration.
- Doctest: `flp.it(range(6)).take_last(2).to_list()` gives `[4, 5]`; `flp.lst([1, 2, 3]).take_last(0).to_list()` gives `[]`.
- Translation map: `xs[-n:]` (n > 0) / `deque(xs, maxlen=n)` / `.TakeLast(n)` → `.take_last(n)`.

## 8. Expected outcomes
- `take_last` on all four types with typing; ~615 ported theory rows green (both `flp_type`s).
- `_indexable()` helper available for L05, L08, L10, L11.

## 9. Verification
VERIFY-std with `<op>=take_last`, plus:
```bash
uv run pytest -q tests/nettests/test_take_last.py -rs
uv run python -c "from flpit import flp; print(flp.it(range(6)).take_last(2).to_list(), flp.lst([1,2,3]).take_last(0).to_list())"   # [4, 5] []
```

## 10. Definition of Done
DoD-std, plus: `_indexable()` has its own unit test (returns `None` for `OrderedIt`, generators, `_FactoryIterable`; returns the backing list for `FlpList`).

## 11. Risks / open questions
- `_indexable()` must never return a source whose iteration has side effects; the exact-type check (`type(src) in ...`, not `isinstance`) keeps user subclasses of `list` with custom `__iter__` on the generic path.
- Cross-card: `ElementAtOrDefault(-1)` asserts in SkipTakeData-based tests (L04, L05, L11) cannot be ported under the L10 negative-index mapping; they are dropped, not skipped as whole tests.
