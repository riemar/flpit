---
id: L10
title: element_at (from-end) / element_at_or_default
status: todo
priority: 021
effort: S
depends_on: [F05, F06, F07, F08, F09, L04, L07]
upstream:
  dotnet: ElementAtTests.cs (24 [Fact]/[Theory]) + ElementAtOrDefaultTests.cs (18 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331
  morelinq: n/a
pr:
---

# L10: `element_at` (from-end) / `element_at_or_default`

## 1. Goal
Resolve README open question 3 for `ElementAt(Index)`: **a negative `int` means "from the end"**, exactly like Python indexing, so `.NET ^n` maps to `-n`. `element_at(-1)` becomes "last element" instead of an `IndexError`, and `element_at_or_default(i, default=...)` is added in the D5 shape. The existing `element_at` has no ported tests; this card ports both .NET files.

## 2. Scope
**In:** rewritten `element_at(index)` with from-end support; new `element_at_or_default(index, *, default=None)`; `Sequence`/`Sized` fast paths; migration of in-repo tests that asserted `element_at(-1)` raises; adding the deferred `ElementAtOrDefault(Count())` sub-asserts to the L04/L05 ports.
**Out:** `Take(Range)` (N09). A separate `Index` type (rejected: Python ints already carry the from-end meaning).

## 3. Detailed design
### 3.1 Signatures
```python
def element_at(self, index: int) -> TItem: ...

@overload
def element_at_or_default(self, index: int) -> TItem | None: ...
@overload
def element_at_or_default(self, index: int, *, default: TDefault) -> TItem | TDefault: ...
```
| .NET | Python |
|---|---|
| `ElementAt(int index)`, index ≥ 0 | `element_at(index)` |
| `ElementAt(int index)`, index < 0 (throws in .NET) | **deviation**: `element_at(-k)` is from-end |
| `ElementAt(Index)`: `new Index(i)` / `^k` | `element_at(i)` / `element_at(-k)`; `^0` has no Python spelling (it is always out of range) |
| `ElementAtOrDefault(int)` / `ElementAtOrDefault(Index)` | `element_at_or_default(i)` / `element_at_or_default(-k)`, plus D5 `default=` |

### 3.2 Semantics
- Kind: terminal.
- `index >= 0`: pulls `index + 1` elements and stops (short-circuit). Out of range → `IndexError`.
- `index = -k < 0`: generic sources are fully enumerated with a ring buffer of `k` elements (partial buffering, O(k) memory, matching .NET's queue in `TryGetElementAt(^k)`); valid iff `k <= len`. Out of range → `IndexError` after the full scan (pull count `len + 1` including the exhausting `next()`, same as upstream `EnumerateElements`).
- **Deviation (README § "Intentional Semantic Deviations"):** .NET `ElementAt(-1)` throws and `ElementAtOrDefault(-1)` returns default; in flpit both address the last element. Rationale: Python's own indexing contract (`xs[-1]`) and D-question 3. Invariant: for any `index` and finite list-convertible source, `flp.it(xs).element_at(index) == list(xs)[index]` or both raise `IndexError`.
- Error: `IndexError("Index was out of range. (Parameter 'index')")` (README 3.1 keeps `IndexError`; .NET's "Must be non-negative" clause is dropped because it is false here). Legacy tests matching `"Index out of range"` are updated to `match="out of range"`.
- Validation (eager): `operator.index(index)` (`bool` accepted, `1.5` → `TypeError`); `None` → `ArgumentNoneError("index")`.
- Huge indices: `index > sys.maxsize` (beyond `islice`) or `-index > sys.maxsize` (beyond `deque` maxlen) drain the source and raise `IndexError` (or return the default); an infinite source loops forever, as in .NET.
- `element_at_or_default`: only the out-of-range case returns `default` (`None` unless given); source exceptions propagate.
- Breaking change for `element_at(-k)` (previously `IndexError`); CHANGELOG `Changed`.

### 3.3 Implementation sketch
```python
def _element_at_or_missing(self, index):
    index = _require_index(index, "index")
    seq = self._indexable()                                 # L04: list/tuple/range/str/FlpList
    if seq is not None:
        try:
            return seq[index]                               # native negative indexing
        except IndexError:                                  # incl. "cannot fit 'int' into an index-sized integer"
            return _MISSING
    src = self._sized_source()                              # exact set/frozenset/dict/deque/dict views, else None
    if src is not None and index < 0:
        index += len(src)                                   # .NET TryGetNonEnumeratedCount path: no buffering
        if index < 0:
            return _MISSING
    if index >= 0:
        if index > sys.maxsize:
            _drain(self); return _MISSING
        return next(islice(iter(self), index, None), _MISSING)
    k = -index
    if k > sys.maxsize:
        _drain(self); return _MISSING
    window = deque(self, maxlen=k)
    return window[0] if len(window) == k else _MISSING
```
- Indexable: O(1). Sized: O(index) time, O(1) memory. Generic positive: O(index) C-level `islice`. Generic negative: O(n) time, O(k) memory.
- Fast paths are observationally equivalent: list/tuple/range/str and the exact builtin sized types have side-effect-free iteration; results and exception types match the generic path (asserted by an equivalence test over index ∈ [−len−2, len+2]).
- `element_at` raises `IndexError` on `_MISSING`; `element_at_or_default` returns `default`.

### 3.4 Registry entry
```toml
[operators.element_at]
category = "element"
kind = "terminal"
buffering = "partial"          # negative index on generic sources buffers |index| elements
short_circuit = true           # non-negative index
dotnet = "Enumerable.ElementAt (int, Index)"
python_equivalent = "xs[i] / next(islice(xs, i, None))"
since = "0.1.0"
changed = "0.3.0: negative index counts from the end (.NET ^n)"

[operators.element_at_or_default]
category = "element"
kind = "terminal"
buffering = "partial"
short_circuit = true
dotnet = "Enumerable.ElementAtOrDefault (int, Index)"
python_equivalent = "next(islice(xs, i, None), default)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_element_at.py` from `ElementAtTests.cs` (24). Rules: `new Index(i)` → `i`; `^k` → `-k`; asserts using `^0` or expecting `ElementAt(negative int)` to throw are dropped line by line with `# NO_INDEX_RANGE_TYPE` comments; `int.MinValue` → `-2**31` (still out of range). `ListPartitionOrEmpty` → `flp.lst(src).skip(0)`, `EnumerablePartitionOrEmpty` → `non_collection(src)` + `skip(0)` (L01); `TestCollection` → `collections.deque` (exercises the Sized path). Expected skips:
  - `NO_SPAN_OR_ARRAY`: `NonEmptySource_Consistency_ThrowsIListIndexerException`, `EmptySource_Consistency_ThrowsIListIndexerException` (`ImmutableArray` indexer exception type).
  - `OTHER`: `NonEmptySource_Consistency_NonGenericCollection`, `EmptySource_Consistency_NonGenericCollection` (no generic/non-generic split in Python; covered by the `deque` variants).
  - Target: 20 of 24 (83 %).
- **Ported** `tests/nettests/test_element_at_or_default.py` from `ElementAtOrDefaultTests.cs` (18): same index rules; `default(int)` → `is None`; the `NullableArray_InvalidIndex_ReturnsNull` `(-1)` line and the theory row's `ElementAtOrDefault(-1)` int assert are dropped (`NO_INDEX_RANGE_TYPE`). Target: 18 of 18 methods.
- **Backfill** into L04/L05 ports: `element_at_or_default(len(result))` is `None`.
- **Migrated** legacy tests: `tests/gemini_test_suite/test_created_20260923.py` (`-1` row now valid), `tests/luna_test_suite/test_terminal_ops.py` (`-1` row), `tests/luna_test_suite/test_flplist_comprehensive.py`; regex updated.
- **Own unit tests** (`tests/unit/test_element_at.py`): property-style equivalence with `list(xs)[i]` for i in [−len−2, len+2] over `flp_type`, `non_collection`, `deque`, `range`, `str`; pull counts (positive: `i+1`; negative on generic: `len+1`); eager `ArgumentNoneError`/`TypeError`; `2**70` and `-(2**70)`.
- **Contracts** (auto): terminal; short-circuit probe uses a non-negative index; FlpList not mutated.
- **Typing**: `assert_type(xs.element_at(-1), int)`, `assert_type(xs.element_at_or_default(5), int | None)`, `assert_type(xs.element_at_or_default(5, default=0), int)`.

## 5. Differential harness
`difftest/specs/element_at.toml`, `element_at_or_default.toml`: index domain `{0, 1, len-1, len, len+1, int.MaxValue}` mapped to the .NET `int` overload, and `{-1, -len, -(len+1), -int.MaxValue}` mapped to `Index.FromEnd(k)` (never to the `int` overload); sources empty/singleton/ints/`int?` with `None`, list and non-collection kinds; probes `result` or `out_of_range`, `elements_pulled`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_element_at.py`, sizes 1e3 / 1e5, `i = size // 2` and `i = -10`:
- `native`: `data[i]` (list); `next(islice(iter(data), i, None))`; `deque(iter(data), maxlen=10)[0]`
- `flpit-FlpIt` (list source, `iter()` source) / `flpit-FlpList`
- Target ratio ≤ 1.5× (O(1) list case: report absolute overhead).

## 7. Docs
- Docstrings: `.NET: Enumerable.ElementAt(int / Index)`; "`-k` is `.NET ^k`"; buffering note for negative indices on generic sources; D5 `default`.
- Doctests: `flp.it(range(10)).element_at(-1)` gives `9`; `flp.it(x for x in "abc").element_at(1)` gives `'b'`; `flp.it([1, 2]).element_at_or_default(5, default=0)` gives `0`.
- README deviation entry "Negative indices"; translation map: `xs[i]` / `.ElementAt(i)` → `.element_at(i)`; `.ElementAt(^k)` → `.element_at(-k)`; `.ElementAtOrDefault(i)` → `.element_at_or_default(i)`.

## 8. Expected outcomes
- From-end indexing on all four types; 38 ported .NET tests green, 4 categorised skips; legacy tests migrated; CHANGELOG notes the behaviour change.

## 9. Verification
VERIFY-std with `<op>=element_at` and `<op>=element_at_or_default`, plus:
```bash
uv run pytest -q tests/nettests/test_element_at.py tests/nettests/test_element_at_or_default.py -rs
uv run python -c "from flpit import flp; print(flp.it(x for x in range(10)).element_at(-3), flp.it([1, 2]).element_at_or_default(-3))"   # 7 None
```

## 10. Definition of Done
DoD-std, plus: README "Negative indices" deviation; CHANGELOG `Changed` for `element_at(-k)`; L04/L05 ported tests extended with `element_at_or_default(len)`.

## 11. Risks / open questions
- Ports of other files that use `ElementAtOrDefault(-1)` to mean "default" (TakeLast, SkipLast, Reverse, DefaultIfEmpty) must drop those asserts rather than translate them; reviewers of those cards should check for it.
- `_sized_source()` is a second private helper next to `_indexable()`; if it is only used here, keep it local to `element_at`.
