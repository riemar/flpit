---
id: L22
title: intersect / intersect_by
status: todo
priority: 033
effort: S
depends_on: [F05, F06, F07, F08, F09, L06, L21]
upstream:
  dotnet: IntersectTests.cs @ dotnet/runtime main 6f1d9331 (15 [Fact]/[Theory]; IntersectBy tests live in the same file)
  morelinq: n/a
pr:
---

# L22: `intersect` / `intersect_by`

## 1. Goal
Order-preserving, distinct set intersection that streams the first sequence (Python's `set(a) & set(b)` is eager and unordered). `intersect_by(keys, key_selector)` (.NET 6) answers "keep the records whose key is in this key list", a frequent filtering idiom (`orders.intersect_by(vip_ids, lambda o: o.customer_id)`) that also yields each key at most once. Reuses `_setops.py` from L21.

## 2. Scope
**In:** `intersect(second)` and `intersect_by(second, key_selector)` on `_LinqOps`.
**Out:** comparer overloads (D3).

## 3. Detailed design
### 3.1 Signatures
```python
def intersect(self, second: Iterable[TItem]) -> FlpIt[TItem]: ...
def intersect_by(self, second: Iterable[TKey], key_selector: Callable[[TItem], TKey]) -> FlpIt[TItem]: ...
```
`.NET` overload map: `Intersect(second)` → `intersect`; `IntersectBy(second, keySelector)` → `intersect_by` (note: `second` is a sequence of **keys**, as in .NET); both comparer overloads omitted (D3).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial: `second` is fully buffered into a `set` at the **first `next()`**, before `self` is touched; `self` is then streamed. Short-circuit: `intersect(b).first()` buffers all of `b` but pulls `self` only until the first match.
- Algorithm (as .NET): `s = set(second)`; for each element of `self` (key for `_by`), if it is in `s`, remove it from `s` and yield the element. Result: distinct elements (first occurrence) of `self` that occur in `second`, in `self` order.
- No early exit when `s` becomes empty: .NET keeps enumerating `self` to the end, and so does flpit (observable via `elements_pulled`; the harness checks it).
- `second` is not iterated at call time (deferred, `ForcedToEnumeratorDoesntEnumerate`); it is iterated once per enumeration of the query.
- Validation (eager): `second is None` → `ArgumentNoneError("second")`; `key_selector is None` → `ArgumentNoneError("key_selector")`.
- `key_selector` is called once per element of `self` pulled, never on `second`.
- `None` elements/keys are ordinary values (`NullableInt` data: `[1, 2, None, ...] ∩ [..., None, ...]` keeps `None`).
- Equality and hashability: shared rules from L21 (Python `__eq__`/`__hash__`; unhashable element or key → `TypeError`; for `second` the error surfaces at the first `next()`).

### 3.3 Implementation sketch
```python
def intersect_by(self, second, key_selector):
    _require_not_none(second, "second"); _require_callable(key_selector, "key_selector")
    def _generator():
        remaining = set(second)              # C-level, first next()
        remove = remaining.remove
        for item in self:
            k = key_selector(item)
            if k in remaining:
                remove(k)
                yield item
    return FlpIt(_FactoryIterable(_generator))
# intersect: same loop without key_selector (k = item)
```
- O(n + m) time, O(m) memory. `set(second)` is C-level.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.intersect]
category = "set"
kind = "intermediate"
buffering = "partial"         # second fully buffered, first streamed
short_circuit = false
dotnet = "Enumerable.Intersect"
python_equivalent = "s = set(b); [x for x in dict.fromkeys(a) if x in s]"
since = "0.3.0"

[operators.intersect_by]
category = "set"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.IntersectBy"
python_equivalent = "seen-set filter of a by k(x) in set(keys), first per key"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_intersect.py` from `IntersectTests.cs` (15). Comparer rows are rewritten with `intersect_by` using the L21 helpers: the `AnagramEqualityComparer` row of `String` becomes `first.intersect_by(map(anagram_key, second), anagram_key)` (expected `["Bob", "Mike"]`), same for the `IntersectBy_TestData` anagram and `OrdinalIgnoreCase` rows. `HashSetWithBuiltInComparer_HashSetContainsNotUsed` uses the case-insensitive `set` subclass from L21; its `OrdinalIgnoreCase` assertions use `intersect_by(map(str.lower, ...), str.lower)`.
  - Expected skips: none. Target: 100 % ported.
- **Own unit tests** (`tests/unit/test_intersect.py`): `second` buffered at first `next()` and before `self.__iter__` (spy records call order); `second` not touched at call time; no early exit when the set is exhausted (`elements_pulled == len(self)`); each match yielded once; `key_selector` never applied to `second`; unhashable element in `second` raises at first `next()`; one-shot `second` makes the query one-shot (second enumeration yields nothing because `second` is empty).
- **Contracts**: auto via registry; the `partial` buffering class asserts that `second` is consumed fully while `self` is streamed.
- **Typing**: `assert_type(flp.it([1]).intersect([1]), FlpIt[int])`; `assert_type(flp.it([("a", 1)]).intersect_by([1], lambda p: p[1]), FlpIt[tuple[str, int]])`.

## 5. Differential harness
`difftest/specs/intersect.toml` and `intersect_by.toml`: source pairs from the upstream data plus empty/empty, disjoint, `second` with duplicates, `None` values; probes `result`, `elements_pulled_first` (full enumeration expected), `elements_pulled_second`, `key_selector_calls`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_intersect.py`, sizes 1e3 / 1e5 per side, 50 % overlap:
- `native`: a plain function `s = set(b); out = []` then `for x in a: if x in s: s.remove(x); out.append(x)` (the idiomatic order-preserving equivalent).
- `flpit-FlpIt` / `flpit-FlpList`: `.intersect(b).to_list()`.
- Target ratio ≤ 1.3× (buffering op).

## 7. Docs
- Docstrings: `.NET: Enumerable.Intersect / IntersectBy`; buffering of `second` at first iteration; result distinctness; `second` holds keys for `_by`; hashability; `Execution: Deferred, second buffered, first streamed`.
- Doctests:
  ```python
  >>> flp.it([1, 2, 2, 3, 4]).intersect([4, 2, 9]).to_list()
  [2, 4]
  >>> flp.it([("Tom", 20), ("Dick", 30), ("Harry", 40)]).intersect_by([15, 20, 40], lambda p: p[1]).to_list()
  [('Tom', 20), ('Harry', 40)]
  ```
- Translation map: `[x for x in dict.fromkeys(a) if x in set(b)]` / `a.Intersect(b)` → `.intersect(b)`; `IntersectBy(keys, k)` → `.intersect_by(keys, k)`.

## 8. Expected outcomes
- `intersect`/`intersect_by` on all types; all 15 upstream tests ported.

## 9. Verification
VERIFY-std with `<op>=intersect` and `<op>=intersect_by`, plus:
```bash
uv run pytest -q tests/nettests/test_intersect.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([1, None, 2, None]).intersect([None, 2]).to_list())"   # [None, 2]
```

## 10. Definition of Done
DoD-std.

## 11. Risks / open questions
- The registry `buffering = "partial"` value was defined for bounded buffers; set ops buffer one whole input. If F08's contract tests treat `partial` as "bounded", F06 adds a `buffering = "second"` (or a `buffers = ["second"]` list) and L21–L26 use it. Decide in F06; this card adapts.
