---
id: M08
title: split
status: todo
priority: 069
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Split.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; SplitTest.cs has 4 [Test]/[TestCase])
pr:
---

# M08: `split`

## 1. Goal
`split` breaks a sequence at separator elements (a value or a predicate), like `str.split` but for any iterable: token streams split on delimiters, CSV-like records split on blank lines, protocol frames split on markers. It complements `segment` (M07), which keeps the boundary element; `split` drops it.

## 2. Scope
**In:** `split(...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`) with a separator value **or** a separator predicate, an optional maximum split `count`, and an optional `result_selector`.
**Out:** comparer overloads (D3; use the predicate form, e.g. `predicate=lambda x: x.lower() == ","`); keeping trailing empty parts (MoreLINQ drops them, see §3.2).

**MoreLINQ overload mapping** (10 overloads)
| MoreLINQ | flpit |
|---|---|
| `Split(separator)` / `Split(separator, count)` | `split(separator)` / `split(separator, count)` |
| `Split(separator, resultSelector)` / `(separator, count, resultSelector)` | `split(separator, [count], result_selector=f)` |
| `Split(separator, comparer[, count][, resultSelector])` (4 overloads) | omitted, D3 → predicate form |
| `Split(Func<T,bool> separatorFunc[, count][, resultSelector])` (4 overloads) | `split(predicate=f, [count=n], [result_selector=g])` |

The predicate is keyword-only because a separator value may itself be callable (splitting a list of functions); runtime "is it callable?" dispatch would be ambiguous.

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def split(self, separator: TItem, count: int | None = None) -> FlpIt[FlpList[TItem]]: ...
@overload
def split(self, separator: TItem, count: int | None = None, *,
          result_selector: Callable[[FlpList[TItem]], TResult]) -> FlpIt[TResult]: ...
@overload
def split(self, *, predicate: Callable[[TItem], bool], count: int | None = None) -> FlpIt[FlpList[TItem]]: ...
@overload
def split(self, *, predicate: Callable[[TItem], bool], count: int | None = None,
          result_selector: Callable[[FlpList[TItem]], TResult]) -> FlpIt[TResult]: ...
```
Implementation signature: `split(self, separator=_SENTINEL, count=None, *, predicate=_SENTINEL, result_selector=_SENTINEL)`. `separator=None` is a valid separator (splits on `None` values).

### 3.2 Semantics (mirrors MoreLINQ exactly)
- Kind: intermediate, deferred. Buffering: partial (current part). Short-circuit: n/a.
- An element is a separator when `predicate(item)` is truthy, or for the value form when `item is separator or item == separator` (Python container equality, as in `list.__contains__`).
- Each separator ends the current part, which is yielded (possibly empty). Consecutive separators → empty parts; a leading separator → a leading empty part.
- **The trailing part is yielded only if non-empty**: `[1, 0]` split on `0` → `[[1]]`; `[0]` → `[[]]`; `[]` → `[]`. (Differs from `str.split`; documented.)
- `count` = maximum number of splits (separators honoured). After `count` separators, later separators are ordinary elements of the final part, and **the predicate is no longer called** (MoreLINQ short-circuits `count > 0 && pred(x)`). `count=None` means unlimited.
- Validation (eager): exactly one of `separator` / `predicate` must be given, else `TypeError("split() takes either a separator or predicate=")`; `predicate=None` / `result_selector=None` → `ArgumentNoneError`; `count` via `_require_index`, `count <= 0` → `ArgumentOutOfRangeError("count")` (MoreLINQ rejects 0, unlike `str.split(maxsplit=0)`).
- Parts are fresh `FlpList` objects; `result_selector` receives that `FlpList` and is called once per part, in order, right before the part is yielded.
- Exceptions from source/predicate/selector propagate at enumeration; re-enumeration re-runs everything.

### 3.3 Implementation sketch
```python
def _generator():
    remaining = count            # None = unlimited
    part: list | None = None
    for item in src:                                   # src = self._source() (F05)
        if remaining != 0 and is_sep(item):        # is_sep bound once: predicate or identity/== check
            yield emit(part or [])
            if remaining is not None:
                remaining -= 1
            part = None
        else:
            (part := part if part is not None else []).append(item)
    if part:
        yield emit(part)
```
- `emit` is `FlpList` or `lambda p: result_selector(FlpList(p))`, chosen once. The unlimited value form uses a specialised loop (`item is sep or item == sep` inlined) to avoid a call per element.
- O(n) time, O(largest part) memory. **FlpList fast path**: none (no index trick avoids the per-element test).

### 3.4 Registry entry
```toml
[operators.split]
category = "grouping"
kind = "intermediate"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.Split"
python_equivalent = "manual loop; str.split for strings"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `SplitTest.cs` (4 cases) as checklist, all covered: separator + result transformation, max count, separator predicate, predicate + max count (with `None` elements). Target: 100 %. The comparer overloads have no upstream tests; they are omitted (`COMPARER_NOT_SUPPORTED` would apply).
- **Own unit tests** (`tests/unit/morelinq/test_split.py`, both `flp_type`s):
  - `[1, 0, 2, 3, 0, 4].split(0)` → `[[1], [2, 3], [4]]`; leading, consecutive and trailing separators (`[0, 1, 0]` → `[[], [1]]`, `[0, 0]` → `[[], []]`).
  - `count=1` on `[1, 0, 2, 0, 3]` → `[[1], [2, 0, 3]]`; predicate call log stops after the last honoured split.
  - Splitting on `None`; splitting a list of callables by value (proves no callable dispatch); `float("nan")` object matched by identity.
  - `result_selector` called once per part, receives an `FlpList`; `"".join` on characters.
  - Validation: both/neither of separator and predicate, `count ∈ {0, -1, None, 1.5}`, `predicate=None`, all raised at call time.
  - Streaming: the first part is yielded right after the first separator is pulled (counting source).
- **Contracts:** auto via registry.
- **Typing** (`tests/typing/test_types_split.py`): value form → `FlpIt[FlpList[int]]`; with `result_selector=len` → `FlpIt[int]`; predicate form.

## 5. Differential harness
`difftest/specs/split.toml`, oracle calls `MoreEnumerable.Split` (separator and `Func<T,bool>` overloads, pinned `morelinq` NuGet). Domains: empty, only separators, leading/trailing/consecutive separators, ints and strings with nulls; `count ∈ {omitted, 1, 2, len, -1, 0}`; predicates from a catalogue incl. one that throws. Probes: parts, predicate call log, exception type at call time. Expected: MATCH; `EXPECTED_DIFFERENCE` for separators that are distinct NaN objects (.NET `double.Equals(NaN, NaN)` is true, Python `==` is false).

## 6. Benchmarks
`tests/benchmarks/test_bench_split.py`, sizes 1e3 / 1e5, ints with a `0` every ~8 elements:
- `native`: idiomatic loop appending to `cur` and pushing on `x == 0` (no trailing empty part), materialised to a list of lists.
- `flpit-FlpIt` / `flpit-FlpList`: `split(0).to_list()`; extra group `split(predicate=lambda x: x == 0)`.
- Target ratio ≤ 1.3×.

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Split(separator | separatorFunc, [count], [resultSelector])`; Args incl. the trailing-part rule and the meaning of `count`; Raises; `Execution:` deferred, buffers one part.
- Doctest:
  ```python
  >>> flp.it([1, 0, 2, 3, 0, 4]).split(0).to_list()
  [[1], [2, 3], [4]]
  >>> flp.it("the quick brown fox").split(" ", 2, result_selector="".join).to_list()
  ['the', 'quick', 'brown fox']
  ```
- Translation map: `.Split(sep)` / `str.split(sep, maxsplit)` → `.split(sep, count)`; `.Split(x => ...)` → `.split(predicate=...)`.
- Deviations (README): equality is Python container equality (`is` or `==`); trailing empty part dropped unlike `str.split` (MoreLINQ behaviour, kept on purpose).

## 8. Expected outcomes
- `split` on all four types with value and predicate forms; ~15 own tests; difftest 0 MISMATCH; benchmark recorded.

## 9. Verification
VERIFY-std with `<op>=split`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_split.py
uv run python -c "from flpit import flp; print(flp.it([1,0,2,0,3]).split(0, 1).to_list())"   # [[1], [2, 0, 3]]
uv run python -c "from flpit import flp; print(flp.it([0, 1, 0]).split(0).to_list())"       # [[], [1]]
```

## 10. Definition of Done
DoD-std, plus the README deviation entry "split: trailing empty part, equality" exists.

## 11. Risks / open questions
- `count` name versus Python's `maxsplit`: proposal `count` (MoreLINQ name, LINQ-first library); the docstring says "like `maxsplit`".
- The trailing-part asymmetry surprises Python users; keeping MoreLINQ semantics is what difftest verifies. Revisit only with a separate keyword, never by changing the default.
