---
id: L19
title: to_set / to_hash_set
status: todo
priority: 037
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ToHashSetTests.cs @ dotnet/runtime main 6f1d9331 (6 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L19: `to_set` / `to_hash_set`

## 1. Goal
Materialising into a set is common for membership tests and deduplication. Today users write `set(query)`, which works but breaks the fluent chain and is invisible to the operator registry, the docs and the skill. D17 fixes the target type: builtin `set`, with the .NET name kept as an alias.

## 2. Scope
**In:** `to_set()` on `_LinqOps`, alias `to_hash_set = to_set`.
**Out:** comparer overload (D3: use `select(key).to_set()` or `distinct_by(key)`); `frozenset` (callers can wrap; one return type keeps typing simple).

## 3. Detailed design
### 3.1 Signatures
```python
def to_set(self) -> set[TItem]: ...
to_hash_set = to_set
```
`.NET` overload map: `ToHashSet()` → `to_set()` / `to_hash_set()`; `ToHashSet(IEqualityComparer)` omitted (D3).

### 3.2 Semantics
- Kind: terminal. Buffering: full. Short-circuit: none.
- No arguments to validate; `flp.it(None)` already raises `SourceNoneError` (`ThrowOnNullSource`).
- Duplicates are tolerated (unlike `to_dictionary`); `None` elements are kept (`TolerateNullElements`).
- Equality is Python `__eq__`/`__hash__`: `{1, 1.0, True}` collapses to one element; `float('nan')` objects are distinct unless they are the same object (.NET treats all `NaN` as equal). Shared equality deviation (owned by L06).
- Unhashable element → `TypeError: unhashable type` at that element.
- Returns a new `set`; mutating it never affects the source or the query.

### 3.3 Implementation sketch
```python
def to_set(self) -> set[TItem]:
    return set(self)
to_hash_set = to_set
```
- C-level: O(n) time, O(distinct) memory. Defined once on the mixin; the alias is a class attribute so `FlpList`/`OrderedIt`/`Grouping`/`Lookup` inherit both names (the alias must be re-bound if a subclass ever overrides `to_set`; a contract test checks `type(x).to_hash_set is type(x).to_set`).
- **FlpList fast path**: none needed; `set(self)` iterates the backing list directly.

### 3.4 Registry entry
```toml
[operators.to_set]
category = "conversion"
kind = "terminal"
buffering = "full"
short_circuit = false
dotnet = "Enumerable.ToHashSet"
aliases = ["to_hash_set"]
python_equivalent = "set(xs)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_to_hash_set.py` from `ToHashSetTests.cs` (6). Expected skips:
  - `COMPARER_NOT_SUPPORTED`: `ExplicitComparer` (asserts `hs.Comparer` identity).
  - `NoExplicitComparer` is ported without its `Comparer` assertion (`isinstance(hs, set)`, `len == 50`).
  - Target: 5/6 ported (83 %).
- **Own unit tests** (`tests/unit/test_to_set.py`): alias identity; unhashable element `TypeError`; `None` kept; result is a fresh `set` (mutating it does not change a second `to_set()` call); one-shot generator consumed once; `1`/`True` collapse documented by a test.
- **Contracts**: auto (terminal, FlpList not mutated).
- **Typing**: `assert_type(flp.it([1]).to_set(), set[int])`; `assert_type(flp.lst(["a"]).to_hash_set(), set[str])`.

## 5. Differential harness
`difftest/specs/to_set.toml`: sources empty, ints with duplicates, strings with `None`; probe `result` compared as a sorted list (set order is unspecified on both sides). Mixed `1`/`True`/`1.0` sources are `UNCOMPARABLE` (no equivalent .NET element type). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_to_set.py`, sizes 1e3 / 1e5, 50 % duplicates:
- `native`: `set(data)`; `flpit-FlpIt`: `flp.it(data).to_set()`; `flpit-FlpList`: `flp.lst(data).to_set()`.
- Target ratio ≤ 1.1× (one extra call frame).

## 7. Docs
- Docstring: `.NET: Enumerable.ToHashSet()`; equality note; `Execution: Immediate, full buffering`.
- Doctest:
  ```python
  >>> sorted(flp.it([3, 1, 3, 2]).to_set())
  [1, 2, 3]
  ```
- Translation map: `set(xs)` / `.ToHashSet()` → `.to_set()` (alias `.to_hash_set()`).

## 8. Expected outcomes
- `to_set` and `to_hash_set` on all types, typed as `set[T]`.
- 5 ported + own tests green; registry alias support exercised (first alias besides `avg`).

## 9. Verification
VERIFY-std with `<op>=to_set`, plus:
```bash
uv run python -c "from flpit import flp; print(sorted(flp.it('abca').to_hash_set()))"   # ['a', 'b', 'c']
```
Manual: the README operator matrix lists `to_hash_set` as an alias of `to_set`.

## 10. Definition of Done
DoD-std, plus F06's docs generator renders `aliases` (extend it here if it does not).

## 11. Risks / open questions
- None significant. If F06's registry schema has no `aliases` key yet, this card adds it (also used by `average`/`avg`).
