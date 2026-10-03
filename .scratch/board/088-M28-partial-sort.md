---
id: M28
title: partial_sort / partial_sort_by
status: todo
priority: 088
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (equivalent query: OrderBy(...).Take(n))
  morelinq: PartialSort.cs @ morelinq master d217ab1 (reference only, D7; PartialSortTest.cs 7 + PartialSortByTest.cs 6 [Test], read for behaviour; both stability tests are [Ignore("TODO")] upstream)
pr:
---

# M28: `partial_sort` / `partial_sort_by`

## 1. Goal
"Top 10 by score" written as `order_by(score).take(10)` sorts the whole input: O(n log n) time and O(n) memory. `partial_sort(_by)` keeps only the best `k` while streaming: O(n log k) time, O(k) memory, via `heapq.nsmallest`/`nlargest`. flpit makes it **stable** (exactly equal to `order_by(...).take(k)`), which MoreLINQ does not guarantee (its stability tests are ignored as TODO).

## 2. Scope
**In:** `partial_sort(count, *, descending=False)`, `partial_sort_by(count, key_selector, *, descending=False)` on `_LinqOps`; a FlpList fast path for the keyless form.
**Out:** returning an `OrderedIt` (no `then_by` after a partial sort; MoreLINQ returns `IEnumerable<T>` too); comparer overloads (D3).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `PartialSort(count)` | `partial_sort(count)` |
| `PartialSort(count, OrderByDirection)` | `partial_sort(count, descending=...)` |
| `PartialSort(count, IComparer<T>)`, `(count, IComparer<T>, OrderByDirection)` | omitted (D3): `partial_sort_by(count, key)` |
| `PartialSortBy(count, keySelector)` | `partial_sort_by(count, key_selector)` |
| `PartialSortBy(count, keySelector, OrderByDirection)` | `partial_sort_by(count, key_selector, descending=...)` |
| `PartialSortBy(count, keySelector, IComparer<TKey>)`, `(..., IComparer<TKey>, OrderByDirection)` | omitted (D3) |

`OrderByDirection` becomes a keyword-only `descending: bool`, consistent with `sorted(reverse=...)` and M27.

## 3. Detailed design
### 3.1 Signatures
```python
def partial_sort(self, count: int, *, descending: bool = False) -> FlpIt[TItem]: ...
def partial_sort_by(
    self, count: int, key_selector: Callable[[TItem], Any], *, descending: bool = False
) -> FlpIt[TItem]: ...
```
Argument order `(count, key_selector)` follows MoreLINQ for translation fidelity.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (at most `count` elements retained) but the whole source is consumed before the first element is yielded. Short-circuit: none.
- **Contract:** `partial_sort_by(k, f)` yields exactly the same elements in the same order as `order_by(f).take(k)`; with `descending=True` as `order_by_descending(f).take(k)`. Ties keep source order (stable). `partial_sort(k)` is the same with the element as its own key.
- None keys/elements sort lowest, via the existing `_none_aware_key` (same rule as `order_by`).
- `count == 0` → empty, the source is still not iterated (`count` known at call time). `count >= len` → full stable sort.
- Validation (eager): `count = _require_index(count, "count")`; `count < 0` → `ArgumentOutOfRangeError("count")`. MoreLINQ fails only at enumeration (from `new List<T>(count)`, message naming `capacity`); flpit validates at call time like its other deferred ops (README deviation, difftest EXPECTED_DIFFERENCE). `key_selector is None` → `ArgumentNoneError("key_selector")`; `descending` must be a `bool` (`_require_bool`, shared with M27).
- `key_selector` is called once per element, in source order (`heapq` decorates each element once). Incomparable keys raise `TypeError` at enumeration.
- Re-enumeration re-runs the selection.

### 3.3 Implementation sketch
```python
def partial_sort_by(self, count, key_selector, *, descending=False):
    count = _require_non_negative(_require_index(count, "count"), "count")
    _require_callable(key_selector, "key_selector"); _require_bool(descending, "descending")
    if count == 0:
        return FlpIt(())
    src = self._source()
    pick = heapq.nlargest if descending else heapq.nsmallest
    key = partial(_none_aware_key, key_selector)
    return FlpIt(_FactoryIterable(lambda: iter(pick(count, src, key=key))))

def partial_sort(self, count, *, descending=False):
    ...same validation...
    return FlpIt(_FactoryIterable(lambda: iter(pick(count, src, key=_none_aware_identity))))
```
- `heapq.nsmallest(n, it, key)` is documented as equivalent to `sorted(it, key=key)[:n]` and `nlargest` to `sorted(it, key=key, reverse=True)[:n]`: both stable, both match `order_by(_descending)` (which uses `list.sort(reverse=...)`). They switch to `min`/`max` for `n == 1` and to `sorted` when `n >= len`, all stable. O(n log k) time, O(k) memory.
- **FlpList fast path** (keyless form only): try `heapq.nsmallest(count, data)` without a key wrapper; on `TypeError` (a `None` was compared) retry with `_none_aware_identity`. Re-reading a list is side-effect free, so the result is identical, and the common no-None case avoids a Python-level key call per element (prototype at 1e5 floats, k = 10: 1.5 ms without key vs 4.5 ms with the wrapper). The FlpIt generic path cannot retry (one-shot sources), so it always wraps.

### 3.4 Registry entries
```toml
[operators.partial_sort]
category = "ordering"
kind = "intermediate"
buffering = "partial"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.PartialSort"
python_equivalent = "heapq.nsmallest(k, xs)"
contract_args = "(2,)"
since = "0.4.0"   # adjust to the release that ships it
card = "M28"
notes = "stable (== order_by(...).take(k)); MoreLINQ tie order unspecified"

[operators.partial_sort_by]   # same fields; morelinq = "MoreEnumerable.PartialSortBy",
                              # python_equivalent = "heapq.nsmallest(k, xs, key=f)", contract_args = "(2, lambda x: x)"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design). MoreLINQ's 13 cases (basic, direction, duplicates, comparer, laziness, two ignored stability tests) are a checklist; comparer cases become key-selector tests; the ignored stability tests become real own tests here. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_partial_sort.py`, both `flp_type`s):
  - **Property (Hypothesis):** for random lists of `(key, tag)` pairs with many ties, random `k` in `0..len+2` and both directions, `partial_sort_by(k, key)` equals `order_by(key).take(k)` / `order_by_descending(key).take(k)` element-for-element (identity of tagged objects). Same for `partial_sort` vs `order_by(identity)`.
  - Explicit stability: ten equal-but-distinct strings (`"".join(list("foobar"))` copies) keep source identity order.
  - `k = 0` (no iteration), `k = 1`, `k = len`, `k > len`; empty source.
  - None keys/elements sort first ascending and last descending.
  - Key-selector call count = n; deferral (`NoIterList`).
  - Validation: `-1` → `ArgumentOutOfRangeError` at call time; `None` count/key → `ArgumentNoneError`; `1.5` → `TypeError`; `descending="yes"` → `TypeError`.
  - FlpList fast path with and without `None` elements equals the generic path.
- **Contracts** (auto): deferral, lazy key selector, FlpList not mutated, `buffering = partial`.
- **Typing** (`tests/typing/test_types_partial_sort.py`): both return `FlpIt[T]` (not `OrderedIt`); `descending` keyword-only.

## 5. Differential harness
`difftest/specs/partial_sort.toml`, `partial_sort_by.toml`; oracle `Operators/PartialSort.cs` calling `MoreEnumerable.PartialSort/PartialSortBy` statically, mapping `descending` to `OrderByDirection`.
- `count ∈ {-1, 0, 1, 2, len-1, len, len+1}`; items: empty, singleton, duplicates-heavy ints, strings, ints with nulls; keys: `identity`, `mod(k)`, `key_len`.
- **Comparison profile `sorted_ties_unordered`** (new, owned by this card, generic for X01): key sequence must match exactly; within each run of equal keys the elements must match as a multiset, except the last run cut by `count`, where only membership in the source's equal-key set is checked. Justification: MoreLINQ's tie order is unspecified (`BinarySearch` insertion); flpit's stricter stable order is covered by the unit-test property above. The profile is used only for `partial_sort_by` with non-injective keys; keyless `partial_sort` over ints/strings compares exactly (equal elements are indistinguishable).
- Expected: MATCH (exact or under the profile). `count = -1`: `EXPECTED_DIFFERENCE` (reason: "OTHER: eager validation; MoreLINQ throws at enumeration naming 'capacity'").

## 6. Benchmarks
`tests/benchmarks/test_bench_partial_sort.py`, sizes 1e3 / 1e5, random floats, `k = 10` and `k = 1000`:
- `native`: `heapq.nsmallest(k, data)` and `heapq.nsmallest(k, data, key=f)`; reference row `sorted(data)[:k]` (what `order_by().take()` costs).
- `flpit-FlpIt` / `flpit-FlpList`: `.partial_sort(k).to_list()`, `.partial_sort_by(k, f).to_list()`.
- Targets: FlpList keyless ≤ 1.3×; FlpIt keyless ≤ 3.0× (None-aware key wrapper per element, still ~4× faster than `sorted()[:k]`); `partial_sort_by` ≤ 1.5× vs `nsmallest(key=f)`.

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.PartialSort(count[, direction])` / `PartialSortBy(count, keySelector[, direction])`; the stability contract; `Execution: Deferred; consumes the whole source, keeps count elements`; doctests:
  ```python
  >>> flp.it([5, 1, 4, 1, 3]).partial_sort(3).to_list()
  [1, 1, 3]
  >>> flp.it([5, 1, 4, 1, 3]).partial_sort(2, descending=True).to_list()
  [5, 4]
  >>> flp.it(["bb", "a", "cc", "d"]).partial_sort_by(2, len).to_list()
  ['a', 'd']
  >>> flp.it(["bb", "a", "cc", "d"]).partial_sort_by(2, len, descending=True).to_list()
  ['bb', 'cc']
  ```
- README deviations: stable ties (stricter than MoreLINQ); eager `count` validation.
- Translation map: MoreLINQ `.PartialSort(k)` / `.PartialSortBy(k, f, OrderByDirection.Descending)` / Python `heapq.nsmallest(k, xs, key=f)`, `heapq.nlargest` / LINQ `.OrderBy(f).Take(k)` → `.partial_sort(k)` / `.partial_sort_by(k, f, descending=True)`.

## 8. Expected outcomes
- Top-k selection on all four types, provably identical to `order_by(...).take(k)` and asymptotically cheaper.
- A reusable `sorted_ties_unordered` comparison profile in the harness.
- difftest specs 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=partial_sort` and `<op>=partial_sort_by`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_partial_sort.py --hypothesis-show-statistics
uv run python -c "from flpit import flp; print(flp.it([5, 1, 4, 1, 3]).partial_sort(3).to_list())"      # [1, 1, 3]
uv run python -c "from flpit import flp; print(flp.lst([3, None, 1]).partial_sort(2).to_list())"        # [None, 1]
```

## 10. Definition of Done
DoD-std, plus: Hypothesis equivalence property against `order_by(...).take(k)`; `sorted_ties_unordered` profile implemented with its own harness self-test (a deliberately reordered tie group still MATCHes, a wrong key order is a MISMATCH).

## 11. Risks / open questions
- If N07 (`order`) decides that keyless ordering should **not** be None-aware, align `partial_sort` with it (the contract is "equal to the corresponding order + take").
- `heapq`'s stability is an implementation property documented by the "equivalent to `sorted(...)[:n]`" wording; the Hypothesis property guards it across Python 3.12 to 3.14.
- The FlpList retry-on-`TypeError` path must not swallow a `TypeError` raised for other reasons (e.g. `int` vs `str`): it retries once with the wrapper, which raises the same `TypeError` again for genuinely incomparable data.
