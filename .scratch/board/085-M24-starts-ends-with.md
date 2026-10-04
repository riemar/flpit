---
id: M24
title: starts_with / ends_with
status: todo
priority: 085
effort: S
depends_on: [F05, F06, F07, F08, F09, L04, L06, N10]
upstream:
  dotnet: n/a (closest .NET op: SequenceEqual, L14)
  morelinq: StartsWith.cs, EndsWith.cs @ morelinq master d217ab1 (reference only, D7; StartsWithTest.cs 18 + EndsWithTest.cs 18 [Test]/[TestCase] read for behaviour)
pr:
---

# M24: `starts_with` / `ends_with`

## 1. Goal
`str.startswith` exists only for strings; for arbitrary sequences ("does this log start with the handshake records?", "does the path end with these segments?") users write `list(islice(xs, len(ys))) == ys` or a `deque` tail, both easy to get wrong for one-shot sources. MoreLINQ's `StartsWith`/`EndsWith` give a prefix/suffix test with clear pull semantics: `starts_with` stops at the first mismatch, `ends_with` keeps a buffer bounded by `len(second)`.

## 2. Scope
**In:** `starts_with(second)` and `ends_with(second)` on `_LinqOps`; known-count shortcut via N10; Sequence fast path via L04's `_indexable()`.
**Out:** comparer overloads. D3 would offer a key selector, but composition already expresses it with identical semantics, so no `key` parameter and no `_by` variant (same decision as L06 `contains`): `xs.select(key).starts_with(map(key, ys))`. Documented in the docstring.

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `StartsWith(second)` / `EndsWith(second)` | `starts_with(second)` / `ends_with(second)` |
| `StartsWith(second, IEqualityComparer<T>)` / `EndsWith(...)` | omitted (D3): `select(key).starts_with(map(key, second))` |

## 3. Detailed design
### 3.1 Signatures
```python
def starts_with(self, second: Iterable[TItem]) -> bool: ...
def ends_with(self, second: Iterable[TItem]) -> bool: ...
```
### 3.2 Semantics
- Kind: terminal. `starts_with`: streaming, short-circuits. `ends_with`: partial buffering (`deque(maxlen=len(second))`), always drains `self` unless a shortcut applies.
- **Equality**: L06's contract (`_equality.items_equal`: `a is b or a == b`, Python container semantics). NaN and cross-type numerics follow the README "Equality semantics" deviation.
- `starts_with` order of work (matches MoreLINQ): get the iterator of `self`, then iterate `second`; for each `b` pull one `a` from `self`; return False at the first mismatch or when `self` runs out; True when `second` is exhausted. So at most `len(second)` elements of `self` and `k + 1` elements of `second` are pulled when the first mismatch is at index `k`.
- `ends_with` order: if `second`'s count is unknown, materialise `second` first; `n == 0` → True **without iterating `self`** (.NET `TakeLast(0)` returns empty without enumerating); otherwise drain `self` into `deque(maxlen=n)` and compare.
- Known counts: `self` via N10's `_count_if_cheap()`; `second` counts as known only when it is a FlpList or a `list`/`tuple`/`range`/`str` (side-effect-free iteration; any other `second` is a plain iterable for this rule). When both are known and `len(second) > len(self)`, both return False without iterating anything (MoreLINQ's `ICollection` check). If `self`'s count was derived through `select` etc., the skipped selector calls are the same documented deviation as in M23.
- Empty cases: both empty → True; `second` empty → True; only `self` empty → False.
- Validation (eager): `second is None` → `ArgumentNoneError("second")`.
- None elements compare by the equality rule (`None is None`).
- Exceptions from either source or from an element's `__eq__` propagate.
- One-shot `self`: `starts_with` leaves the elements after the prefix in the iterator.

### 3.3 Implementation sketch
```python
def starts_with(self, second):
    _require_not_none(second, "second")
    n1, n2 = self._count_if_cheap(), _builtin_len(second)          # N10 helper; _builtin_len: len for FlpList/list/tuple/range/str else None
    if n1 is not None and n2 is not None:
        if n2 > n1:
            return False
        seq, other = self._indexable(), _indexable_of(second)      # L04 helper (list/tuple/range/str)
        if seq is not None and other is not None:
            return list(seq[:n2]) == list(other)                   # C-level, same identity-or-eq rule
    first_it = iter(self._source())
    for b in second:
        a = next(first_it, _MISSING)
        if a is _MISSING or not (a is b or a == b):                # inlined items_equal (L06)
            return False
    return True

def ends_with(self, second):
    _require_not_none(second, "second")
    n2 = _builtin_len(second)
    other = second if n2 is not None else list(second)            # MoreLINQ materialises second first
    n2 = len(other)
    if n2 == 0:
        return True
    n1 = self._count_if_cheap()
    if n1 is not None and n2 > n1:
        return False
    seq = self._indexable()
    tail = seq[-n2:] if seq is not None else deque(self._source(), maxlen=n2)
    return len(tail) == n2 and list(tail) == list(other)
```
- `starts_with`: O(min(n1, n2)) time, O(1) memory. `ends_with`: O(n1 + n2) time, O(n2) memory (buffer bounded by `len(second)`, plus `second` itself when it had to be materialised). The final `list == list` comparison is C-level and short-circuits at the first unequal pair with the same identity-or-eq rule as `items_equal`.
- **Sequence fast paths** (FlpList and FlpIt over list/tuple/range/str): slicing instead of pulling; observationally equivalent because these built-ins have no iteration side effects. Tests cover a `list` source and the `non_collection` fixture, as required by README §3.1.

### 3.4 Registry entries
```toml
[operators.starts_with]
category = "quantifier"
kind = "terminal"
buffering = "streaming"
short_circuit = true
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.StartsWith"
python_equivalent = "list(islice(xs, len(ys))) == list(ys)"
contract_args = "([0, 99],)"
contract_max_pull = 2
since = "0.4.0"   # adjust to the release that ships it
card = "M24"

[operators.ends_with]
category = "quantifier"
kind = "terminal"
buffering = "partial"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.EndsWith"
python_equivalent = "list(deque(xs, maxlen=len(ys))) == list(ys)"
contract_args = "([1, 2],)"
since = "0.4.0"
card = "M24"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design). MoreLINQ's 36 cases (int/char/string prefixes and suffixes, both empty, only first empty, enumerator disposal, comparer, collection-count shortcut) are a checklist; the comparer case becomes a `select(key)` composition test; disposal has no Python analogue (generators are not closed by the operator; documented). Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_starts_ends_with.py`, both `flp_type`s plus generator sources):
  - Prefix/suffix true, false at first/middle/last position, `second` longer, equal, empty; `self` empty.
  - Strings as sequences of characters: `flp.it("123").starts_with("12")`.
  - Pull counts: `starts_with` over `itertools.count()` with `second = [0, 1, 5]` pulls 3 from `self` and returns False; `second` as a generator is pulled `k + 1` times at a mismatch at index `k`.
  - `ends_with([])` on an infinite source returns True immediately; `ends_with` buffer bound: elements of a small class tracked in a `weakref.WeakSet` while draining a 10,000-element generator with `len(second) == 3`; never more than 4 alive at once.
  - Known-count shortcut: list subclass whose `__iter__` raises (per N10's rule) returns False without iteration when `second` is longer.
  - Equality rule: `[1]` vs `[1.0]` True, `[nan_obj]` vs same object True, distinct NaNs False, `None` vs `None` True.
  - Comparer replacement: `flp.it(["A", "b"]).select(str.lower).starts_with(map(str.lower, ["a"]))`.
  - `second=None` → `ArgumentNoneError`; one-shot remainder after `starts_with`.
- **Contracts** (auto): `starts_with` short-circuit bound, FlpList not mutated.
- **Typing** (`tests/typing/test_types_starts_ends_with.py`): both return `bool`; `second: Iterable[TItem]` rejects an obviously wrong element type under pyrefly (negative check via `# pyrefly: expect-error` if supported, else documented).

## 5. Differential harness
`difftest/specs/starts_with.toml`, `difftest/specs/ends_with.toml`; oracle `Operators/StartsEndsWith.cs` calling `MoreEnumerable.StartsWith/EndsWith` statically.
- `self` and `second` items: empty, singleton, `range(0, 10)`, prefixes/suffixes of it, mismatches at 0 / middle / end, longer `second`, strings, ints with nulls.
- Source kinds for both arguments: `counting`, `one_shot`, `throwing_at(i)`, plus `collection` opt-in to exercise the count shortcut.
- Probes: result, `trace` for both sources (pull order: `self.get_enumerator` before `second`, then alternating `second`/`self` pulls for `starts_with`; `second` fully before `self` for `ends_with` with a non-collection `second`).
- Expected: MATCH. Floats with NaN: `EXPECTED_DIFFERENCE` (README "Equality semantics", L06).

## 6. Benchmarks
`tests/benchmarks/test_bench_starts_ends_with.py`, sizes 1e3 / 1e5, `second` = first half (true case):
- `native` starts_with: `len(ys) <= len(data) and all(a == b for a, b in zip(data, ys))`; also reported: `data[:len(ys)] == ys` (list idiom).
- `native` ends_with: `list(deque(iter(data), maxlen=len(ys))) == ys`.
- `flpit-FlpIt` over a generator (generic path) and `flpit-FlpList` (slice fast path).
- Targets: ≤ 1.5× vs the `zip`/`all` and `deque` idioms (the prototype loop measured ~1.1×); the FlpList path should be within 1.3× of the slicing idiom.

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.StartsWith(second)` / `EndsWith`; equality rule (link to README "Equality semantics"); comparer replacement by `select(key)`; `Execution: Terminal; starts_with short-circuits at the first mismatch; ends_with buffers len(second) elements`; doctests:
  ```python
  >>> flp.it([1, 2, 3]).starts_with([1, 2])
  True
  >>> flp.it([1, 2, 3]).ends_with([2, 3])
  True
  >>> flp.it([1, 2, 3]).ends_with([0, 1, 2, 3])
  False
  ```
- Translation map: MoreLINQ `.StartsWith(ys)` / Python `list(islice(xs, len(ys))) == ys`, `str.startswith` → `.starts_with(ys)`; `.EndsWith(ys)` / `deque(xs, maxlen=len(ys))` → `.ends_with(ys)`.
- No new deviation beyond L06's equality section (referenced).

## 8. Expected outcomes
- Prefix/suffix tests on all four types with bounded memory and documented pull order.
- difftest specs 0 MISMATCH including two-source traces.

## 9. Verification
VERIFY-std with `<op>=starts_with` and `<op>=ends_with`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_starts_ends_with.py
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).starts_with([0, 1, 2]))"   # True (terminates)
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).ends_with([]))"            # True (terminates)
```

## 10. Definition of Done
DoD-std, plus: equality goes through L06's rule (inlined form covered by a test that compares it with `items_equal` on a property-based sample).

## 11. Risks / open questions
- Cross-card: L14 `sequence_equal` should use the same equality rule and the same "no comparer, compose with `select`" decision, so that `a.sequence_equal(b)`, `a.starts_with(b)` and `a.ends_with(b)` agree on every pair of inputs. Flag to the L14 owner.
- If N10's `_count_if_cheap` / L04's `_indexable` helpers have different names when they land, follow them; the shortcut rules are what matters.
