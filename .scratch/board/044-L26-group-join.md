---
id: L26
title: group_join
status: todo
priority: 044
effort: M
depends_on: [F05, F06, F07, F08, F09, L20, L25]
upstream:
  dotnet: GroupJoinTests.cs @ dotnet/runtime main 6f1d9331 (34 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L26: `group_join`

## 1. Goal
`GroupJoin` correlates each outer element with the **collection** of its matching inner elements (C# `join ... into g`). It is the building block for hierarchical results (customer with its orders) and the classic way to express a left outer join before .NET 10's `LeftJoin`. It reuses L25's join lookup (`None` keys never match) and L20's `Grouping`.

## 2. Scope
**In:** `group_join(inner, outer_key_selector, inner_key_selector, result_selector=...)` on `_LinqOps`.
**Out:** comparer overloads (D3); `left_join` (N04), which is a separate operator.

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def group_join(self, inner: Iterable[TInner],
               outer_key_selector: Callable[[TItem], TKey],
               inner_key_selector: Callable[[TInner], TKey]) -> FlpIt[Grouping[TItem, TInner]]: ...
@overload
def group_join(self, inner: Iterable[TInner],
               outer_key_selector: Callable[[TItem], TKey],
               inner_key_selector: Callable[[TInner], TKey],
               result_selector: Callable[[TItem, FlpIt[TInner]], TResult]) -> FlpIt[TResult]: ...
```
`.NET` overload map: `GroupJoin(inner, ok, ik, resultSelector)` → 4-argument form; `GroupJoin(inner, ok, ik)` returning `IEnumerable<IGrouping<TOuter, TInner>>` → 3-argument form returning `Grouping`s **keyed by the outer element**; comparer overloads (including the optional `comparer = null` on the grouping form) omitted (D3). As with L25's tuple `Join`, the grouping-returning overload exists only in `main` / .NET 11 previews, not .NET 10 GA: verified by ported tests, `UNCOMPARABLE` in the harness until the oracle SDK has it.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (inner buffered, outer streamed). Short-circuit: stops pulling outer when the consumer stops.
- Source-access order (as .NET's `GroupJoinIterator`): on the first `next()`, pull the first outer element; if outer is empty, `inner` is never iterated. Otherwise build the join lookup from all of `inner` (`None` inner keys dropped), then yield **one result per outer element**, in outer order, including outer elements without matches (empty group). Unlike `join`, an empty lookup does not stop enumeration.
- `result_selector(outer, group)` receives a re-iterable, sized `Grouping` of the matching inner elements in inner order (an empty `Grouping` when there is no match or the outer key is `None`). Typed as `FlpIt[TInner]`.
- Grouping form: `Grouping(key=outer_element, elements=matches)`; groups of outer elements with equal keys share the same immutable element list (no copy).
- `None` keys never match (mirrors .NET; `SelectorsReturnNull` yields empty groups; `OuterInnerBothSingleNullElement` still yields the outer element).
- Validation (eager): `inner is None` → `ArgumentNoneError("inner")`; key selectors and explicit `result_selector=None` → `ArgumentNoneError(<name>)`.
- Unhashable key → `TypeError` (inner: during the build; outer: at that element).
- Re-enumeration re-reads both sources.

### 3.3 Implementation sketch
```python
def group_join(self, inner, outer_key_selector, inner_key_selector, result_selector=_SENTINEL):
    ...validation...
    def _generator():
        it = iter(self)
        first = next(it, _MISSING)
        if first is _MISSING:
            return
        lookup = _build_lookup(inner, inner_key_selector, skip_none_keys=True)   # L20/L25
        get = lookup.get
        for outer in chain((first,), it):
            key = outer_key_selector(outer)
            group = None if key is None else get(key)
            if result_selector is _SENTINEL:
                yield Grouping._adopt(outer, group._elements if group else [])
            else:
                yield result_selector(outer, group if group is not None else Grouping._adopt(key, []))
    return FlpIt(_FactoryIterable(_generator))
```
- O(N + M) time, O(M) memory; no per-outer copying of matches.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.group_join]
category = "join"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.GroupJoin"
python_equivalent = "idx = defaultdict(list) over inner; [(o, idx.get(ok(o), [])) for o in outer]"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_group_join.py` from `GroupJoinTests.cs` (34). Records become frozen dataclasses; `JoinRec` arrays become tuples built inside the result selector. Comparer tests rewritten with `anagram_key` in both key selectors (`CustomComparer`, `GroupJoinWithoutResultSelector_CustomComparer`); `NullComparer`, `NullComparerRunOnce`, `OuterInnerBothSingleNullElement` use default equality. `Outer*Null` tests map to `flp.it(None)` → `SourceNoneError`. `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(q, Iterator)`. `GroupJoinWithoutResultSelector_*` cover the grouping form (`result[i].key`, `len(result[i])`, `CanIterateMultipleTimes`).
  - Expected skips: none. Target: 100 % ported.
- **Own unit tests** (`tests/unit/test_group_join.py`): empty outer never touches `inner`; outer elements without matches yield empty groups (also when the lookup is empty: contrast with `join`); `None` keys; groups are re-iterable and sized; equal outer keys share contents but have distinct `Grouping` keys; result selector called once per outer element; left-outer-join recipe `group_join(inner, ok, ik, lambda o, g: (o, g)).select_many(lambda t: t[1].default_if_empty(), lambda t, i: (t[0], i))` (L12, L17) yields `(outer, None)` rows for unmatched outers.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).group_join(["a"], lambda o: o, len), FlpIt[Grouping[int, str]])`; with result selector `lambda o, g: (o, g.count())` → `FlpIt[tuple[int, int]]`.

## 5. Differential harness
`difftest/specs/group_join.toml`: same outer/inner domains as `join.toml`; probes `result` (outer, list of inner), `inner_enumerated`, `outer_elements_pulled`, `result_selector_calls`. Grouping form: `UNCOMPARABLE: overload absent in .NET 10 GA`. Expected: all MATCH otherwise.

## 6. Benchmarks
`tests/benchmarks/test_bench_group_join.py`, sizes 1e3 / 1e5 outer, inner = 3 × outer with 3 matches per key:
- `native`: `idx = defaultdict(list)` over inner, then `[(o, len(idx.get(ok(o), ()))) for o in outer]`
- `flpit-FlpIt` / `flpit-FlpList`: `.group_join(inner, ok, ik, lambda o, g: (o, len(g))).to_list()`.
- Target ratio ≤ 1.3×.

## 7. Docs
- Docstring: `.NET: Enumerable.GroupJoin`; one result per outer element; `None` keys; grouping form keyed by the outer element (.NET 11 note); left-join recipe pointing to `left_join` (N04) once available.
- Doctest:
  ```python
  >>> people = [("Ann", 1), ("Bob", 2), ("Cid", 3)]
  >>> orders = [(1, "tea"), (3, "pie"), (1, "jam")]
  >>> flp.it(people).group_join(orders, lambda p: p[1], lambda o: o[0],
  ...     lambda p, os: (p[0], os.select(lambda o: o[1]).to_list())).to_list()
  [('Ann', ['tea', 'jam']), ('Bob', []), ('Cid', ['pie'])]
  ```
- Translation map: dict-index + `.get(k, [])` / `join ... into g` / `.GroupJoin(...)` → `.group_join(...)`.

## 8. Expected outcomes
- `group_join` on all types with both forms; 34 ported tests green.

## 9. Verification
VERIFY-std with `<op>=group_join`, plus:
```bash
uv run pytest -q tests/nettests/test_group_join.py -rs | tail -3
uv run python -c "from flpit import flp; print([(g.key, g.to_list()) for g in flp.it([1, 2]).group_join([1, 1], lambda x: x, lambda y: y)])"   # [(1, [1, 1]), (2, [])]
```

## 10. Definition of Done
DoD-std.

## 11. Risks / open questions
- Passing a `Grouping` (whose `key` is the join key) to `result_selector` exposes one more attribute than .NET's `IEnumerable<TInner>`; harmless, documented.
- Shared element lists between groupings rely on `Grouping` immutability (L20); a test guards it.
