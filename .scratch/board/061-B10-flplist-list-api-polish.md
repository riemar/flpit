---
id: B10
title: FlpList List<T> API polish (exceptions, validation, docs)
status: todo
priority: 061
effort: S
depends_on: [F05, F06, F08]
upstream:
  dotnet: List<T> tests (System.Collections.Generic), already ported on main as tests/nettests/test_generic_list.py (eea2097, 48 tests, 10 skips)
  morelinq: n/a
pr:
---

# B10: `FlpList` `List<T>` API polish

## 1. Goal
`main @ eea2097` (riemar) added the `List<T>` instance API to `FlpList`: `insert`, `insert_range`, `remove`, `remove_all`, `remove_at`, `remove_range`, `clear`, `contains`, `exists`, `find`, `find_all` and `reverse()` / `reverse(index, count)`, with 95 ported test cases. Its commit message notes that exception types and messages still need polishing for .NET fidelity. This card finishes that work on top of the F05 validation and exception framework, so the `List<T>` surface has the same quality bar as the LINQ operators (D28).

## 2. Scope
**In**
- Exceptions aligned with `List<T>` and the F05 taxonomy:
  - argument range errors (`index`, `count`, invalid range) → `ArgumentOutOfRangeError` with .NET parameter names and messages (`Index was out of range. Must be non-negative and less than the size of the collection. (Parameter 'index')`, etc.). **Decided (maintainer, 2026-10-04): `ArgumentOutOfRangeError` also subclasses `IndexError`**, i.e. `class ArgumentOutOfRangeError(ValueError, IndexError)`, so existing `except IndexError` code (including riemar's `List<T>` tests on `main`) keeps working.
  - `None` callables/collections → `ArgumentNoneError` subclasses (`PredicateNoneError`, `CollectionNoneError`, `ArgumentNoneError("match")`).
- Validation bugs found while re-evaluating on 2026-10-04:
  - `remove_at(len)` passes the guard (`index > len` instead of `>=`) and fails with Python's raw `IndexError: list assignment index out of range`.
  - `exists(None)` raises `TypeError: 'NoneType' object is not callable` instead of the predicate-none error (`find`, `find_all` and `remove_all` already validate).
  - `insert_range(index, collection)` materialises the collection before validating `index` (order differs from .NET, which checks `index` first). Benign, but it should be aligned.
- Un-skip what the polish enables among the 10 skips in `test_generic_list.py`; categorise the rest with F08 categories.
- Docstrings (F06 standard, `.NET: List<T>.X`) and registry entries with `origin = "dotnet-list"` so the README matrix and skill reference include them.
- Remaining `List<T>` members, decided here (proposals): `index_of`/`last_index_of`/`find_index`/`find_last_index`/`find_last` (cheap, common: add), `true_for_all` (= LINQ `all`: add as an alias for parity), `get_range` (returns `FlpList` copy: add), `sort`/`sort(key)` (in place, stable: add), `convert_all` (= `select().to_list()`: add), `binary_search`, `copy_to`, `capacity`, `ensure_capacity`, `trim_excess` (n/a in Python: skip, documented).

**Out:** the LINQ operators themselves (other cards); the `count()` vs `Count` property deviation (already documented).

## 3. Detailed design
### 3.1 Signatures (new members)
```python
def index_of(self, item: TItem, index: int = 0, count: int | None = None) -> int: ...   # -1 when absent
def last_index_of(self, item: TItem, index: int | None = None, count: int | None = None) -> int: ...
def find_index(self, match: Callable[[TItem], bool], start: int = 0, count: int | None = None) -> int: ...
def find_last(self, match: Callable[[TItem], bool]) -> TItem | None: ...
def find_last_index(self, match: Callable[[TItem], bool], start: int | None = None, count: int | None = None) -> int: ...
def true_for_all(self, match: Callable[[TItem], bool]) -> bool: ...
def get_range(self, index: int, count: int) -> FlpList[TItem]: ...
def sort(self, key: Callable[[TItem], Any] | None = None, *, reverse: bool = False) -> None: ...
def convert_all(self, converter: Callable[[TItem], TResult]) -> FlpList[TResult]: ...
```
### 3.2 Semantics
- All of these are eager instance methods (they mutate or return materialised values); none returns `FlpIt`.
- `find`/`find_last` return `None` when not found (the reference-type `default(T)`); documented, and the same convention as `*_or_default` (D5).
- `sort` uses `list.sort` (stable); .NET `List<T>.Sort` is unstable. This is a stricter guarantee and is documented, not a deviation that tests can observe.
### 3.3 Implementation sketch
Thin wrappers over the backing `list` with F05 validators; index/count checks mirror `List<T>` order (index, then count, then range).
### 3.4 Registry
One entry per member, `origin = "dotnet-list"`, `classes = ["FlpList"]`, `kind = "terminal"` (or `"mutator"` added to the enum for in-place methods).

## 4. Tests
- `tests/nettests/test_generic_list.py`: exception assertions upgraded to type + param name; skips re-categorised; target ≥ 90 % of the upstream cases ported.
- Own unit tests for the new members and both validation bugs (regression).
- Contracts: mutators are excluded from the "FlpList not mutated" contract via `kind = "mutator"`.

## 5. Differential harness
Optional: `List<T>` operations can run in the oracle (`new List<T>(src)`), with a `mutator` scenario kind that compares the resulting list plus the return value. Proposed for X01, not required here.

## 6. Benchmarks
Only for `index_of`, `find_index` and `sort` vs `list.index`/loop/`list.sort` (expected ≈ 1.0–1.1×).

## 7. Docs
README "FlpList and `List<T>`" section: table of `List<T>` members → `FlpList`, the D28 rule (`List<T>` wins on name clashes, `as_enumerable()` for LINQ), and the in-place `reverse` note. Skill reference picks them up through the registry.

## 8. Expected outcomes
`FlpList` behaves like `List<T>` including exceptions; the two validation bugs are fixed; the `List<T>` surface is documented and discoverable.

## 9. Verification
VERIFY-std, plus:
```bash
uv run pytest -q tests/nettests/test_generic_list.py -rs
uv run python -c "from flpit import flp; flp.lst([1,2,3]).remove_at(3)"     # ArgumentOutOfRangeError (Parameter 'index')
uv run python -c "from flpit import flp; flp.lst([1]).exists(None)"         # PredicateNoneError
```

## 10. Definition of Done
DoD-std, plus the `List<T>` member table in README, and a test asserting `issubclass(ArgumentOutOfRangeError, IndexError)` and `issubclass(ArgumentOutOfRangeError, ValueError)`.

## 11. Risks / open questions
- Resolved: `ArgumentOutOfRangeError(ValueError, IndexError)`. Multiple inheritance from two built-in exceptions is valid because both share `Exception` with a compatible layout. F05 defines the class this way from the start.
- Coordinate with riemar, who authored the `List<T>` API, before changing its exception types.
