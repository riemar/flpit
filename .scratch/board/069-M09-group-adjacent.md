---
id: M09
title: group_adjacent
status: todo
priority: 069
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: GroupAdjacent.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; GroupAdjacentTest.cs has 8 [Test]/[TestCase])
pr:
---

# M09: `group_adjacent`

## 1. Goal
`group_adjacent` groups **consecutive** elements with equal keys, the streaming counterpart of `group_by` and the LINQ face of `itertools.groupby`. It is the right tool for sorted or naturally clustered data (log lines per request, rows per date) because it never buffers more than one group and keeps the original order. Effort M because it settles the selector-overload shape that L24 `group_by` overloads must share.

## 2. Scope
**In:** `group_adjacent(key_selector, element_selector=..., *, result_selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`), yielding the existing `Grouping[TKey, TElement]` class.
**Out:** comparer overloads (D3: put the normalisation into the key selector, e.g. `key=str.lower`); lazy (unbuffered) inner groups like raw `itertools.groupby` (unsafe when consumers skip groups).

**MoreLINQ overload mapping** (6 overloads)
| MoreLINQ | flpit |
|---|---|
| `GroupAdjacent(keySelector)` | `group_adjacent(key_selector)` |
| `GroupAdjacent(keySelector, elementSelector)` | `group_adjacent(key_selector, element_selector)` |
| `GroupAdjacent(keySelector, resultSelector(key, IEnumerable<T>))` | `group_adjacent(key_selector, result_selector=f)` |
| the three `..., IEqualityComparer<TKey>` overloads | omitted (D3) |
| (none) | `group_adjacent(key_selector, element_selector, result_selector=f)`: superset, as .NET `GroupBy(key, element, result)` |

`result_selector` is keyword-only: positionally it would be indistinguishable from `element_selector` at runtime (both are callables), the same problem L24 faces with `GroupBy(key, resultSelector)`.

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def group_adjacent(self, key_selector: Callable[[TItem], TKey]) -> FlpIt[Grouping[TKey, TItem]]: ...
@overload
def group_adjacent(self, key_selector: Callable[[TItem], TKey],
                   element_selector: Callable[[TItem], TElement]) -> FlpIt[Grouping[TKey, TElement]]: ...
@overload
def group_adjacent(self, key_selector: Callable[[TItem], TKey], *,
                   result_selector: Callable[[TKey, FlpList[TItem]], TResult]) -> FlpIt[TResult]: ...
@overload
def group_adjacent(self, key_selector: Callable[[TItem], TKey],
                   element_selector: Callable[[TItem], TElement], *,
                   result_selector: Callable[[TKey, FlpList[TElement]], TResult]) -> FlpIt[TResult]: ...
```
New TypeVar `TElement` (shared with L24).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (one group). Short-circuit: n/a; a group is yielded when the first element of the next group (or end of source) is seen.
- Key equality is Python `==` between the previous group's key and the new key (`prev == new`), as `itertools.groupby` does. `None` keys group normally.
- The group key is the key of the **first** element of the run.
- `key_selector` is called exactly once per element, in source order; `element_selector` once per element; `result_selector` once per group with `(key, FlpList)`.
- Empty source → nothing. Groups are never empty. Non-adjacent equal keys produce separate groups (`[1, 1, 2, 1]` → keys `1, 2, 1`).
- Each `Grouping` owns a materialised list: it is re-iterable and remains valid after the outer iteration advances (unlike raw `groupby` groups).
- Validation (eager): `key_selector`, `element_selector`, `result_selector` explicitly `None` → `ArgumentNoneError(<name>)`.
- Exceptions from source or callbacks propagate at enumeration; the open group is discarded.

### 3.3 Implementation sketch
```python
def _generator():
    if element_selector is _SENTINEL:
        for key, run in groupby(src, key_selector):
            yield make(key, list(run))
    else:
        for key, run in groupby(src, key_selector):
            yield make(key, list(map(element_selector, run)))
# make = Grouping (default) or lambda k, xs: result_selector(k, FlpList(xs))
```
- `itertools.groupby` is C-level, calls the key once per element and stops at the first key change; `list(run)` drains the run before the next group is requested, so memory is one group. O(n) time.
- `Grouping(key, list)` reuses the existing class (`FlpIt` subclass with `.key`, `__eq__`, `__repr__`). It is constructed over the list without copying.
- **Callback interleaving difference:** MoreLINQ calls `keySelector(x)` then `elementSelector(x)` for the element that opens group k+1 *before* yielding group k; with `groupby` the element selector for that element runs when group k+1 is built. Values are identical; only the relative order of `element_selector`/`result_selector` calls around a boundary differs. Documented, and classified in the difftest spec.
- **FlpList fast path**: none (`groupby` is already optimal).

### 3.4 Registry entry
```toml
[operators.group_adjacent]
category = "grouping"
kind = "intermediate"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.GroupAdjacent"
python_equivalent = "itertools.groupby(xs, key)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `GroupAdjacentTest.cs` (8 cases) as checklist:
  - covered: laziness; key selector; element selector; result selector; some `null` keys.
  - `COMPARER_NOT_SUPPORTED`: the three `...Comparer` cases; own equivalents use a case-folding key selector, which preserves their intent.
  - Target: 100 % of behaviours (5 direct + 3 rewritten via key selector).
- **Own unit tests** (`tests/unit/morelinq/test_group_adjacent.py`, both `flp_type`s):
  - `"aabccc"` → keys `a, b, c` with sizes `2, 1, 3`; non-adjacent repeats produce new groups.
  - Group key is the first element's key (`key=str.lower` over `["A", "a", "B"]` → key `"a"`, elements `["A", "a"]`).
  - Element selector, result selector, and the combined form; result selector receives an `FlpList`.
  - Groups stay valid after advancing (collect all groups, then iterate each twice).
  - Callback counts: key and element selector exactly n calls; result selector one per group.
  - `None` keys; empty source; single element.
  - Streaming: first group yielded after pulling the first element of the second group (counting source).
  - `None` selectors raise at call time.
- **Contracts:** auto via registry.
- **Typing** (`tests/typing/test_types_group_adjacent.py`): all four overloads, e.g. `assert_type(flp.it("ab").group_adjacent(str.upper), FlpIt[Grouping[str, str]])`.

## 5. Differential harness
`difftest/specs/group_adjacent.toml`, oracle calls the three non-comparer `MoreEnumerable.GroupAdjacent` overloads (pinned `morelinq` NuGet), normalising `IGrouping` to `{key, elements}`. Domains: empty, singleton, all-equal, alternating keys, sorted runs, strings with null keys; selectors from a catalogue. Probes: groups, per-callback call counts, `elements_pulled` after `first()`. Expected: MATCH; `EXPECTED_DIFFERENCE` for (a) the cross-callback call order at group boundaries (§3.3) and (b) NaN keys (.NET groups NaN with NaN; Python `==` never does). The combined element+result form is Python-only (unit tests only).

## 6. Benchmarks
`tests/benchmarks/test_bench_group_adjacent.py`, sizes 1e3 / 1e5, data = sorted ints with runs of ~10:
- `native`: `[(k, list(g)) for k, g in itertools.groupby(data, key)]`.
- `flpit-FlpIt` / `flpit-FlpList`: `group_adjacent(key).to_list()`.
- Target ratio ≤ 1.3× (cost of `Grouping` object vs tuple).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.GroupAdjacent(keySelector, [elementSelector | resultSelector])`; Args; Returns; Raises; `Execution:` deferred, buffers one group; contrast with `group_by` (whole source, non-adjacent merge).
- Doctest:
  ```python
  >>> flp.it("aabccc").group_adjacent(lambda c: c).select(lambda g: (g.key, g.count())).to_list()
  [('a', 2), ('b', 1), ('c', 3)]
  >>> flp.it([1, 1, 2, 1]).group_adjacent(lambda x: x, result_selector=lambda k, xs: len(xs)).to_list()
  [2, 1, 1]
  ```
- Translation map: `.GroupAdjacent(k)` / `itertools.groupby(xs, k)` → `.group_adjacent(k)`.
- Deviations (README): `==` equality (NaN keys never group); group key = first element's key (same as MoreLINQ, stated for clarity).

## 8. Expected outcomes
- `group_adjacent` with all overload shapes; ~15 own tests; difftest 0 MISMATCH; benchmark recorded.
- The keyword-only `result_selector` pattern is documented as the convention for L24 (`group_by`) and L26 (`group_join`).

## 9. Verification
VERIFY-std with `<op>=group_adjacent`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_group_adjacent.py
uv run python -c "from flpit import flp; print(flp.it([1,1,2,1]).group_adjacent(lambda x: x).to_list())"
# [Grouping(key=1, elements=[1, 1]), Grouping(key=2, elements=[2]), Grouping(key=1, elements=[1])]
```

## 10. Definition of Done
DoD-std, plus: L24 card updated (or a comment left on it) to adopt keyword-only `result_selector`, so `group_by` and `group_adjacent` share one shape.

## 11. Risks / open questions
- Cross-card: if L24 lands first with a positional `result_selector`, this card must follow it instead; whichever lands first sets the convention.
- `Grouping.__repr__` calls `to_list()`; harmless here (materialised list) but worth keeping in mind for lazy groupings.
