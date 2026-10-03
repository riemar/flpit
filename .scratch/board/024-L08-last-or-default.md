---
id: L08
title: last_or_default
status: todo
priority: 024
effort: S
depends_on: [F05, F06, F07, F08, F09, L04, L07]
upstream:
  dotnet: LastOrDefaultTests.cs @ dotnet/runtime main 6f1d9331 (24 [Fact]/[Theory]); LastTests.cs (18) already ported as tests/nettests/test_last.py
  morelinq: n/a
pr:
---

# L08: `last_or_default`

## 1. Goal
The non-throwing twin of `last`, in the D5 shape established by L07. It unblocks two `tests/nettests/test_order_by.py` cases that are skipped today ("last_or_default needs to be implemented") and aligns `last` on list-like sources with .NET's backward scan.

## 2. Scope
**In:** `last_or_default()` / `(predicate)` / `(default=...)` / `(predicate, default=...)` on `_LinqOps`; a shared `_last_or_missing` used by `last` too; `Sequence` fast path via `_indexable()` (L04); un-skip `test_LastOnOrderedMatchingCases` and `test_LastOrDefaultOnOrdered` in `tests/nettests/test_order_by.py`.
**Out:** O(n) `OrderedIt.last` without sorting (follow-up proposed in L07). No legacy shim (new operator).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def last_or_default(self) -> TItem | None: ...
@overload
def last_or_default(self, predicate: Callable[[TItem], object]) -> TItem | None: ...
@overload
def last_or_default(self, *, default: TDefault) -> TItem | TDefault: ...
@overload
def last_or_default(self, predicate: Callable[[TItem], object], *, default: TDefault) -> TItem | TDefault: ...
```
| .NET | Python |
|---|---|
| `LastOrDefault()` | `last_or_default()` |
| `LastOrDefault(TSource defaultValue)` | `last_or_default(default=v)` |
| `LastOrDefault(predicate)` | `last_or_default(predicate)` |
| `LastOrDefault(predicate, TSource defaultValue)` | `last_or_default(predicate, default=v)` |

### 3.2 Semantics
- Kind: terminal. Generic path: no short-circuit, the whole source is read (the last match can only be known at the end). Indexable path: O(1) without predicate, backward scan stopping at the first match from the end with a predicate.
- **Predicate call order** (observable): on `list`/`tuple`/`range`/`str`/`FlpList` sources the predicate is called from the end backwards and stops at the first match, exactly like .NET for `IList<T>`; on other sources it is called once per element, front to back. `FlpList.last` already scans backwards today; `FlpIt(list).last(pred)` scans forward today. This card makes both `last` and `last_or_default` follow the .NET rule on every type (documented in the docstring; the change to `last` is listed in CHANGELOG under `Changed`).
- Empty / no match → `default` (`None` unless given). Exceptions from source/predicate propagate; nothing is caught.
- Validation (eager): `predicate=None` → `ArgumentNoneError("predicate")` (a `PredicateNoneError` subclass after F05, so `test_last.py::test_NullPredicate` keeps passing).
- `None` elements are values (same ambiguity note as L07).
- `OrderedIt`: sorts, returns the last element of the stable order (last among equal keys), which is what `test_LastOnOrderedMatchingCases` asserts.

### 3.3 Implementation sketch
```python
def _last_or_missing(self, predicate):
    if predicate is not _SENTINEL:
        _require_not_none(predicate, "predicate")
    seq = self._indexable()                                  # L04 helper
    if seq is not None:
        if predicate is _SENTINEL:
            return seq[-1] if len(seq) else _MISSING
        return next(filter(predicate, reversed(seq)), _MISSING)
    if predicate is _SENTINEL:
        tail = deque(self, maxlen=1)                         # C-level drain
        return tail[0] if tail else _MISSING
    result = _MISSING
    for item in self:
        if predicate(item):
            result = item
    return result

def last(self, predicate=_SENTINEL): ...                    # raises EmptySequenceError / NoMatchError on _MISSING
def last_or_default(self, predicate=_SENTINEL, *, default=None):
    result = self._last_or_missing(predicate)
    return default if result is _MISSING else result
```
- Generic: O(n) time, O(1) memory. Indexable: O(1) / O(n − i) with i the index of the last match.
- The indexable path is observationally different only in predicate call order, and that difference is the .NET behaviour (see 3.2); results and exceptions are otherwise identical.

### 3.4 Registry entry
```toml
[operators.last_or_default]
category = "element"
kind = "terminal"
buffering = "streaming"
short_circuit = false        # generic path; list-like sources stop early (documented)
dotnet = "Enumerable.LastOrDefault"
python_equivalent = "xs[-1] if xs else default / deque(xs, maxlen=1)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_last_or_default.py` from `LastOrDefaultTests.cs` (24): `default(int)` expectations rewritten to `is None` (`# NO_VALUE_TYPES`), `LastOrDefault(v)` → `last_or_default(default=v)`, `NullSource*` → `SourceNoneError`, `NullPredicate` → `ArgumentNoneError`. Target 100 %.
- **Un-skipped** in `tests/nettests/test_order_by.py`: `test_LastOnOrderedMatchingCases`, `test_LastOrDefaultOnOrdered`.
- **Own unit tests** (`tests/unit/test_last_or_default.py`):
  - Predicate call order: on `flp.it([1, 2, 3, 4])` and `flp.lst(...)` with `is_odd`, calls are `[4, 3]`; on the `non_collection` fixture calls are `[1, 2, 3, 4]`. Same for `last`.
  - Generic path drains the source exactly once; one-shot sources are consumed.
  - Predicate raising `NoMatchError` propagates (no swallowing).
  - Eager `ArgumentNoneError` on an empty source.
- **Contracts** (auto): terminal, FlpList not mutated; short-circuit contract skipped for this op (`short_circuit = false`).
- **Typing**: `assert_type(xs.last_or_default(), int | None)`, `assert_type(xs.last_or_default(default=0), int)`, `assert_type(xs.last_or_default(pred, default=""), int | str)`.

## 5. Differential harness
`difftest/specs/last_or_default.toml`: oracle sources typed `int?`/`string`; collection kinds `list` (→ C# `List<int?>`) and `non_collection` (→ iterator method) so the `predicate_calls_order` probe compares the backward/forward rule in both runtimes; defaults `{omitted, 0, None}`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_last_or_default.py`, sizes 1e3 / 1e5:
- `native` (list, no predicate): `data[-1] if data else None`; (list, predicate matching at index `size // 2`): `next(filter(pred, reversed(data)), None)`; (iterator): `deque(iter(data), maxlen=1)`
- `flpit-FlpIt` (list source and `iter()` source) / `flpit-FlpList`
- Target ratio ≤ 1.5×.

## 7. Docs
- Docstring: `.NET: Enumerable.LastOrDefault`; backward scan on list-like sources; D5 `default`; Execution: Terminal, reads the whole source unless the source is list-like.
- Doctests: `flp.it([1, 2, 3, 4]).last_or_default(lambda x: x % 2 == 1)` gives `3`; `flp.it([]).last_or_default(default=0)` gives `0`.
- Translation map: `xs[-1] if xs else d` / `.LastOrDefault(d)` → `.last_or_default(default=d)`; `.LastOrDefault(p)` → `.last_or_default(p)`.

## 8. Expected outcomes
- `last_or_default` on all four types; 24 ported tests + 2 un-skipped order_by tests green.
- `last` and `last_or_default` share one implementation and the .NET predicate-order rule on every type.

## 9. Verification
VERIFY-std with `<op>=last_or_default`, plus:
```bash
uv run pytest -q tests/nettests/test_last_or_default.py tests/nettests/test_last.py tests/nettests/test_order_by.py -rs
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3, 4]).last_or_default(lambda x: x % 2 == 1), flp.it([]).last_or_default(default=0))"   # 3 0
```

## 10. Definition of Done
DoD-std, plus CHANGELOG `Changed` entry for the `last(pred)` call-order alignment on `FlpIt` over list-like sources.

## 11. Risks / open questions
- Someone relying on forward predicate side effects in `flp.it(list).last(pred)` sees a change; it is the documented .NET behaviour and already how `FlpList.last` works.
