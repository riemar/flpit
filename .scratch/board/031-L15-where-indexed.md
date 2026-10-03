---
id: L15
title: where_indexed + WhereTests backfill
status: todo
priority: 031
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: WhereTests.cs @ dotnet/runtime main 6f1d9331 (92 [Fact]/[Theory], +1 [ConditionalFact] IndexOverflows)
  morelinq: n/a
pr:
---

# L15: `where_indexed` + WhereTests backfill

## 1. Goal
`where` is the most used operator in the library but has **no ported .NET tests** and validates its predicate lazily (`flp.it(xs).where(None)` builds fine and fails with `'NoneType' object is not callable` on first `next`). This card fixes validation, ports all of `WhereTests.cs` (the second largest LINQ test file), and adds the indexed overload `Where((item, index) => ...)` as `where_indexed` (D4). If L02/L03 have not landed it yet, this card also lands the **shared indexed helper** reused by `select_indexed` (L16), `select_many_indexed` (L17), `take_while_indexed` (L02) and `skip_while_indexed` (L03).

## 2. Scope
**In:** eager validation for `where`; new `where_indexed(predicate)` on `_LinqOps` (so `FlpIt`, `FlpList`, `OrderedIt`, `Grouping`, `Lookup`); private helper `_indexed(source)` in `src/flpit/core/_indexed.py`; full port of `WhereTests.cs`.
**Out:** `Where`/`Select` iterator fusion (`WhereSelectArrayIterator` etc.), which is a .NET-internal optimisation with no observable effect; `select_indexed` (L16).

## 3. Detailed design
### 3.1 Signatures
```python
def where(self, predicate: Callable[[TItem], object]) -> FlpIt[TItem]: ...
def where_indexed(self, predicate: Callable[[TItem, int], object]) -> FlpIt[TItem]: ...
```
`.NET` overload map: `Where(Func<T,bool>)` → `where`; `Where(Func<T,int,bool>)` → `where_indexed` (D4). The predicate return type is `object` because the result is tested for truthiness (see 3.2); the existing `Callable[[TItem], bool]` annotation stays accepted.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: none (pulls one source element per yielded or rejected element).
- Validation (eager, at call time): `predicate is None` → `ArgumentNoneError("predicate")` (F05; subclass of the existing `PredicateNoneError`). **Bug fix**: today `where(None)` fails lazily; `count(None)`/`first(None)`/`single(None)` inherit the fix because they route through `where`.
- Truthiness: the result of `predicate` is tested with `if`, not `is True` (Python idiom; .NET requires `bool`). `Falsy` objects from `tests/helpers.py` are rejected, as today. Documented in the docstring.
- Index: `0, 1, 2, ...` counts **source** elements (rejected ones included), as in .NET. Python ints never overflow, so .NET's `OverflowException` after `int.MaxValue` elements does not exist (README deviation "indexed callbacks never overflow", shared by all `*_indexed` ops).
- `None` elements are passed to the predicate like any other value.
- Re-enumeration: each `iter()` re-enumerates the source and restarts the index at 0. One-shot sources stay one-shot.
- Exceptions from the source or the predicate propagate at enumeration. After an exception the Python generator is finished (a later `next` raises `StopIteration`); .NET array-backed enumerators can continue. This is generic generator behaviour; see 4 and 11.

### 3.3 Implementation sketch
```python
# _indexed.py
from itertools import count
def _indexed(source: Iterable[T]) -> Iterator[tuple[T, int]]:
    return zip(source, count())          # (item, index) order == callback order

def where_indexed(self, predicate):
    _require_callable(predicate, "predicate")          # F05
    def _generator():
        for item, index in _indexed(self):
            if predicate(item, index):
                yield item
    return FlpIt(_FactoryIterable(_generator))

def where(self, predicate):
    _require_callable(predicate, "predicate")
    return FlpIt(_FactoryIterable(lambda: filter(predicate, self)))
```
- `where` switches to C-level `filter` (same truthiness semantics, same call order). Time O(n), memory O(1).
- `zip(source, count())` keeps the index bookkeeping in C. A `starmap`-based variant cannot be used for filtering (the item must survive), so `where_indexed` keeps a Python loop; measured against `enumerate`.
- **FlpList fast path**: none. Filtering has no O(1) shortcut and the mixin already passes the backing list to `filter`.

### 3.4 Registry entry
```toml
[operators.where_indexed]
category = "filtering"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Where(Func<TSource,int,bool>)"
python_equivalent = "(x for i, x in enumerate(xs) if p(x, i))"
since = "0.3.0"
```
The existing `[operators.where]` entry (F06) gets `python_equivalent = "filter(p, xs)"`.

## 4. Tests
- **Ported** `tests/nettests/test_where.py` from `WhereTests.cs` (92). The Array / List / IReadOnlyCollection / ICollection / IEnumerable variants map to `tuple`, `list`, a read-only `Sequence` wrapper, a `Collection` wrapper and the `non_collection` fixture (F08), so they are ported, not skipped. Expected skips:
  - `OTHER` (no `IEnumerator.Current`): the five `*_CurrentIsDefaultOfTAfterEnumeration` tests.
  - `OTHER` (no `IEnumerator.Reset`): `Select_ResetEnumerator_ThrowsException`.
  - `OTHER` (Python list iteration does not detect mutation): `Where_SourceThrowsOnConcurrentModification`.
  - `OTHER` (no `IDisposable` on list enumerators): `Where_SourceIsIList_EnumeratorDisposedOnComplete`, `..._OnExplicitDispose`.
  - `INTERNAL_OPTIMIZATION`: the `Assert.Same(result, enumerator1)` half of `Where_GetEnumeratorReturnsUniqueInstances` (the `iter(q) is not iter(q)` half is ported).
  - Adapted, not skipped: `Where_PredicateThrowsException`, `Where_SourceThrowsOnCurrent/OnMoveNext/OnGetEnumerator` assert the exception at the first `next`; the "subsequent MoveNext succeeds" half is replaced by asserting `StopIteration` (generator semantics, deviation note). `ToCollection` drops its `Current` asserts. `ForcedToEnumerator*` become `not isinstance(q, Iterator)`.
  - `IndexOverflows` ([ConditionalFact], not counted): skipped `OTHER` (no int overflow).
  - Target: ≥ 88 % of upstream cases ported.
- **Own unit tests** (`tests/unit/test_where.py`): `where(None)` / `where_indexed(None)` raise at call time even on an empty and on a one-shot source (source untouched); index counts rejected elements; index restarts on re-enumeration; `Falsy` predicate results reject; `where_indexed` on `order_by(...)` sees post-sort indices.
- **Contracts**: auto via registry (deferral, one-shot, FlpList not mutated).
- **Typing**: `assert_type(flp.lst([1]).where_indexed(lambda x, i: i > 0), FlpIt[int])`; a 1-arg lambda passed to `where_indexed` is a pyrefly error (negative check with `# pyrefly: expect-error`).

## 5. Differential harness
`difftest/specs/where.toml` (extend) and `where_indexed.toml`: sources empty, singleton, ints with duplicates, `None`-containing strings; predicates `{always, never, even, i % 3 == 0, i == len-1}`; probes `enumeration_count`, `predicate_calls` (must equal source length), `elements_pulled` for `where(...).first()`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_where.py` and `test_bench_where_indexed.py`, sizes 1e3 / 1e5, predicate `x % 3 == 0`:
- `native`: `list(filter(p, data))` / `[x for i, x in enumerate(data) if p(x, i)]`
- `flpit-FlpIt`: `flp.it(data).where(p).to_list()` / `.where_indexed(p).to_list()`; `flpit-FlpList` analogous.
- Target ratio ≤ 1.5× (streaming).

## 7. Docs
- `where_indexed` docstring: `.NET: Enumerable.Where(source, Func<TSource, int, bool>)`; truthiness rule; index counts source elements; `Execution: Deferred, streaming, re-iterable if the source is`.
- Doctest:
  ```python
  >>> flp.it([10, 20, 30, 40]).where_indexed(lambda x, i: i % 2 == 0).to_list()
  [10, 30]
  ```
- README deviations: "predicate results use truthiness", "indexed callbacks never overflow", "an exception ends the iteration (generator semantics)" (the last one is shared; add once).
- Translation map: `[x for i, x in enumerate(xs) if p(x, i)]` / `.Where((x, i) => ...)` → `.where_indexed(lambda x, i: ...)`.

## 8. Expected outcomes
- `where(None)` raises `ArgumentNoneError` at call time on all types.
- `where_indexed` available with typing; the `_indexed` helper exists for L16/L17/L02/L03.
- ~81 ported `WhereTests` green, README nettest table updated.

## 9. Verification
VERIFY-std with `<op>=where` and `<op>=where_indexed`, plus:
```bash
uv run pytest -q tests/nettests/test_where.py -rs | tail -3      # skip reasons listed by category
uv run python -c "from flpit import flp; flp.it([1]).where(None)"   # raises ArgumentNoneError at call time
uv run python -c "from flpit import flp; print(flp.it('abcd').where_indexed(lambda c, i: i % 2).to_list())"   # ['b', 'd']
```

## 10. Definition of Done
DoD-std, plus: the shared `_indexed` helper is documented in `rules.md` (callback order `(item, index)`), and the README deviation entries above exist.

## 11. Risks / open questions
- Generator-after-exception semantics affects every streaming operator; the deviation is documented once here (or by F08 if it lands first) instead of per card.
- Switching `where` to `filter` changes nothing observable, but the contract test for "predicate called once per element" must cover it.
