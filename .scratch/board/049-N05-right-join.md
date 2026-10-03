---
id: N05
title: right_join
status: todo
priority: 049
effort: M
depends_on: [F05, F06, F07, F08, F09, L20, N04]
upstream:
  dotnet: RightJoinTests.cs @ dotnet/runtime main 6f1d9331 (32 [Fact]/[Theory])
  morelinq: RightJoin.cs (reference only, D7; superseded by the .NET 10 operator)
pr:
---

# N05: `right_join`

## 1. Goal
`RightJoin` (.NET 10) is the mirror of `left_join` (N04): every **inner** element, paired with each matching outer element or with "nothing". It keeps the fluent chain anchored on the outer sequence when the "keep all" side is the argument (e.g. `orders.right_join(customers, ...)` to list every customer). It reuses N04's `JoinPair`, lookup helper and test scaffolding, so it is mostly a careful mirror plus the ported tests.

## 2. Scope
**In:** `right_join` on `_LinqOps`, tuple form and result-selector form.
**Out:** comparer overloads (D3). Everything N04 lists as out.

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def right_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
) -> FlpIt[JoinPair[TItem | None, TInner]]: ...
@overload
def right_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
    result_selector: Callable[[TItem | None, TInner], TResult],
) -> FlpIt[TResult]: ...
```
| .NET overload | flpit |
|---|---|
| `RightJoin(inner, oKey, iKey, resultSelector)` | `right_join(inner, o_key, i_key, result_selector)` |
| `RightJoin(inner, oKey, iKey, resultSelector, comparer)` | omitted (D3) |
| `RightJoin(inner, oKey, iKey, comparer = null)` → `(Outer?, Inner)` | `right_join(inner, o_key, i_key)` → `JoinPair` |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (the **outer** side, i.e. `self`, is buffered into a lookup; `inner` is streamed). Short-circuit: n/a.
- Validation (eager, .NET order): `inner` → `ArgumentNoneError("inner")`; then `outer_key_selector`, `inner_key_selector`, `result_selector`.
- Enumeration order (mirrors `RightJoin.cs`): pull the first **inner** element; if inner is empty, **the outer side (`self`) is never enumerated** and `outer_key_selector` is never called. Otherwise build the outer lookup (all of `self`, `outer_key_selector` once per element), then stream inner (`inner_key_selector` once per element).
- Output order: inner order; for each inner element its matching outer elements in outer order; an unmatched inner element yields once with `outer=None`.
- `None` keys never match (outer `None`-key elements dropped from the lookup; inner `None`-key elements yield `(None, inner)`).
- Missing side is `None` (shared deviation with N04). Python equality/hashing for keys; unhashable keys raise `TypeError` during enumeration.
- Re-enumeration re-enumerates both sides; a one-shot `self` source is empty on the second pass (every inner element unmatched).
- On an `OrderedIt` receiver, the lookup is built from the sorted outer sequence, so matches per inner element come out in sorted outer order.

### 3.3 Implementation sketch
```python
def right_join(self, inner, outer_key_selector, inner_key_selector, result_selector=_SENTINEL):
    ...same validation as left_join...
    src = self._source()
    def _generator():
        it = iter(inner)
        first = next(it, _MISSING)
        if first is _MISSING:
            return
        get = _build_lookup(src, outer_key_selector, skip_none_keys=True).get   # L20 builder
        for item in chain((first,), it):
            matches = get(inner_key_selector(item))
            if matches is None:
                yield _make_pair((None, item)) if result_selector is _SENTINEL else result_selector(None, item)
            elif result_selector is _SENTINEL:
                for m in matches: yield _make_pair((m, item))
            else:
                for m in matches: yield result_selector(m, item)
    return FlpIt(_FactoryIterable(_generator))
```
- Same helper, same complexity as N04: O(|outer| + |inner| + |output|) time, O(|outer|) memory.
- Note the argument order of the result selector stays `(outer, inner)` even though inner drives the loop (as in .NET).
- **FlpList fast path**: none.
- Consider factoring the N04/N05 bodies into one private `_half_join(driver, lookup_src, driver_key, lookup_key, make)`; only if it keeps both readable and costs nothing measurable.

### 3.4 Registry entry
```toml
[operators.right_join]
category = "join"
kind = "intermediate"
buffering = "partial"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.RightJoin"
morelinq = "MoreEnumerable.RightJoin"
python_equivalent = "lk = defaultdict(list) over outer; [(o, i) for i in inner for o in lk.get(k(i)) or [None]]"
since = "0.4.0"
card = "N05"
notes = "Self (outer) is buffered, inner streamed; missing outer is None; None keys never match."
```

## 4. Tests
- **Ported** `tests/nettests/test_right_join.py` from `RightJoinTests.cs` (32 cases), using N04's helpers (`create_join_rec` maps a missing `CustomerRec` to `name=None`, matching `new JoinRec{ name = null }`):
  - `NO_VALUE_TYPES` (adapted, not skipped): struct defaults as in N04.
  - Comparer cases rewritten with key selectors (anagram key, `str.lower` with `None` for `#` items), intent preserved (D3).
  - `NullKeysRemainUnmatched` expectation `["<null>:#i1", "a:A", "<null>:#i2", "<null>:b"]` ported verbatim.
  - `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(query, Iterator)`.
  - Expected skips: none. Target: 32/32 (100 %).
- **Own unit tests** (`tests/unit/test_right_join.py`): empty inner never enumerates `self` (`NoIterList`/`Bomb` outer) and never calls `outer_key_selector`; outer duplicates come out in outer order per inner element; `OrderedIt` receiver; one-shot outer on re-enumeration; symmetry property `a.right_join(b, ka, kb).to_list() == b.left_join(a, kb, ka).select(lambda p: (p.inner, p.outer)).to_list()` on random small inputs, including `None` keys.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).right_join(["a"], str, str), FlpIt[JoinPair[int | None, str]])`.

## 5. Differential harness
`difftest/specs/right_join.toml`: same domains and probes as `left_join` (N04), including the enumeration-order log that proves `self` is untouched for an empty inner. Nullable element types on the C# side. Expected: all MATCH (.NET 10 GA has `RightJoin`; tuple overload mapped to the result-selector overload if the GA SDK lacks it).

## 6. Benchmarks
`tests/benchmarks/test_bench_right_join.py`, same data shapes as N04:
- `native`: `lk = defaultdict(list)`; `for o in outer: lk[okey(o)].append(o)`; `[(o, i) for i in inner for o in lk.get(ikey(i)) or (None,)]`.
- `flpit-FlpIt` / `flpit-FlpList`: tuple form and result-selector form.
- Target ratio ≤ 1.5× tuple form, ≤ 1.3× result-selector form.

## 7. Docs
- Docstring: "Correlates inner elements with matching outer elements by key, keeping inner elements without a match."; `.NET: Enumerable.RightJoin`; Execution note that the receiver is the buffered side and is not enumerated when `inner` is empty. Example:
  ```python
  >>> flp.it([1, 2]).right_join([2, 3], lambda o: o, lambda i: i).to_list()
  [JoinPair(outer=2, inner=2), JoinPair(outer=None, inner=3)]
  ```
- README matrix row; shared deviation entry from N04.
- Translation map: `.RightJoin(...)` → `.right_join(...)`; "or swap and `left_join`".

## 8. Expected outcomes
- `right_join` on all four types; 32 ported .NET tests green; benchmark recorded; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=right_join`, plus:
```bash
uv run pytest -q tests/nettests/test_right_join.py -rs     # expect 0 skipped
uv run python -c "from flpit import flp; print(flp.it([1, 2]).right_join([2, 3], lambda o: o, lambda i: i).to_list())"
# [JoinPair(outer=2, inner=2), JoinPair(outer=None, inner=3)]
```

## 10. Definition of Done
DoD-std, plus the symmetry property test with `left_join` passes.

## 11. Risks / open questions
- Users may expect `right_join` to buffer the argument (like `left_join` does); the docstring states explicitly that the receiver is buffered. Matches .NET.
