---
id: N10
title: try_get_non_enumerated_count
status: todo
priority: 054
effort: S
depends_on: [F05, F06, F07, F08, F09, N09]
upstream:
  dotnet: CountTests.cs (4 of 13 [Fact]/[Theory] cover it) + OfTypeTests.cs `Count` (3 assertions) @ dotnet/runtime main 6f1d9331
  morelinq: n/a
pr:
---

# N10: `try_get_non_enumerated_count`

## 1. Goal
`TryGetNonEnumeratedCount` (.NET 6) answers "how many elements, if that is free?" without iterating. Users need it to pre-size buffers or pick a strategy; flpit needs it internally for fast paths (`take(slice)` with negative bounds already uses the private hook from N09; `take_last`, `skip_last`, `element_at(-k)`, `chunk` and `to_list` pre-sizing benefit too). This card publishes the hook, defines which queries know their count, and exposes it to Python's own `operator.length_hint`.

## 2. Scope
**In:** public `try_get_non_enumerated_count()` on `_LinqOps`; the count-provider mechanism (`_FactoryIterable(..., count=...)`); providers for every existing operator whose count is a pure function of its inputs' counts; `FlpIt.__length_hint__`; rewrite of the 3 skipped/placeholder tests in `tests/nettests/test_count.py`.
**Out:** a `__len__` on `FlpIt` (would change truthiness, `bool(flp.it([]))` is `True` today and must stay so, and would make `list()` call it); counting by enumeration (that is `count()`); `Count(onlyIfCheap: false)` semantics.

## 3. Detailed design
### 3.1 Signatures
```python
def try_get_non_enumerated_count(self) -> int | None: ...

class FlpIt:
    def __length_hint__(self) -> int: ...      # count or NotImplemented
```
| .NET | flpit |
|---|---|
| `bool TryGetNonEnumeratedCount(out int count)` | `try_get_non_enumerated_count() -> int \| None` |

Python has no `out` parameters; `int | None` is the idiomatic "maybe" (like `dict.get`). Pitfall documented: test with `is not None`, since `0` is a valid count. The `(bool, int)` tuple assumed by the current placeholder tests is rejected (unpythonic, and `if q.try_...():` would always be true).

### 3.2 Semantics
- Kind: terminal, immediate. Buffering: none. Short-circuit: n/a. **Never iterates the source and never calls user callbacks** (selectors, predicates). It may call `len()` on a user source object, the Python equivalent of reading `ICollection<T>.Count`.
- Returns the count when known cheaply, else `None`:
  | Receiver / source | Result |
  |---|---|
  | `FlpList` | `len()` |
  | `FlpIt` over a `Sized` source (list, tuple, `range`, str, dict and views, set, deque, FlpList, any `__len__`) | `len(source)` |
  | `flp.range`, `flp.repeat`, `flp.empty` (L13), `flp.sequence` int fast path (N12) | count |
  | `Grouping` | number of elements (backed by a list) |
  | `order*` / `then_by*` (`OrderedIt`), `select`, `select_indexed`, `cast`, `reverse`, `shuffle`, `index` | source count |
  | `append` / `prepend` | source count + 1 |
  | `concat` | sum, if both known |
  | `default_if_empty` | `max(c, 1)` |
  | `take(n)` / `skip(n)` / `take(slice)` / `take_last` / `skip_last` | derived with slice arithmetic |
  | `zip` | `min` of the inputs, if all known |
  | `chunk(size)` | `ceil(c / size)` |
  | generator / iterator sources, `where`, `distinct*`, `select_many`, `group_by`, `of_type`, `take_while`, set ops, joins | `None` |
- Evaluated at call time (a later mutation of a backing list changes later answers, like .NET).
- **Deviation** (README § Intentional Semantic Deviations): flpit may report a count where .NET returns `false` (e.g. `index`, `zip`, `chunk`, `take` over a non-list counted source, `select` over a non-`IList` collection such as `Stack<T>`); whenever flpit returns an `int` it is the exact count. flpit never returns `None` where .NET returns a count for the operators both have.
- `__length_hint__` returns the same value or `NotImplemented`, so `list(query)` / `FlpList(query)` pre-size their buffer.

### 3.3 Implementation sketch
```python
class _FactoryIterable:
    __slots__ = ("_factory", "_count")
    def __init__(self, factory, count: Callable[[], int | None] | None = None): ...

def _cheap_count(src: object) -> int | None:          # module-level
    if isinstance(src, _FactoryIterable):
        return src._count() if src._count is not None else None
    if isinstance(src, _LinqOps):
        return src._count_if_cheap()
    if isinstance(src, Sized):
        return len(src)
    return None

# _LinqOps
def try_get_non_enumerated_count(self):
    return self._count_if_cheap()
# FlpIt._count_if_cheap -> _cheap_count(self._iterable); FlpList -> len(backing list)

# provider example (select)
def select(self, selector):
    src = self._source()
    return FlpIt(_FactoryIterable(lambda: map(selector, src), count=lambda: _cheap_count(src)))
```
- `_count_if_cheap` replaces N09's minimal version (same name, same contract), which already absorbed L10's `_sized_source()`.
- Providers are lambdas evaluated lazily at query time: O(depth of the query) per call, no iteration.
- `isinstance(x, Sized)` is an ABC check (cached by `abc`); a fast `type(src) in (list, tuple, range, dict)` pre-check is optional and only if the benchmark shows it matters.
- **FlpList fast path**: none needed (`len`).
- Internal adopters in this PR: `take(slice)` (already), `take_last`/`skip_last` (via N09 helper), `element_at` with negative index (L10) if present. `.agents/rules.md` gains: "new count-preserving or count-derived operators pass `count=` to `_FactoryIterable`".

### 3.4 Registry entry
```toml
[operators.try_get_non_enumerated_count]
category = "aggregation"
kind = "terminal"
buffering = "streaming"          # never enumerates
short_circuit = true
origin = "dotnet"
dotnet = "Enumerable.TryGetNonEnumeratedCount"
python_equivalent = "len(xs) if isinstance(xs, Sized) else None"
since = "0.4.0"
card = "N10"
notes = "Returns int | None; never iterates; may know counts where .NET does not."
```

## 4. Tests
- **Ported** into `tests/nettests/test_count.py` (the file already holds the placeholders): rewrite `test_NonEnumeratedCount_*` for the `int | None` API and un-skip them; add the missing `NonEnumeratedCount_ShouldNotEnumerateSource`. Port `OfTypeTests.Count`'s three `TryGetNonEnumeratedCount` assertions into `tests/nettests/test_of_type.py` if B04 created it, else into `test_count.py`.
  - Supported rows rebuilt with flpit operators to keep the upstream intent (today's data pre-materialises them, e.g. `sorted(...)` instead of `OrderBy`): list, tuple, `deque` (Stack), `flp.empty()`, `flp.range(1, 100)`, `flp.repeat(1, 80)`, `flp.range(1, 20).reverse()`, `.order_by(lambda x: -x)`, `.concat(...)`, and the speed-optimised `select` rows.
  - Unsupported rows: `where`, `group_by`, `distinct` ported; `Stack.Select` row dropped with `INTERNAL_OPTIMIZATION` (flpit counts `deque.select`, see deviation); non-speed-optimised rows dropped (`INTERNAL_OPTIMIZATION`, .NET build flavour).
  - `NullSource` → `flp.it(None)` raises `SourceNoneError` (the current loose `pytest.raises((AttributeError, TypeError, ValueError))` is tightened).
  - Target: 4/4 test functions + OfType block ported; 1 + 3 data rows dropped.
- **Own unit tests** (`tests/unit/test_try_get_non_enumerated_count.py`):
  - Every row of the table in §3.2, each with a source that raises on `__iter__` (`NoIterList`) and callbacks that raise, proving nothing is enumerated or called.
  - `0` is returned (not `None`) for empty counted sources.
  - `list(q)` pre-sizing: `operator.length_hint(q)` equals the count, or the default when unknown.
  - Truthiness unchanged: `bool(flp.it([]))` is `True`; `FlpIt` has no `__len__`.
  - Mutating a backing list changes the next answer.
- **Contracts**: registry marks it terminal/non-enumerating; F08's "terminal ops enumerate at most once" contract plus a specific "zero enumeration" check.
- **Typing**: `assert_type(flp.it([1]).try_get_non_enumerated_count(), int | None)`.

## 5. Differential harness
`difftest/specs/try_get_non_enumerated_count.toml`: compositions over array / list / non-collection sources: `Select`, `OrderBy`, `Concat`, `Append`, `Reverse`, `Where`, `Distinct`, `GroupBy`, `Take(n)` on array, `Skip(n)` on array, `Range`, `Repeat`, `Empty`. Probes: the `(found, count)` pair, mapped from `int | None`. Expected: MATCH everywhere except compositions where flpit knows more (`Index`, `Zip`, `Chunk`, `Take` over a counted non-list iterator): `EXPECTED_DIFFERENCE` with reason "flpit returns an exact count where .NET reports false" and an extra check that flpit's count equals `Count()`.

## 6. Benchmarks
`tests/benchmarks/test_bench_try_get_non_enumerated_count.py` (micro, sizes irrelevant; use 1e3 and 1e5 for the harness):
- `native`: `len(data) if isinstance(data, Sized) else None`.
- `flpit-FlpIt`: `flp.it(data).select(f).order_by(k).try_get_non_enumerated_count()`; `flpit-FlpList`: `flp.lst(data).try_get_non_enumerated_count()`.
- Target: constant time independent of size; ratio ≤ 3× vs native for the FlpList case (method dispatch on a ~50 ns operation), recorded only. Plus `to_list()` before/after `__length_hint__` on 1e5 `select` (expect a small gain, must not regress).

## 7. Docs
- Docstring: "Returns the number of elements if it can be determined without enumerating the sequence, otherwise None."; `.NET: Enumerable.TryGetNonEnumeratedCount(out int)`; Returns (`int | None`, use `is not None`); Execution (terminal, never enumerates, never calls callbacks); which queries know their count (short form of the table). Example:
  ```python
  >>> flp.lst([1, 2, 3]).select(lambda x: x * 2).try_get_non_enumerated_count()
  3
  >>> flp.it(x for x in "ab").try_get_non_enumerated_count() is None
  True
  ```
- README: matrix row; deviation entry; a short paragraph in "Execution Characteristics" on count propagation.
- Translation map: `.TryGetNonEnumeratedCount(out var n)` → `n = q.try_get_non_enumerated_count()`; Python idiom `len(xs) if isinstance(xs, Sized) else None` / `operator.length_hint`.

## 8. Expected outcomes
- Public, documented count hook; counted queries pre-size `list()`; N09/L04/L05/L10 fast paths share one mechanism.
- The skipped placeholders in `test_count.py` become real ported tests.
- Benchmark recorded; difftest 0 MISMATCH (documented EXPECTED_DIFFERENCE rows only).

## 9. Verification
VERIFY-std with `<op>=try_get_non_enumerated_count`, plus:
```bash
uv run pytest -q tests/nettests/test_count.py -rs -k NonEnumerated     # no skips left except the documented data rows
uv run python -c "from flpit import flp; print(flp.range(0, 5).order_by(lambda x: -x).try_get_non_enumerated_count())"   # 5
uv run python -c "import operator; from flpit import flp; print(operator.length_hint(flp.it([1, 2]).select(str)))"         # 2
```

## 10. Definition of Done
DoD-std, plus the provider checklist line in `.agents/rules.md`, and every operator in §3.2's table covered by a "does not enumerate" test.

## 11. Risks / open questions
- Provider coverage drifts as new cards land; mitigated by the rules.md checklist and a contract test that compares `try_get_non_enumerated_count()` (when not `None`) with `count()` for every registered intermediate operator.
- `flp.repeat` is currently a one-shot generator (bug fixed by B08, which rebuilds it as `_FactoryIterable(partial(itertools.repeat, element, count))`). B08 has no count provider; this card adds `count=lambda: count` there (or B08 does it if it lands after N10).
- Found while reading `tests/nettests/test_count.py`: `test_it_Int` is defined twice, so the FlpIt variant never runs (the FlpList one shadows it). Out of scope here; fix in F08 or B-phase (rename to `test_it_Int_FlpIt` / `_FlpList`).
