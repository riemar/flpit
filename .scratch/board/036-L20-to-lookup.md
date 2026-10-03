---
id: L20
title: to_lookup + Lookup type
status: todo
priority: 036
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ToLookupTests.cs @ dotnet/runtime main 6f1d9331 (23 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L20: `to_lookup` + `Lookup` type

## 1. Goal
`ToLookup` is the eager, re-queryable sibling of `GroupBy`: a one-to-many index where `lookup[key]` never fails. It is also the internal engine of `GroupBy`, `Join`, `GroupJoin` and the .NET 10 joins. This card adds the public immutable `Lookup[TKey, TElement]` (D17), makes `Grouping` a proper read-only sequence, and lands the **internal lookup builder** reused by L24 (`group_by`), L25 (`join`), L26 (`group_join`) and N04–N06.

## 2. Scope
**In:** `to_lookup(key_selector, element_selector=...)` on `_LinqOps`; new `Lookup` class (exported from `flpit`); `Grouping` upgrade (owned list storage, `__len__`, `__getitem__`, `__contains__`, O(1) `count()`); private `_build_lookup(...)` in `src/flpit/core/_lookup.py`.
**Out:** comparer overloads (D3); `group_by` refactor onto the builder (L24); null-key skipping for joins (flag added here, used by L25).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def to_lookup(self, key_selector: Callable[[TItem], TKey]) -> Lookup[TKey, TItem]: ...
@overload
def to_lookup(self, key_selector: Callable[[TItem], TKey],
              element_selector: Callable[[TItem], TElement]) -> Lookup[TKey, TElement]: ...

class Lookup(FlpIt[Grouping[TKey, TElement]], Generic[TKey, TElement]):
    def __len__(self) -> int: ...                                    # ILookup.Count
    def __getitem__(self, key: TKey) -> Grouping[TKey, TElement]: ... # missing key -> empty Grouping
    def __contains__(self, key: object) -> bool: ...                  # ILookup.Contains(key)
    def contains(self, key: TKey) -> bool: ...                        # same, LINQ spelling
    def keys(self) -> KeysView[TKey]: ...
    def values(self) -> ValuesView[Grouping[TKey, TElement]]: ...
    def items(self) -> ItemsView[TKey, Grouping[TKey, TElement]]: ...
    def apply_result_selector(
        self, result_selector: Callable[[TKey, FlpIt[TElement]], TResult]) -> FlpIt[TResult]: ...
```
`.NET` map: `ToLookup(keySelector)` / `ToLookup(keySelector, elementSelector)` → `to_lookup`; the two comparer overloads are omitted (D3). `ILookup.Count` → `len()`; `this[key]` → `lookup[key]`; `Contains(key)` → `key in lookup` / `contains(key)`; `Lookup.ApplyResultSelector` → `apply_result_selector`; `GetEnumerator` → iteration yields `Grouping`s.

### 3.2 Semantics
- `to_lookup`: kind terminal (immediate, like .NET). Buffering: full. Short-circuit: none.
- Validation (eager): `key_selector=None` → `ArgumentNoneError("key_selector")`; explicit `element_selector=None` → `ArgumentNoneError("element_selector")`.
- Per element: `key_selector(item)` then `element_selector(item)` (.NET order).
- Groups appear in **first-key-appearance order**; elements keep source order inside a group.
- `None` is a valid key (`NullKeyIncluded`, `SingleNullKeyAndElement`). Unhashable key → `TypeError` at that element.
- `Lookup` is immutable: no `__setitem__`/`__delitem__`; `lookup[missing]` returns a fresh empty `Grouping(missing, ())` and **does not insert** it, so `len` and `in` are unchanged.
- `Lookup` is **Mapping-like but not a `collections.abc.Mapping`**: iterating yields `Grouping`s (ILookup contract, so `lookup.where(lambda g: len(g) > 1)` works), whereas `Mapping.__iter__` must yield keys. `keys()/values()/items()` provide the dict-style views (read-only views of the internal dict). Documented as a deliberate design choice, not a deviation.
- `Lookup.contains(key)` overrides L06's element-wise `contains(value)`, exactly as C#'s instance `ILookup.Contains(key)` hides `Enumerable.Contains` on a `Lookup`.
- Re-iterable: iterating twice yields the same `Grouping` objects. `count()` without predicate is O(1) (`len`), identical result. Equality is identity (as in .NET).
- `Grouping` upgrade: stores its elements in a private list. Public `Grouping(key, elements)` copies into a list; the builder adopts its lists without copying (`Grouping._adopt`). New: `len(g)`, `g[i]` (Python index semantics: negative indexes count from the end, `IndexError` out of range), `x in g`, `g.count()` O(1). Not mutable (no `append`, no `__setitem__`). Note: an empty `Grouping`/`Lookup` is now falsy because it has `__len__` (Python convention).

### 3.3 Implementation sketch
```python
# _lookup.py
def _build_lookup(source, key_selector, element_selector=None, *, skip_none_keys=False):
    groups: defaultdict[Any, list[Any]] = defaultdict(list)
    for item in source:
        key = key_selector(item)
        if skip_none_keys and key is None:          # joins (L25): None never matches
            continue
        groups[key].append(item if element_selector is None else element_selector(item))
    return {k: Grouping._adopt(k, v) for k, v in groups.items()}

def to_lookup(self, key_selector, element_selector=_SENTINEL):
    ...validation...
    return Lookup._from_groups(_build_lookup(self, key_selector, None if element_selector is _SENTINEL else element_selector))
```
- `defaultdict(list)` keeps the miss path in C; one hash per element. O(n) time, O(n) memory. `Lookup._from_groups` stores the dict and passes `groups.values()` to `FlpIt.__init__` as the iterable.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.to_lookup]
category = "conversion"
kind = "terminal"
buffering = "full"
short_circuit = false
dotnet = "Enumerable.ToLookup"
python_equivalent = "d = defaultdict(list); [d[k(x)].append(x) for x in xs]"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_to_lookup.py` from `ToLookupTests.cs` (23). Expected skips:
  - `COMPARER_NOT_SUPPORTED`: `OneElementCustomComparer` (lookup by anagram must find the original key), and the five `Null*ExplicitComparer` variants (identical to their comparer-less twins once the comparer is dropped).
  - Rewritten without comparer (intent kept): `DuplicateKeys`, `RunOnce`, `EmptySource`, `SingleNullKeyAndElement`.
  - Adapted: `LookupImplementsICollection` → `isinstance(lk, collections.abc.Collection)`, `len`, no `add`/`remove`/`clear` attributes, `list(lk)` equals `lk.to_list()`; the `Contains(grouping)` assertions become `g.key in lk` (keys, by design). `SameResultsRepeatCall` compares `list(l1) == list(l2)` (Grouping equality).
  - `ApplyResultSelectorForGroup` needs `group_by(..., result_selector=...)`: skipped `OTHER: needs L24`, un-skipped by L24.
  - Target: ≥ 70 % ported now, 74 % after L24.
- **Own unit tests** (`tests/unit/test_to_lookup.py`, `test_grouping.py`): missing key returns empty grouping and does not insert; first-appearance order; `None` key; unhashable key `TypeError`; `keys()/values()/items()`; `contains` overrides element `contains`; immutability (`lk[k] = ...` is `TypeError`); `Grouping` `len`/index/negative index/`in`/`count()`; public `Grouping(key, gen)` copies so it is re-iterable.
- **Contracts**: `to_lookup` auto (terminal); `Lookup` and `Grouping` added to the contract matrix as source types (all `_LinqOps` ops work on them).
- **Typing**: `assert_type(flp.it(["a"]).to_lookup(len), Lookup[int, str])`; `assert_type(lk[1], Grouping[int, str])`; element-selector overload; `assert_type(lk.apply_result_selector(lambda k, g: g.count()), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/to_lookup.toml`: sources empty, ints with duplicate keys (`x % 3`), strings with `None` keys; probes `groups` (ordered list of `(key, [elements])`), `count`, `contains(k)` for present/missing keys, `lookup[missing]` (empty). Expected: all MATCH (both sides use first-appearance order).

## 6. Benchmarks
`tests/benchmarks/test_bench_to_lookup.py`, sizes 1e3 / 1e5, keys `x % 100`:
- `native`: `d = defaultdict(list)` + `for x in data: d[k(x)].append(x)`
- `flpit-FlpIt` / `flpit-FlpList`: `.to_lookup(k)`.
- Target ratio ≤ 1.3× (buffering).

## 7. Docs
- Docstrings for `to_lookup`, `Lookup` (class docstring explains "Mapping-like, iteration yields groupings"), each `Lookup` method, and the new `Grouping` dunders.
- Doctest:
  ```python
  >>> lk = flp.it(["ant", "bee", "cat", "ape"]).to_lookup(lambda s: s[0])
  >>> lk["a"].to_list()
  ['ant', 'ape']
  >>> lk["z"].to_list()
  []
  >>> len(lk), "b" in lk
  (3, True)
  >>> [g.key for g in lk]
  ['a', 'b', 'c']
  ```
- Translation map: `defaultdict(list)` grouping / `.ToLookup(k)` → `.to_lookup(k)`.

## 8. Expected outcomes
- `Lookup` exported and typed; `Grouping` is a read-only sequence.
- `_build_lookup` available for L24/L25/L26/N04–N06.
- ~17 ported tests plus own tests green.

## 9. Verification
VERIFY-std with `<op>=to_lookup`, plus:
```bash
uv run pytest -q tests/nettests/test_to_lookup.py tests/unit/test_grouping.py -rs | tail -3
uv run python -c "from flpit import flp; lk = flp.it([1, 2, 3]).to_lookup(lambda x: x % 2); print(lk[1].to_list(), len(lk[5]), len(lk))"   # [1, 3] 0 2
```

## 10. Definition of Done
DoD-std, plus `Lookup` and `Grouping` docstrings pass the F06 non-empty-docs check, and `rules.md` documents `_build_lookup` as the single grouping engine.

## 11. Risks / open questions
- Making `Grouping` sized changes truthiness of empty groupings (`if group:`). Empty groupings only arise from `lookup[missing]` and `group_join`, so the change is low-risk; it is listed in `CHANGELOG.md`.
- `Grouping` storing a list means `Grouping(key, infinite_gen)` now hangs at construction; the constructor is rarely used directly and the docstring says it materialises.
