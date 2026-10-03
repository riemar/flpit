---
id: B09
title: to_list
status: todo
priority: 060
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ToListTests.cs @ dotnet/runtime main 6f1d9331 (25 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# B09: `to_list` (backfill + FlpList construction fast path)

## 1. Goal
`to_list` is the materialiser every pipeline ends with, yet `ToListTests.cs` is not ported. Semantics are already right (`FlpIt.to_list` builds a new `FlpList`; `FlpList.to_list` returns a shallow copy, as `ToList_AlwaysCreateACopy` requires). The defect is cost: every `FlpList(...)` goes through `UserList[TItem](...)` (a `GenericAlias` call plus a `UserList` wrapper), ~1.4 µs per instance vs 0.09 µs for `list(...)`, and `FlpList.to_list()` is ≈ 3.2× `list.copy()` at 1e5. That overhead is paid by every `to_list`, every `chunk` (B06) and every window (M02). This card ports the tests and adds a private no-copy constructor.

## 2. Scope
**In:** `to_list()` on `_LinqOps` (FlpIt) with overrides on `FlpList` (copy) and `OrderedIt` (adopt the sorted buffer); `FlpList` storing a plain `list` internally (drop the inner `UserList`) and a private `FlpList._adopt(lst)`; port of `ToListTests.cs`.
**Out:** `to_array` (no Python analogue beyond `tuple(q)`); capacity pre-sizing (CPython `list()` already uses `__length_hint__`).

## 3. Detailed design
### 3.1 Signatures
```python
def to_list(self) -> FlpList[TItem]: ...

@classmethod
def _adopt(cls, items: list[TItem]) -> FlpList[TItem]: ...   # private: takes ownership, no copy
```
.NET `ToList(source)` maps 1:1 (single overload).

### 3.2 Semantics
- Kind: terminal (materialiser). Buffering: full. Short-circuit: no (enumerates the whole source once).
- Always returns a **new** `FlpList`, never `self`, never sharing storage with the source (`FlpList.to_list()` is a shallow copy; elements are the same objects, `ToList_ProduceCorrectList` checks identity).
- One-shot sources are consumed; a second `to_list()` on the same one-shot query returns `[]` (Python semantics, consistent with the README).
- Exceptions raised by the source propagate; no partial list is returned.
- `_adopt` invariant: the caller must not keep or mutate the list afterwards. Used only internally (`to_list`, `chunk`, windows, `OrderedIt`).

### 3.3 Implementation sketch
```python
class FlpList(Collection[TItem], Generic[TItem]):
    __slots__ = ("_data",)                     # plain list; replaces self.__list (UserList)
    def __init__(self, source=_SENTINEL):
        ...; self._data = [] if source is _SENTINEL else list(source)
    @classmethod
    def _adopt(cls, items):
        obj = object.__new__(cls); obj._data = items; return obj
    def to_list(self):                         # FlpList override
        return FlpList._adopt(self._data.copy())

def to_list(self):                             # _LinqOps default (FlpIt, Grouping)
    return FlpList._adopt(list(self))

def to_list(self):                             # OrderedIt override
    return FlpList._adopt(self._sorted_buffer())   # the private sorted list, no second copy
```
- O(n) time, O(n) memory; `list(self)` and `.copy()` are C-level. `_guard_empty` and other `self.__list.data` users switch to `self._data` (mechanical). Observable behaviour is unchanged: `repr`, equality, slicing, `add`/`add_range` keep their current results.
- If F05 has already flattened `FlpList` storage, this card only adds `_adopt` and the overrides.

### 3.4 Registry entry
```toml
[operators.to_list]
category = "conversion"
kind = "terminal"
buffering = "full"
short_circuit = false
dotnet = "Enumerable.ToList"
python_equivalent = "list(xs)"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_to_list.py` from `ToListTests.cs` (25):
  - Ported now (14): `ToList_AlwaysCreateACopy` (`is not` + equal, on `FlpList`), `ToList_WorkWithEmptyCollection` and `ToList_ProduceCorrectList` (`RunToListOnAllCollectionTypes` → list, tuple, `NonCollectionIterable`, read-only `Sequence`, `Collection`; string identity checked with `is`), `RunOnce`, `ToList_ArrayWhereSelect`, `ToList_ListWhereSelect`, `ToList_IListWhereSelect` (3 rows each; `ReadOnlyCollection` → `tuple`), `SameResultsRepeatCallsFromWhereOnIntQuery`, `...OnStringQuery`, `SourceIsEmptyICollectionT`, `SourceIsICollectionTWithFewElements`, `SourceNotICollectionAndIsEmpty`, `SourceNotICollectionAndHasElements`, `SourceNotICollectionAndAllNull`.
  - Written now, active once L01 `skip` lands (8, F08 `requires_op`): `ConstantTimeCount*` (4: `flp.range(...).select(...).skip(...).take(...)`), `NonConstantTimeCount*` (4: `order_by` + `select` + `skip` + `take`).
  - Skips: `INTERNAL_OPTIMIZATION` 2 (`ToList_TouchCountWithICollection`, `ToList_UseCopyToWithICollection`: assert `Count`/`CopyTo` call counts); `OTHER` 1 (`ToList_ThrowArgumentNullExceptionWhenSourceIsNull`).
  - Target: 22/25 = 88 % once L01 is merged; 14/25 = 56 % otherwise.
- **Own unit tests** (`tests/unit/test_to_list.py`):
  - `flp.lst(x).to_list()` mutated via `add` does not change the original, and vice versa.
  - `order_by(k).to_list()` result mutation does not affect a second enumeration of the same ordered query.
  - `FlpList._adopt` is not exported (`"_adopt" not in dir(flpit)`), and the existing FlpList behaviour suites (moved by F02) stay green after the storage change.
  - Source raising midway: exception propagates, nothing returned.
- **Contracts** (auto, `kind = "terminal"`): FlpList not mutated.
- **Typing**: `assert_type(flp.it([1]).to_list(), FlpList[int])`; `OrderedIt[str].to_list()` → `FlpList[str]`.

## 5. Differential harness
`difftest/specs/to_list.toml`: sources {empty, singleton, ints, nullable ints, strings} with pipelines `where`/`select`/`order_by`/`take` (and `skip` once L01 exists) ending in `to_list`; probe: copy independence (mutate result, re-enumerate source). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_to_list.py`, sizes 1e3 and 1e5, plus a "many small lists" case (1e5 lists of 5):
- `native`: `list(data)` (FlpIt variant), `data.copy()` (FlpList variant), `[list(t) for t in tuples]` (small lists).
- `flpit-FlpIt`: `flp.it(data).to_list()`; `flpit-FlpList`: `flp.lst(data).to_list()`; small: `[flp.lst(t) for t in tuples]` vs `FlpList._adopt(list(t))`.
- Target ≤ 1.3× (buffering). Today: FlpIt ≈ 1.4×, FlpList ≈ 3.2×, small lists ≈ 15×.

## 7. Docs
- Docstring: `.NET: Enumerable.ToList()`; always a new `FlpList` (shallow copy for `FlpList`); terminal, consumes one-shot sources. Doctest: `flp.it(x for x in "ab").to_list()` → `['a', 'b']`.
- Translation map: `.ToList()` / `list(xs)` / `xs.copy()` → `.to_list()`.

## 8. Expected outcomes
- `FlpList` construction cost close to `list()`; `to_list` within 1.3× of native.
- B06 and M02 meet their benchmark targets through `_adopt`.
- 14 ported tests green now, 22 after L01.

## 9. Verification
VERIFY-std with `<op>=to_list`, plus:
```bash
uv run pytest -q tests/nettests/test_to_list.py -rs
uv run python -c "from flpit import flp; a = flp.lst([1]); b = a.to_list(); b.add(2); print(a, b)"   # [1] [1, 2]
uv run python -m timeit -s "from flpit import FlpList; t = (1, 2, 3, 4, 5)" "FlpList(t)"            # well under 1 µs
```

## 10. Definition of Done
DoD-std, plus: the PR reports `FlpList(...)` construction time before/after; no public API change (`_adopt` is private).

## 11. Risks / open questions
- Touches `FlpList` internals that F05 may also restructure; coordinate (if F05 lands first, rebase onto its storage layout).
- `__slots__` on `FlpList` forbids ad-hoc attributes on instances; acceptable (none are documented), but noted in CHANGELOG.
