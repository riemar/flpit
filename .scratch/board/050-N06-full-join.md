---
id: N06
title: full_join
status: todo
priority: 050
effort: M
depends_on: [F05, F06, F07, F08, F09, L20, N04]
upstream:
  dotnet: FullJoinTests.cs @ dotnet/runtime main 6f1d9331 (27 [Fact]/[Theory])
  morelinq: FullJoin.cs (reference only, D7)
pr:
---

# N06: `full_join`

## 1. Goal
`FullJoin` (runtime `main`, shipping with .NET 11) completes the outer-join family: every element of both sides appears, matched where keys agree and paired with "nothing" otherwise. It is the reconciliation operator (diff two datasets by id). It reuses N04's `JoinPair`, validation and test scaffolding; the new parts are the "unmatched inner" tail and its ordering rules, which are subtle and pinned down below from `FullJoin.cs` at the oracle SHA.

## 2. Scope
**In:** `full_join` on `_LinqOps`, tuple form and result-selector form.
**Out:** comparer overloads (D3). Mirroring .NET's empty-*array* shortcuts (see §3.2, Risks).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def full_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
) -> FlpIt[JoinPair[TItem | None, TInner | None]]: ...
@overload
def full_join(
    self,
    inner: Iterable[TInner],
    outer_key_selector: Callable[[TItem], TKey],
    inner_key_selector: Callable[[TInner], TKey],
    result_selector: Callable[[TItem | None, TInner | None], TResult],
) -> FlpIt[TResult]: ...
```
| .NET overload (main) | flpit |
|---|---|
| `FullJoin(inner, oKey, iKey, resultSelector, comparer = null)` | `full_join(inner, o_key, i_key, result_selector)` |
| `FullJoin(inner, oKey, iKey, comparer = null)` → `(Outer?, Inner?)` | `full_join(inner, o_key, i_key)` → `JoinPair` |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (inner fully buffered, outer streamed). Short-circuit: n/a.
- Validation (eager, .NET order): `inner`, `outer_key_selector`, `inner_key_selector`, `result_selector` → `ArgumentNoneError(<name>)`.
- Enumeration order (general path of `FullJoin.cs`): on the first `next()`, **inner is enumerated first and completely** (`inner_key_selector` once per element) into a lookup that **keeps `None`-key elements as their own group**; then outer is streamed (`outer_key_selector` once per element); finally the unmatched inner elements are yielded. Unlike `left_join`, an empty outer does not skip the inner side (the inner elements are the output).
- Output order:
  1. Outer order; per outer element its matches in inner order, or one `(outer, None)` if it has none. An outer `None` key never matches.
  2. Then every inner group that no outer element matched, **in group order** (order of first occurrence of each key, the `None`-key group included at its first-occurrence position), elements within a group in inner order, each as `(None, inner)`. Example: unmatched inner `[a1(k1), b(k2), a2(k1)]` yields `a1, a2, b`, not raw inner order.
- Missing side is `None` on either side (shared deviation with N04/N05). Python key equality/hashing; unhashable keys raise `TypeError` during enumeration.
- Re-enumeration re-enumerates both sides; a one-shot inner is empty on the second pass.
- **.NET quirk not mirrored**: when the outer (or inner) argument is an *empty array* at call time, .NET takes a shortcut that yields the other side in raw source order without calling its key selector. flpit always uses the general path, so for an empty outer with non-adjacent duplicate inner keys the order is grouped, and key selectors are always called once per element. Identical to .NET for every non-array source. Recorded in the difftest spec, not in README (implementation detail, not a contract).

### 3.3 Implementation sketch
```python
def full_join(self, inner, outer_key_selector, inner_key_selector, result_selector=_SENTINEL):
    ...validation as left_join...
    src = self._source()
    make = _make_pair if result_selector is _SENTINEL else (lambda pair: result_selector(*pair))
    def _generator():
        lookup = _build_lookup(inner, inner_key_selector)         # L20 builder, skip_none_keys=False: None group KEPT
        get = lookup.get
        matched: set[int] = set()                                  # id() of matched Grouping objects
        for item in src:
            key = outer_key_selector(item)
            group = None if key is None else get(key)
            if group is None:
                yield make((item, None))
            else:
                matched.add(id(group))
                for m in group: yield make((item, m))
        if len(matched) < len(lookup):
            for group in lookup.values():
                if id(group) not in matched:
                    for m in group: yield make((None, m))
    return FlpIt(_FactoryIterable(_generator))
```
- Uses L20's `_build_lookup` with its default `skip_none_keys=False` (the `to_lookup` mode, like .NET `Lookup.Create`), not the join mode; explicit `key is None` check on the outer side because the `None` group exists in the lookup.
- Matched groups tracked by `id()` of the `Grouping` (groupings stay alive in `lookup`, so ids are stable), mirroring .NET's `HashSet<Grouping>`; avoids rehashing keys. Tail skipped entirely when every group matched.
- In the final code the result-selector path calls `result_selector(o, i)` directly (two specialised loops) instead of the `make(*pair)` indirection shown above; the sketch only shows the ordering logic.
- Time O(|outer| + |inner| + |output|); memory O(|inner| + matched groups).
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.full_join]
category = "join"
kind = "intermediate"
buffering = "partial"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.FullJoin"
morelinq = "MoreEnumerable.FullJoin"
python_equivalent = "left join, then inner items whose key group never matched (grouped by key)"
since = "0.4.0"
card = "N06"
notes = "dotnet/runtime main only (.NET 11); unmatched inner yielded grouped by key; missing side None."
```

## 4. Tests
- **Ported** `tests/nettests/test_full_join.py` from `FullJoinTests.cs` (27 cases), reusing N04's record helpers:
  - `NO_VALUE_TYPES` (adapted): struct defaults (`orderID = 0`, `name = null`) and `TupleOverloadMatchesResultSelector`'s `(1, 0)` / `(0, 4)` become `(1, None)` / `(None, 4)`.
  - Comparer cases (`CustomComparer`, `TupleOverloadWithComparer`, `NullKeysAreUnmatchedButPreserved`) rewritten with key selectors (anagram key, `str.lower`, `None` for `#` items), intent preserved.
  - `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(query, Iterator)`.
  - Expected skips: none. Target: 27/27 (100 %).
- **Own unit tests** (`tests/unit/test_full_join.py`):
  - Grouped tail order (`[a1(k1), b(k2), a2(k1)]` example), `None`-key group position in the tail.
  - Empty outer: inner still enumerated, all `(None, i)`; empty inner: all `(o, None)`, `outer_key_selector` called per element.
  - Inner fully enumerated before the first outer pull (call-order log).
  - Every element of both sides appears exactly once as a non-`None` side when keys are unique (property test on random small inputs).
  - Consistency: `full_join` minus the tail equals `left_join` (same prefix, same order).
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).full_join(["a"], str, str), FlpIt[JoinPair[int | None, str | None]])`.

## 5. Differential harness
`difftest/specs/full_join.toml`: domains and probes as N04 plus a "duplicate non-adjacent inner keys" domain. **Oracle availability (README open question 2):** `FullJoin` is not in the .NET 10 GA SDK the harness pins, so every case is `UNCOMPARABLE` with reason `"FullJoin requires .NET 11 (runtime main)"` until the oracle SDK moves to .NET 11 (GA expected Nov 2026; a preview SDK lane in F09 is an option). Until then correctness rests on the 27 ported upstream tests plus own tests. When enabled: C# sources for empty-side domains are wrapped as non-array enumerables (`.Select(x => x)`) so the general path runs; an extra "empty outer array" case is `EXPECTED_DIFFERENCE` (shortcut quirk, §3.2).

## 6. Benchmarks
`tests/benchmarks/test_bench_full_join.py`, sizes 1e3 and 1e5, outer keys `x`, inner keys `x + size // 2` (half overlap):
- `native`: `lk = defaultdict(list)` over inner; list comprehension over outer as in N04 while recording matched keys in a `set`; then `[(None, i) for k, g in lk.items() if k not in matched for i in g]`.
- `flpit-FlpIt` / `flpit-FlpList`: tuple form and result-selector form.
- Target ratio ≤ 1.5× tuple form, ≤ 1.3× result-selector form.

## 7. Docs
- Docstring: "Correlates both sequences by key, keeping elements of either side that have no match."; `.NET: Enumerable.FullJoin (.NET 11 / runtime main)`; Execution (inner buffered first, outer streamed, unmatched inner last and grouped by key). Example:
  ```python
  >>> flp.it([1, 2, 3]).full_join([2, 3, 4], lambda o: o, lambda i: i).to_list()
  [JoinPair(outer=1, inner=None), JoinPair(outer=2, inner=2), JoinPair(outer=3, inner=3), JoinPair(outer=None, inner=4)]
  ```
- README matrix row (note ".NET 11"); shared deviation entry from N04.
- Translation map: `.FullJoin(...)` / pandas `merge(how="outer")` → `.full_join(...)`.

## 8. Expected outcomes
- `full_join` on all four types; 27 ported .NET tests green; benchmark recorded.
- Difftest spec registered with documented `UNCOMPARABLE` status and a follow-up to flip it once the oracle runs .NET 11.

## 9. Verification
VERIFY-std with `<op>=full_join` (the difftest step reports UNCOMPARABLE with the reason, 0 MISMATCH), plus:
```bash
uv run pytest -q tests/nettests/test_full_join.py -rs      # expect 0 skipped
uv run python -c "from flpit import flp; print(flp.it([1]).full_join([2, 2], lambda o: o, lambda i: i).to_list())"
# [JoinPair(outer=1, inner=None), JoinPair(outer=None, inner=2), JoinPair(outer=None, inner=2)]
```

## 10. Definition of Done
DoD-std (difftest: UNCOMPARABLE with reason accepted), plus a tracking issue "enable full_join difftest on .NET 11 oracle" linked from the spec.

## 11. Risks / open questions
- Semantics are from runtime `main`, not a shipped release; the API or ordering could still change before .NET 11 GA. Mitigation: the ported tests pin the SHA; re-check `FullJoin.cs` when the oracle moves to .NET 11.
- The empty-array shortcut quirk (§3.2) is deliberately not mirrored; if .NET documents it as contract, revisit with a `Sized`-and-empty check at enumeration time.
