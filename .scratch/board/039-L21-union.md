---
id: L21
title: union / union_by
status: todo
priority: 039
effort: M
depends_on: [F05, F06, F07, F08, F09, L06]
upstream:
  dotnet: UnionTests.cs @ dotnet/runtime main 6f1d9331 (41 [Fact]/[Theory]; UnionBy tests live in the same file)
  morelinq: n/a
pr:
---

# L21: `union` / `union_by`

## 1. Goal
First of the three set operators (L21–L23). `union` gives an order-preserving, streaming, distinct concatenation, which Python's `set | set` cannot (it loses order and is eager). `union_by(key)` (.NET 6) carries the comparer use-case under D3. This card also lands the **shared set-operation helper** (`src/flpit/core/_setops.py`) reused by `intersect`/`except_` and, optionally, by `distinct`/`distinct_by` (B05).

## 2. Scope
**In:** `union(second)` and `union_by(second, key_selector)` on `_LinqOps`; `_setops.py` with the seen-set streaming primitive and the shared argument checks.
**Out:** comparer overloads (D3); .NET's `UnionIteratorN` chain collapsing (`a.Union(b).Union(c)` merged into one iterator), an internal optimisation with identical results.

## 3. Detailed design
### 3.1 Signatures
```python
def union(self, second: Iterable[TItem]) -> FlpIt[TItem]: ...
def union_by(self, second: Iterable[TItem], key_selector: Callable[[TItem], TKey]) -> FlpIt[TItem]: ...
```
`.NET` overload map: `Union(second)` → `union`; `UnionBy(second, keySelector)` → `union_by`; `Union(second, comparer)` and `UnionBy(..., comparer)` omitted (D3: fold the comparer into `key_selector`, e.g. `union_by(other, str.casefold)`).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (memory O(distinct keys)). Short-circuit: yields as soon as an element is new; `union(b).first()` pulls one element of `self` and never touches `second`.
- Order: all distinct elements of `self` in source order, then the not-yet-seen elements of `second`. Duplicates **inside** `self` are removed too (it is a set union, not `concat`).
- `second` is not iterated (not even `iter()`) until `self` is exhausted, matching .NET's `UnionIterator`.
- Validation (eager): `second is None` → `ArgumentNoneError("second")`; `key_selector is None` → `ArgumentNoneError("key_selector")`. `self` can never be `None` (`flp.it(None)` raises `SourceNoneError`).
- `union_by`: `key_selector` is called exactly once per element of both sequences that is pulled; the first element for each key wins.
- `None` elements / keys are ordinary values (`SingleNullWithEmpty`, `NullEmptyStringMix`).
- Equality is Python `__eq__`/`__hash__` (shared deviation from L06: `1 == 1.0 == True`, `NaN` objects only equal to themselves).
- **Unhashable elements (proposed decision)**: raise `TypeError: unhashable type: ...` at the element, from the set operation. No silent O(n²) list fallback: it would hide a performance cliff and diverge from `distinct`. The docstring shows the fix (`union_by(other, tuple)` for lists). README deviation entry "set operators require hashable elements or keys" (shared by L21–L23).
- Re-enumeration: each enumeration starts with an empty seen-set and re-iterates both sources.

### 3.3 Implementation sketch
```python
# _setops.py
def _distinct_stream(iterable, key=None, seen=None):
    seen = set() if seen is None else seen
    add = seen.add
    if key is None:
        for item in iterable:
            if item not in seen:
                add(item); yield item
    else:
        for item in iterable:
            k = key(item)
            if k not in seen:
                add(k); yield item

def union(self, second):
    _require_not_none(second, "second")
    return FlpIt(_FactoryIterable(lambda: _distinct_stream(chain(self, second))))

def union_by(self, second, key_selector):
    _require_not_none(second, "second"); _require_callable(key_selector, "key_selector")
    return FlpIt(_FactoryIterable(lambda: _distinct_stream(chain(self, second), key_selector)))
```
- `chain` calls `iter(second)` lazily, giving the .NET ordering of source access. O(n + m) time, O(distinct) memory.
- **FlpList fast path**: none (no observable-equivalent shortcut; `dict.fromkeys` would be eager).

### 3.4 Registry entry
```toml
[operators.union]
category = "set"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Union"
python_equivalent = "dict.fromkeys(itertools.chain(a, b))  (eager)"
since = "0.3.0"

[operators.union_by]
category = "set"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.UnionBy"
python_equivalent = "seen-set generator over itertools.chain(a, b) keyed by k (no stdlib one-liner)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_union.py` from `UnionTests.cs` (41). Comparer tests are rewritten with `union_by` and a key (D3), which preserves their intent:
  - `AnagramEqualityComparer` → key `None if s is None else "".join(sorted(s))` (shared helper `anagram_key` in `tests/nettests/_comparers.py`, F08); `Modulo100EqualityComparer` → key `None if x is None else x % 100` (test data is non-negative, so C#/Python `%` agree); `StringComparer.OrdinalIgnoreCase` → `str.lower`.
  - Rewritten: `CustomComparer`, `RunOnce`, `FirstNullCustomComparer`, `SecondNullCustomComparer`, `MultipleUnionsCustomComparer`, `MultipleUnionsDifferentComparers`, `UnionBy_HasExpectedOutput`/`_RunOnce` comparer rows. The `Assert.Equal(expected, actual, comparer)` form compares mapped keys.
  - Adapted: `HashSetWithBuiltInComparer_HashSetContainsNotUsed` uses a `set` subclass with a case-insensitive `__contains__` and asserts flpit never calls it; `ForcedToEnumerator*` → `not isinstance(q, Iterator)`.
  - Expected skips: none. Target: 100 % ported.
- **Own unit tests** (`tests/unit/test_union.py`): `second` untouched until `self` is exhausted (spy iterable records `__iter__`); `union(b).first()` pulls one element; duplicates inside `self` removed; first-wins for `union_by`; key selector call count; unhashable element `TypeError` raised lazily at that element; re-enumeration resets the seen-set.
- **Contracts**: auto via registry (deferral, one-shot for both `self` and `second`).
- **Typing**: `assert_type(flp.it([1]).union([2]), FlpIt[int])`; `assert_type(flp.lst(["a"]).union_by(["B"], str.lower), FlpIt[str])`.

## 5. Differential harness
`difftest/specs/union.toml` and `union_by.toml`: pairs of sources (empty/empty, empty/non-empty, overlapping ints, duplicates on both sides, strings with `None`); keys identity, `x % 3`, `len`; probes `result`, `elements_pulled_first`, `elements_pulled_second` for `.first()` and `.take(3)`. Mixed-type equality (`1`/`True`) is `UNCOMPARABLE`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_union.py`, sizes 1e3 / 1e5 per side, 50 % overlap:
- `native`: `list(dict.fromkeys(chain(a, b)))`
- `flpit-FlpIt` / `flpit-FlpList`: `.union(b).to_list()`; `union_by` vs a seen-set generator.
- Target ratio ≤ 1.5× (Python-level loop vs C `dict.fromkeys`; recorded either way).

## 7. Docs
- Docstrings: `.NET: Enumerable.Union / UnionBy`; ordering and source-access rules; hashability requirement; `Execution: Deferred, streaming, re-iterable if both sources are`.
- Doctests:
  ```python
  >>> flp.it([1, 2, 2, 3]).union([3, 4, 1]).to_list()
  [1, 2, 3, 4]
  >>> flp.it(["a", "B"]).union_by(["A", "c"], str.lower).to_list()
  ['a', 'B', 'c']
  ```
- Translation map: `list(dict.fromkeys(chain(a, b)))` / `a.Union(b)` → `.union(b)`; `UnionBy(b, k)` → `.union_by(b, k)`.

## 8. Expected outcomes
- `union`/`union_by` on all types; `_setops.py` ready for L22/L23.
- 41 ported tests green (comparer cases rewritten), README deviation "hashable elements required" added.

## 9. Verification
VERIFY-std with `<op>=union` and `<op>=union_by`, plus:
```bash
uv run pytest -q tests/nettests/test_union.py -rs | tail -3          # expect no skips
uv run python -c "from flpit import flp; print(flp.it([[1]]).union([[1]]).to_list())"   # TypeError: unhashable type: 'list'
```

## 10. Definition of Done
DoD-std, plus `tests/nettests/_comparers.py` (key equivalents of the .NET test comparers) is available to L22–L26.

## 11. Risks / open questions
- Unhashable elements: proposed `TypeError`; the alternative (list fallback) is rejected above. Maintainer confirms once for L21–L23.
- If B05 lands first, `distinct`/`distinct_by` should move onto `_distinct_stream` in whichever card comes second.
