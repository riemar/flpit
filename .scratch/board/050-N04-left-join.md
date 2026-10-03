---
id: N04
title: left_join
status: todo
priority: 050
effort: M
depends_on: [F05, F06, F07, F08, F09, L20, L25, N01]
upstream:
  dotnet: LeftJoinTests.cs @ dotnet/runtime main 6f1d9331 (32 [Fact]/[Theory])
  morelinq: LeftJoin.cs (reference only, D7; superseded by the .NET 10 operator)
pr:
---

# N04: `left_join`

## 1. Goal
`LeftJoin` (.NET 10) replaces the notorious `GroupJoin(...).SelectMany(g => g.DefaultIfEmpty(), ...)` pattern with one call: every outer element, paired with each matching inner element or with "nothing". It is the most requested join after the inner `join` (L25) and lays the shared groundwork (the `JoinPair` result type and the join-lookup helper) for `right_join` (N05) and `full_join` (N06).

## 2. Scope
**In:** `left_join` on `_LinqOps`, tuple form and result-selector form; reuses the `JoinPair[O, I]` NamedTuple from `src/flpit/core/tuples.py` (introduced by L25, D24).
**Out:** comparer overloads (D3: normalise keys in both selectors). A `default=` keyword for the missing side (Python extension; use the result selector). Composite-key helpers (keys are any hashable, tuples work).

## 3. Detailed design
### 3.1 Signatures
```python
# src/flpit/core/tuples.py (defined by L25, shown for reference)
class JoinPair[O, I](NamedTuple):
    outer: O
    inner: I

# _LinqOps
@overload
def left_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
) -> FlpIt[JoinPair[TItem, TInner | None]]: ...
@overload
def left_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
    result_selector: Callable[[TItem, TInner | None], TResult],
) -> FlpIt[TResult]: ...
```
| .NET overload | flpit |
|---|---|
| `LeftJoin(inner, oKey, iKey, resultSelector)` | `left_join(inner, o_key, i_key, result_selector)` |
| `LeftJoin(inner, oKey, iKey, resultSelector, comparer)` | omitted (D3) |
| `LeftJoin(inner, oKey, iKey, comparer = null)` → `(Outer, Inner?)` | `left_join(inner, o_key, i_key)` → `JoinPair` |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (inner fully buffered into a lookup, outer streamed). Short-circuit: n/a.
- Validation (eager, .NET order): `inner` `None` → `ArgumentNoneError("inner")`; `outer_key_selector`, `inner_key_selector`, `result_selector` (if passed) `None` → `ArgumentNoneError(<name>)`.
- Enumeration order (mirrors `LeftJoin.cs`): pull the first outer element; if the outer side is **empty, the inner side is never enumerated** and `inner_key_selector` is never called. Otherwise build the inner lookup (all of inner, `inner_key_selector` once per element, in order), then stream outer: `outer_key_selector` once per outer element.
- Output order: outer order; for each outer element its matches in inner order; an outer element without match yields once with `inner=None`.
- **`None` keys never match** (as .NET `Lookup.CreateForJoin`): inner elements whose key is `None` are dropped from the lookup; outer elements whose key is `None` yield `(outer, None)`.
- Missing side is `None`. Ambiguity: a matched inner element that is itself `None` looks the same; use the result selector with a sentinel-aware projection if it matters (documented).
- Keys use Python equality and hashing (`1`, `1.0`, `True` match each other). Unhashable keys raise `TypeError` during enumeration (inner: while building the lookup; outer: on that element).
- Re-enumeration rebuilds the lookup (re-enumerates inner). A one-shot inner is empty on the second pass, so all outer elements come out unmatched; documented, same as .NET with a one-shot `IEnumerable`.
- **Deviations**: missing side is `None`, never `default(T)` (`0` for .NET value types; README entry "missing join side is None", shared with N05/N06). Results are `JoinPair` NamedTuples.

### 3.3 Implementation sketch
```python
_make_pair = partial(tuple.__new__, JoinPair)

def left_join(self, inner, outer_key_selector, inner_key_selector, result_selector=_SENTINEL):
    _require_not_none(inner, "inner")
    _require_callable(outer_key_selector, "outer_key_selector")
    _require_callable(inner_key_selector, "inner_key_selector")
    if result_selector is not _SENTINEL:
        _require_callable(result_selector, "result_selector")
    src = self._source()
    def _generator():
        it = iter(src)
        first = next(it, _MISSING)
        if first is _MISSING:
            return
        get = _build_lookup(inner, inner_key_selector, skip_none_keys=True).get   # L20; dict[key, Grouping]
        for item in chain((first,), it):
            matches = get(outer_key_selector(item))
            if matches is None:
                yield _make_pair((item, None)) if result_selector is _SENTINEL else result_selector(item, None)
            elif result_selector is _SENTINEL:
                for m in matches: yield _make_pair((item, m))
            else:
                for m in matches: yield result_selector(item, m)
    return FlpIt(_FactoryIterable(_generator))
```
- `_build_lookup(..., skip_none_keys=True)` is **L20's lookup builder** (`src/flpit/core/_lookup.py`; dict of `Grouping`s in first-occurrence key order, `None` keys skipped), the same call L25 `join` and L26 `group_join` make. No second implementation.
- Because `None` keys are never stored, `get(None)` returns `None`: no explicit `key is None` branch in the hot loop.
- The result-selector branch is hoisted out of the inner loops; if profiling shows the per-outer `is _SENTINEL` test matters, split into two generator functions.
- Time O(|outer| + |inner| + |output|); memory O(|inner|).
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.left_join]
category = "join"
kind = "intermediate"
buffering = "partial"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.LeftJoin"
morelinq = "MoreEnumerable.LeftJoin"
python_equivalent = "lk = defaultdict(list) over inner; [(o, i) for o in outer for i in lk.get(k(o)) or [None]]"
since = "0.4.0"
card = "N04"
notes = "Missing inner is None; None keys never match; JoinPair(outer, inner)."
```

## 4. Tests
- **Ported** `tests/nettests/test_left_join.py` from `LeftJoinTests.cs` (32 cases). Adaptations, not skips:
  - `NO_VALUE_TYPES` (adapted): .NET struct records get `default` (`orderID = 0`) for the missing side; the Python `create_join_rec(c, o)` helper maps `o is None` to `0`, so expectations stay identical.
  - Comparer cases (`CustomComparer`, `TupleLeftJoin_WithComparer`): `AnagramEqualityComparer` becomes the key selector `lambda s: "".join(sorted(s))` on both sides (intent preserved, D3). `NullKeysRemainUnmatched` with `OrdinalIgnoreCase` becomes `lambda s: None if s[0] == "#" else s.lower()`.
  - Null-argument tests (`OuterNull` → `flp.it(None)` raises `SourceNoneError`; the rest `ArgumentNoneError` with the param name), with and without comparer variants collapsing to the same call (both kept for traceability).
  - `ForcedToEnumeratorDoesntEnumerate`: ported as `not isinstance(query, Iterator)`.
  - Expected skips: none. Target: 32/32 (100 %).
- **Own unit tests** (`tests/unit/test_left_join.py`): empty outer never touches inner (`Bomb`-raising inner iterable, call-counting `inner_key_selector`); selector call counts; duplicate keys on both sides (cartesian per key, order); `None` keys both sides; matched `None` inner element vs missing; `1`/`True` key equality; unhashable outer key raises `TypeError` on that element only; one-shot inner on re-enumeration; `JoinPair` attribute access and unpacking.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).left_join(["a"], str, str), FlpIt[JoinPair[int, str | None]])`; result-selector form infers `TResult`.

## 5. Differential harness
`difftest/specs/left_join.toml`: outer/inner: empty, singleton, ints with duplicates, strings incl. `null`; key selectors: identity, `x % 3`, "null for negatives". Probes: values, enumeration order log (proves inner untouched for empty outer), selector call counts. The C# side declares element types as nullable/reference (`int?`, `string`) so `default` is `null` and compares to `None`; with that, all MATCH. The tuple-returning overloads are .NET 11 (runtime `main`) only, like L25's `Join` tuple form; instead of marking them `UNCOMPARABLE` (L25's choice), the oracle runs the .NET 10 result-selector overload with `(o, i) => (o, i)`, which is what the .NET 11 tuple overload does by definition (see `FullJoin.cs`). Align L25 to the same approach.

## 6. Benchmarks
`tests/benchmarks/test_bench_left_join.py`, sizes 1e3 and 1e5 (outer = inner = size, inner keys `x // 2` so half the outer keys match twice, half never):
- `native`: `lk = defaultdict(list)`; `for i in inner: lk[ikey(i)].append(i)`; `[(o, i) for o in outer for i in lk.get(okey(o)) or (None,)]`.
- `flpit-FlpIt` / `flpit-FlpList`: `.left_join(inner, okey, ikey).to_list()` and the result-selector form `lambda o, i: (o, i)`.
- Target ratio ≤ 1.5× tuple form (NamedTuple construction), ≤ 1.3× result-selector form.

## 7. Docs
- Docstring: "Correlates outer elements with matching inner elements by key, keeping outer elements without a match."; `.NET: Enumerable.LeftJoin`; Args, Returns, Raises; Execution (deferred, inner buffered, outer streamed, inner untouched when outer is empty); `None` keys and missing side. Example:
  ```python
  >>> flp.it([1, 2, 3]).left_join([2, 3, 3], lambda o: o, lambda i: i).to_list()
  [JoinPair(outer=1, inner=None), JoinPair(outer=2, inner=2), JoinPair(outer=3, inner=3), JoinPair(outer=3, inner=3)]
  >>> flp.it(["ann", "bob"]).left_join([("rex", "ann")], lambda p: p, lambda pet: pet[1], lambda p, pet: (p, pet and pet[0])).to_list()
  [('ann', 'rex'), ('bob', None)]
  ```
- README: matrix row; deviation "missing join side is None"; "Named tuple results" table gains `JoinPair`.
- Translation map: `.LeftJoin(...)` / `GroupJoin+SelectMany+DefaultIfEmpty` / pandas-style `merge(how="left")` → `.left_join(...)`.

## 8. Expected outcomes
- `left_join` on all four types; `JoinPair` exported and used by `join` (L25) too.
- 32 ported .NET tests green, own tests, benchmark recorded, difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=left_join`, plus:
```bash
uv run pytest -q tests/nettests/test_left_join.py -rs      # expect 0 skipped
uv run python -c "from flpit import flp; print(flp.it([1, 2]).left_join([2], lambda o: o, lambda i: i).to_list())"
# [JoinPair(outer=1, inner=None), JoinPair(outer=2, inner=2)]
```

## 10. Definition of Done
DoD-std, plus: `JoinPair` reused (not redefined); the join-lookup helper (L20) is shared, not duplicated.

## 11. Risks / open questions
- Result type settled by D24 (`JoinPair`, introduced in L25).
- `None` doubling as "missing" and "a real None element" is inherent to the Python mapping; revisit only if users ask for `default=`.
