---
id: L24
title: group_by overloads (element/result selector)
status: todo
priority: 040
effort: M
depends_on: [F05, F06, F07, F08, F09, L20]
upstream:
  dotnet: GroupByTests.cs @ dotnet/runtime main 6f1d9331 (59 [Fact]/[Theory], +1 [ConditionalFact] GroupingKeyIsPublic)
  morelinq: n/a
pr:
---

# L24: `group_by` overloads (element/result selector)

## 1. Goal
`group_by` exists only as `group_by(key_selector)`, so projecting elements (`group_by(lambda o: o.customer, lambda o: o.total)`) or shaping each group (`group_by(k, result_selector=lambda key, xs: (key, xs.sum()))`) needs an extra `select`. This card adds the three missing .NET overload shapes, moves `group_by` onto the shared lookup builder (L20), fixes lazy argument validation, and ports `GroupByTests.cs` (no tests today).

## 2. Scope
**In:** `group_by(key_selector, element_selector=..., *, result_selector=...)` on `_LinqOps`; refactor onto `_build_lookup`; full port of `GroupByTests.cs` (including the `Grouping` IList tests, enabled by L20's read-only sequence protocol). Also un-skips L20's `ApplyResultSelectorForGroup`.
**Out:** comparer overloads (D3); MoreLINQ `GroupAdjacent` (M09).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def group_by(self, key_selector: Callable[[TItem], TKey]) -> FlpIt[Grouping[TKey, TItem]]: ...
@overload
def group_by(self, key_selector: Callable[[TItem], TKey],
             element_selector: Callable[[TItem], TElement]) -> FlpIt[Grouping[TKey, TElement]]: ...
@overload
def group_by(self, key_selector: Callable[[TItem], TKey], *,
             result_selector: Callable[[TKey, FlpIt[TItem]], TResult]) -> FlpIt[TResult]: ...
@overload
def group_by(self, key_selector: Callable[[TItem], TKey],
             element_selector: Callable[[TItem], TElement], *,
             result_selector: Callable[[TKey, FlpIt[TElement]], TResult]) -> FlpIt[TResult]: ...
```
`.NET` overload map (8): `GroupBy(k)` → `group_by(k)`; `GroupBy(k, elementSelector)` → `group_by(k, e)`; `GroupBy(k, resultSelector)` → `group_by(k, result_selector=r)`; `GroupBy(k, e, r)` → `group_by(k, e, result_selector=r)`; the four comparer overloads are omitted (D3). `result_selector` is keyword-only because Python cannot tell `GroupBy(k, elementSelector)` from `GroupBy(k, resultSelector)` by position (.NET distinguishes them by delegate arity).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full: on the first `next()` the whole source is consumed and all groups are built; then groups (or results) are yielded. Short-circuit: none on the source (`group_by(k).first()` still reads everything, as in .NET).
- Validation (eager): `key_selector=None` → `ArgumentNoneError("key_selector")`; explicit `element_selector=None` / `result_selector=None` → `ArgumentNoneError(...)`. **Bug fix**: today `group_by(None)` fails only on enumeration.
- Call order while building: `key_selector(item)` then `element_selector(item)` per element; `result_selector(key, group)` is called lazily, once per group, as results are pulled.
- `result_selector` receives the `Grouping` itself (typed as `FlpIt[TElement]`): re-iterable, sized, and LINQ-capable (`xs.sum()`, `xs.count()`).
- Group order: first-key-appearance; element order: source order. `None` keys form a normal group (`SomeDuplicateKeysIncludingNulls`). Unhashable key → `TypeError` during the build.
- Re-enumeration rebuilds all groups (new `Grouping` objects), like .NET's `GroupByIterator`.
- `Grouping` (from L20): `len`, `g[i]`, `in`, immutable; `g[-1]` follows Python indexing (.NET throws `ArgumentOutOfRangeException`); out of range raises `IndexError`.

### 3.3 Implementation sketch
```python
def group_by(self, key_selector, element_selector=_SENTINEL, *, result_selector=_SENTINEL):
    ...validation...
    elem = None if element_selector is _SENTINEL else element_selector
    if result_selector is _SENTINEL:
        return FlpIt(_FactoryIterable(lambda: iter(_build_lookup(self, key_selector, elem).values())))
    def _generator():
        for key, group in _build_lookup(self, key_selector, elem).items():
            yield result_selector(key, group)
    return FlpIt(_FactoryIterable(_generator))
```
- One `defaultdict` pass: O(n) time, O(n) memory. The previous `setdefault(key, [])` allocated a list per element; the builder avoids that.
- **FlpList fast path**: none (the `FlpList.group_by` delegate is removed by F05's mixin).

### 3.4 Registry entry
```toml
[operators.group_by]              # existing entry, updated
category = "grouping"
kind = "intermediate"
buffering = "full"
short_circuit = false
dotnet = "Enumerable.GroupBy"
python_equivalent = "defaultdict(list) grouping (itertools.groupby only groups adjacent keys)"
overloads = ["key", "key+element", "key+result", "key+element+result"]
```

## 4. Tests
- **Ported** `tests/nettests/test_group_by.py` from `GroupByTests.cs` (59). `AssertGroupingCorrect` becomes a helper comparing first-appearance groups. Comparer tests are rewritten with keys (D3, intent preserved): `AllElementsSameKey` drops the comparer (all keys equal); `DuplicateKeysCustomComparer(+RunOnce)` and `AllElementsSameKeyResultSelectorUsed` use `anagram_key` (L21 helper); their result selectors only use `len(key)`, which anagrams share. Null-argument tests that pass a comparer keep their intent without it. `NullComparer*` use the default equality.
  - Adapted: `Grouping_IList_IsReadOnly` → `not isinstance(g, MutableSequence)`; `Grouping_IList_NotSupported` → `append`/`__setitem__`/`__delitem__` unavailable (`AttributeError`/`TypeError`); `Grouping_IList_IndexGetterOutOfRange` keeps `g[23]` → `IndexError`, while `g[-1]` asserts Python semantics (deviation note); `EnumerateGrouping` replaces `Reset()` with a fresh `iter(g)`; `SameResultsRepeatCallsStringQuery` builds `q` with `select_many`.
  - Expected skips: `OTHER` (no `IndexOf`; `Grouping` exposes no `index` method): `Grouping_IList_IndexOf`. `GroupingKeyIsPublic` ([ConditionalFact]) ported as `hasattr(type(g), "key")`.
  - Target: ≥ 95 % ported (58/59).
- **Own unit tests** (`tests/unit/test_group_by.py`): eager validation for all three callables; result selector called lazily (`group_by(k, result_selector=f).first()` calls `f` once but key selector `n` times); groups rebuilt per enumeration; result selector receives a `Grouping` with correct `key` and `len`; `None` key group; element selector call count equals source length.
- **Contracts**: auto via registry (deferral; full buffering).
- **Typing**: one `assert_type` per overload, e.g. `assert_type(flp.it(["a"]).group_by(len, str.upper), FlpIt[Grouping[int, str]])`, `assert_type(flp.it(["a"]).group_by(len, result_selector=lambda k, xs: (k, xs.count())), FlpIt[tuple[int, int]])`.

## 5. Differential harness
`difftest/specs/group_by.toml`: sources empty, unique keys, all-same key, `x % 3`, strings with `None` keys; overloads all four; probes `result` (ordered list of `(key, elements)` or results), `key_selector_calls`, `result_selector_calls` after `.first()`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_group_by.py`, sizes 1e3 / 1e5, keys `x % 100`:
- `native`: `d = defaultdict(list)` loop, then `[(k, sum(v)) for k, v in d.items()]` for the result-selector case.
- `flpit-FlpIt` / `flpit-FlpList`: `.group_by(k).to_list()` and `.group_by(k, result_selector=lambda k, xs: xs.sum()).to_list()`.
- Target ratio ≤ 1.3× (buffering); the existing ordering/grouping benchmark is kept.

## 7. Docs
- Docstring: `.NET: Enumerable.GroupBy` with the overload table; why `result_selector` is keyword-only; full buffering at first iteration; first-appearance order; `itertools.groupby` contrast (adjacent only).
- Doctests:
  ```python
  >>> flp.it(["ant", "bee", "ape"]).group_by(lambda s: s[0], len).select(lambda g: (g.key, g.to_list())).to_list()
  [('a', [3, 3]), ('b', [3])]
  >>> flp.it([1, 2, 3, 4, 5]).group_by(lambda x: x % 2, result_selector=lambda k, xs: (k, xs.sum())).to_list()
  [(1, 9), (0, 6)]
  ```
- Translation map: `defaultdict(list)` loop / `.GroupBy(k, e, (key, xs) => ...)` → `.group_by(k, e, result_selector=...)`.
- README "Execution Characteristics" table: unchanged (still deferred + buffering).

## 8. Expected outcomes
- Four overload shapes, typed; `group_by(None)` raises eagerly.
- ~58 ported tests green; L20's `ApplyResultSelectorForGroup` un-skipped.

## 9. Verification
VERIFY-std with `<op>=group_by`, plus:
```bash
uv run pytest -q tests/nettests/test_group_by.py tests/nettests/test_to_lookup.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it('abca').group_by(lambda c: c, result_selector=lambda k, g: k * len(g)).to_list())"   # ['aa', 'b', 'c']
```

## 10. Definition of Done
DoD-std, plus `group_by` and `to_lookup` share `_build_lookup` (no second grouping loop in the codebase).

## 11. Risks / open questions
- Keyword-only `result_selector` is a Python-specific API shape; documented in the translation map. Positional use raises `TypeError` (too many positional arguments), which is the intended guard.
- `Grouping` negative indexing differs from .NET; listed in README deviations (owned by L20, referenced here).
