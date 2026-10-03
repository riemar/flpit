---
id: L23
title: except_ / except_by
status: todo
priority: 039
effort: S
depends_on: [F05, F06, F07, F08, F09, L06, L21]
upstream:
  dotnet: ExceptTests.cs @ dotnet/runtime main 6f1d9331 (15 [Fact]/[Theory]; ExceptBy tests live in the same file)
  morelinq: n/a
pr:
---

# L23: `except_` / `except_by`

## 1. Goal
Order-preserving, distinct set difference that streams the first sequence. `except_by(keys, key_selector)` (.NET 6) is the "anti-join by key" idiom (`users.except_by(banned_ids, lambda u: u.id)`). This card also **resolves open question 1** of the board README (keyword collision for `Except`).

## 2. Scope
**In:** `except_(second)` and `except_by(second, key_selector)` on `_LinqOps`, reusing `_setops.py` (L21).
**Out:** comparer overloads (D3); an alias `difference` (see 11).

## 3. Detailed design
### 3.1 Signatures
```python
def except_(self, second: Iterable[TItem]) -> FlpIt[TItem]: ...
def except_by(self, second: Iterable[TKey], key_selector: Callable[[TItem], TKey]) -> FlpIt[TItem]: ...
```
`.NET` overload map: `Except(second)` → `except_` (PEP 8 trailing underscore, README §3.1 naming rule); `ExceptBy(second, keySelector)` → `except_by` (`second` holds **keys**); both comparer overloads omitted (D3).

**Open question 1 resolution (proposed default): `except_`, no alias.** Reasons: it follows the naming convention already written in README §3.1, keeps the .NET name searchable (`except` → `except_` is what IDE completion shows), and matches `except_by`. `difference` was considered and rejected: `set.difference` is eager and returns an unordered `set`, so reusing the name would suggest Python set semantics instead of a lazy, order-preserving sequence. No alias, to keep one name per operator in the registry and the skill.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (`second` fully buffered into a `set` at the first `next()`, before `self` is touched; `self` streamed). Short-circuit: `except_(b).first()` buffers `b` and pulls `self` until the first surviving element.
- Algorithm (as .NET): `s = set(second)`; for each element of `self` (its key for `_by`): if adding it to `s` grows `s`, yield the element. Result: distinct elements of `self` (first occurrence per value/key) not present in `second`, in `self` order. `None` duplicates collapse too (`NullableInt` data `[..., None, None] - []` keeps one `None`).
- `second` is not iterated at call time; it is iterated once per enumeration.
- Validation (eager): `second is None` → `ArgumentNoneError("second")`; `key_selector is None` → `ArgumentNoneError("key_selector")`.
- `key_selector` runs once per element of `self` pulled, never on `second`.
- Equality/hashability: shared rules from L21 (unhashable → `TypeError`).

### 3.3 Implementation sketch
```python
def except_by(self, second, key_selector):
    _require_not_none(second, "second"); _require_callable(key_selector, "key_selector")
    def _generator():
        seen = set(second)                              # C-level, first next()
        yield from _distinct_stream(self, key_selector, seen=seen)   # L21 helper
    return FlpIt(_FactoryIterable(_generator))
# except_: _distinct_stream(self, seen=set(second))
```
- "Not in `seen` → add and yield" is exactly .NET's `if (set.Add(x)) yield return x`, so the L21 primitive is reused unchanged. O(n + m) time, O(n + m) memory.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.except_]
category = "set"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.Except"
python_equivalent = "s = set(b); [x for x in dict.fromkeys(a) if x not in s]"
since = "0.3.0"

[operators.except_by]
category = "set"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.ExceptBy"
python_equivalent = "seen-set filter of a where k(x) not in set(keys), first per key"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_except.py` from `ExceptTests.cs` (15). The `AnagramEqualityComparer` row of `String` becomes `first.except_by(map(anagram_key, second), anagram_key)` (expected `["Tim", "Robert"]`); `ExceptBy_TestData` comparer rows likewise; `HashSetWithBuiltInComparer_HashSetContainsNotUsed` uses the L21 case-insensitive `set` subclass and `except_by(map(str.lower, ...), str.lower)` for the `OrdinalIgnoreCase` assertions. `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(q, Iterator)`.
  - Expected skips: none. Target: 100 % ported.
- **Own unit tests** (`tests/unit/test_except.py`): source-access order (`second` fully, then `self`); `second` untouched at call time; duplicates in `self` removed; `except_(b)` with empty `b` equals `distinct()`; key selector call count; unhashable `TypeError`; the method is reachable as `getattr(q, "except_")` and `except` is not defined (no keyword clash).
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).except_([1]), FlpIt[int])`; `assert_type(flp.lst(["a"]).except_by([1], len), FlpIt[str])`.

## 5. Differential harness
`difftest/specs/except_.toml` and `except_by.toml`: upstream data plus empty `second`, `second` superset, duplicates and `None` in `self`; probes `result`, `elements_pulled_first`, `elements_pulled_second`, `key_selector_calls`. The spec maps the Python name `except_` to the oracle method `Except`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_except.py`, sizes 1e3 / 1e5 per side, 50 % overlap:
- `native`: a plain function `seen = set(b); out = []` then `for x in a: if x not in seen: seen.add(x); out.append(x)`.
- `flpit-FlpIt` / `flpit-FlpList`: `.except_(b).to_list()`.
- Target ratio ≤ 1.3×.

## 7. Docs
- Docstrings: `.NET: Enumerable.Except / ExceptBy`; naming note (`except` is a keyword); buffering; distinctness; `Execution: Deferred, second buffered, first streamed`.
- Doctests:
  ```python
  >>> flp.it([1, 2, 2, 3, 4]).except_([2, 4]).to_list()
  [1, 3]
  >>> flp.it([("Tom", 20), ("Dick", 30), ("Harry", 40)]).except_by([20], lambda p: p[1]).to_list()
  [('Dick', 30), ('Harry', 40)]
  ```
- Translation map: `[x for x in dict.fromkeys(a) if x not in set(b)]` / `a.Except(b)` → `.except_(b)`; `ExceptBy(keys, k)` → `.except_by(keys, k)`.
- Board README: open question 1 marked resolved with a link to this card.

## 8. Expected outcomes
- `except_`/`except_by` on all types; all 15 upstream tests ported; naming question closed.

## 9. Verification
VERIFY-std with `<op>=except_` and `<op>=except_by`, plus:
```bash
uv run pytest -q tests/nettests/test_except.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([3, 1, 3, None, None]).except_([1]).to_list())"   # [3, None]
```

## 10. Definition of Done
DoD-std, plus the board README open-question entry is updated.

## 11. Risks / open questions
- Maintainer may prefer an extra `difference` alias for discoverability; adding one later is non-breaking (registry `aliases`, as for `to_hash_set`).
