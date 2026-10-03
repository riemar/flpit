---
id: L14
title: sequence_equal
status: todo
priority: 032
effort: S
depends_on: [F05, F06, F07, F08, F09, L06]
upstream:
  dotnet: SequenceEqualTests.cs @ dotnet/runtime main 6f1d9331 (21 [Fact]/[Theory])
  morelinq: n/a (MoreLINQ StartsWith/EndsWith are M24)
pr:
---

# L14: `sequence_equal`

## 1. Goal
Order-sensitive equality of two iterables without materialising them: comparing a pipeline's output with an expected sequence, checking two streams for identity, test assertions on `FlpIt`. Python only has `list(a) == list(b)` (always materialises both, no short-circuit). Reuses the equality contract fixed in L06.

## 2. Scope
**In:** `sequence_equal(second)` on `_LinqOps`; length pre-check for sized sources; C-level comparison when both sides are lists (or both tuples).
**Out:** `SequenceEqual(second, IEqualityComparer)` (D3). The comparer use case is `a.select(key).sequence_equal(flp.it(b).select(key))`, shown in the docstring; no `sequence_equal_by` is added (no .NET counterpart).

## 3. Detailed design
### 3.1 Signatures
```python
def sequence_equal(self, second: Iterable[TItem]) -> bool: ...
```
| .NET | Python |
|---|---|
| `SequenceEqual(first, second)` | `first.sequence_equal(second)` |
| `SequenceEqual(first, second, IEqualityComparer?)` | omitted (D3); `null` comparer → plain call; custom comparer → `select(key)` on both sides |

### 3.2 Semantics
- Kind: terminal. Short-circuit: stops at the first unequal pair or when one side ends first.
- Equality per element: L06 `items_equal` (`a is b or a == b`), so the README "Equality semantics" deviations apply (NaN, `1 == 1.0 == True`, user `__eq__`).
- Enumeration order (observable): lockstep, `next(first)` then `next(second)`, exactly as .NET (`e1.MoveNext()` then `e2.MoveNext()`); when `first` ends, one more `next(second)` decides the result.
- **Length pre-check:** if both underlying sources are exact builtin sized types (`list`, `tuple`, `range`, `str`, `bytes`, `bytearray`, `deque`, `FlpList`) and `len` differs, return `False` without enumerating (.NET does the same for two `ICollection<T>`). Not applied to `OrderedIt` or chained queries (no cheap length).
- **List/tuple fast path:** both backing objects `list` (FlpList included), or both `tuple`, or both `bytes`/`bytearray`: `a == b`. CPython's list/tuple comparison checks length, then compares pairwise with `PyObject_RichCompareBool` (identity, then `==`) and stops at the first difference, which is exactly the generic loop's observable behaviour (same `__eq__` calls in the same order).
- Validation (eager): `second is None` → `ArgumentNoneError("second")`; `self` is never `None` (constructor). `second` may be any iterable, including another `FlpIt`/`FlpList`.
- One-shot sources: consumed up to the decision point. `x.sequence_equal(x)` on a one-shot `FlpIt` interleaves `next()` on the same iterator twice per step; the result is defined (pairs of consecutive elements) but meaningless, as in .NET; documented, not special-cased.
- Exceptions from either source or from `__eq__` propagate.

### 3.3 Implementation sketch
```python
def sequence_equal(self, second):
    _require_not_none(second, "second")
    a, b = self._plain_source(), _unwrap(second)          # backing object or None (OrderedIt/chains → None)
    if a is not None and b is not None:
        if type(a) is type(b) and type(a) in (list, tuple, bytes, bytearray):
            return a == b                                  # C-level, identical semantics
        if type(a) in _SIZED_EXACT and type(b) in _SIZED_EXACT and len(a) != len(b):
            return False
    for x, y in zip_longest(self, second, fillvalue=_MISSING):
        if x is _MISSING or y is _MISSING or not items_equal(x, y):
            return False
    return True
```
- `zip_longest` pulls `first` then `second` each step, matching .NET's order; when one side is exhausted it yields one `_MISSING` pair and the function returns.
- Generic: O(min(n, m) + 1) time, O(1) memory. List fast path: O(n) in C.
- **FlpList**: covered by `_plain_source()` returning the backing list; no override.

### 3.4 Registry entry
```toml
[operators.sequence_equal]
category = "equality"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.SequenceEqual"
python_equivalent = "list(a) == list(b)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_sequence_equal.py` from `SequenceEqualTests.cs` (21). `FlipIsCollection` → swap between `list` and the `non_collection` fixture (exercises the fast path and the generic loop in all four combinations).
  - `NullComparer`, `BothSingleNullExplicitComparer` (`StringComparer.Ordinal`): ported as plain calls.
  - `CustomComparer`, `RunOnce` (`AnagramEqualityComparer`): rewritten per D3 as `select(sorted_key)` on both sides (intent preserved).
  - `FirstSourceNull` → `flp_type(None)` raises `SourceNoneError`; `SecondSourceNull` → `ArgumentNoneError`.
  - `ByteArrays_SpecialCasedButExpectedBehavior`: ported with `bytes`/`bytearray`/`list[int]` and a seeded `random.Random(0).randbytes`.
  - `ICollectionsCompareCorrectly` → `collections.deque` sources; `IListsCompareCorrectly` → `tuple` sources.
  - No expected skips. Target: 21 of 21 (100 %).
- **Own unit tests** (`tests/unit/test_sequence_equal.py`):
  - Lockstep pull order and counts on two generators (mismatch at index 3 → 4 pulls each; `first` shorter by one → `second` pulled `len(first) + 1` times).
  - Length pre-check: two lists of different length never call element `__eq__` (instrumented elements).
  - Fast-path equivalence: `__eq__` call sequence identical for `list`/`list` vs `non_collection` pairs.
  - NaN identity vs distinct NaN; `[1]` vs `[1.0]` is `True`; `None` elements.
  - `order_by(k).sequence_equal(sorted(xs, key=k))` is `True` (OrderedIt uses the generic path).
- **Contracts** (auto): terminal, short-circuit probe, FlpList not mutated (both arguments).
- **Typing**: `assert_type(flp.it([1]).sequence_equal([1]), bool)`; `flp.it([1]).sequence_equal(["a"])` is a pyrefly error.

## 5. Differential harness
`difftest/specs/sequence_equal.toml`: pairs (empty/empty, equal, mismatch first/middle/last, prefix either way, `None`-containing, strings); kinds `list` and `non_collection` on each side; probes `result`, `pulled_first`, `pulled_second` (non-collection sides only). Floats with NaN: `EXPECTED_DIFFERENCE` (README Equality deviation). Expected otherwise: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_sequence_equal.py`, sizes 1e3 / 1e5, equal sequences (worst case) and mismatch at the middle:
- `native`: `a == b` (lists); `list(ga) == list(gb)` (generators)
- `flpit-FlpIt` (list sources → fast path; generator sources → generic loop) / `flpit-FlpList`
- Targets: list fast path ≤ 1.3×; generic loop ≤ 2.0× vs `list(ga) == list(gb)` (the native baseline materialises in C; flpit trades speed for O(1) memory and short-circuit, stated in the PR).

## 7. Docs
- Docstring: `.NET: Enumerable.SequenceEqual(second)`; equality rule (link to README section); comparer replacement via `select`; Execution: Terminal, lockstep, short-circuits.
- Doctests: `flp.it([1, 2, 3]).sequence_equal((1, 2, 3))` gives `True`; `flp.it([1, 2]).sequence_equal([1, 2, 3])` gives `False`.
- Translation map: `list(a) == list(b)` / `.SequenceEqual(b)` → `.sequence_equal(b)`; `.SequenceEqual(b, cmp)` → `.select(k).sequence_equal(flp.it(b).select(k))`.

## 8. Expected outcomes
- `sequence_equal` on all four types; 21 ported tests green with no skips; equality contract shared with `contains`.

## 9. Verification
VERIFY-std with `<op>=sequence_equal`, plus:
```bash
uv run pytest -q tests/nettests/test_sequence_equal.py -rs        # 0 skipped
uv run python -c "from flpit import flp; print(flp.it(x for x in [1, 2, 3]).sequence_equal((1, 2, 3)), flp.lst([1, 2]).sequence_equal([1, 2, 3]))"   # True False
```

## 10. Definition of Done
DoD-std, plus the README Equality deviation section lists `sequence_equal`.

## 11. Risks / open questions
- The generic loop is Python-level, so the 2.0× target vs a C-level materialising baseline may be missed for large equal inputs; acceptable per D8, documented in the PR.
