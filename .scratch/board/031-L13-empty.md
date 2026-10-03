---
id: L13
title: flp.empty
status: todo
priority: 031
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: EmptyEnumerable.cs @ dotnet/runtime main 6f1d9331 (3 [Fact]/[Theory]); there is no EmptyTests.cs
  morelinq: n/a
pr:
---

# L13: `flp.empty`

## 1. Goal
A typed empty query, `flp.empty(int)`, for initial values of folds and unions (`acc = flp.empty(Order)`, then `acc = acc.concat(batch)`), for "no results" return values that keep the `FlpIt[T]` type, and as the shared empty instance that `take(0)`/`take_last(0)` can return. It completes the factory set (`it`, `lst`, `range`, `repeat`) with .NET's `Enumerable.Empty<T>()`.

## 2. Scope
**In:** `flp.empty()` / `flp.empty(item_type)` in `src/flpit/flp.py`; a module-level singleton in `linq.py`; reuse of the singleton for `count <= 0` in `take` and `take_last` (L04); registry entry of kind `factory`.
**Out:** an empty `FlpList` factory (`flp.lst()` with no argument already exists via `FlpList()`); a `FlpIt.empty()` classmethod (one spelling only, matching the other factories).

## 3. Detailed design
### 3.1 Signatures
```python
# src/flpit/flp.py
@overload
def empty() -> FlpIt[Any]: ...
@overload
def empty(item_type: type[TItem], /) -> FlpIt[TItem]: ...
def empty(item_type: type[Any] | None = None, /) -> FlpIt[Any]: ...
```
| .NET | Python |
|---|---|
| `Enumerable.Empty<TResult>()` | `flp.empty(TResult)` (type argument as a positional, typing only) or `flp.empty()` |

- `flp.empty()` returns `FlpIt[Any]` so that `xs: FlpIt[Order] = flp.empty()` type-checks (`FlpIt` is invariant in `TItem`, so `FlpIt[Never]` would not be assignable).
- `flp.empty(int)` returns `FlpIt[int]`, the explicit spelling of .NET's type argument. Union/generic item types (`int | None`, `list[int]`) are not `type[T]` for every checker; the docs show `cast`-free alternatives: `xs: FlpIt[int | None] = flp.empty()`.

### 3.2 Semantics
- Kind: factory. Buffering: n/a (no elements). Re-iterable, any number of times.
- **Singleton:** every call returns the same object (`flp.empty() is flp.empty(str)`), mirroring `.NET`'s cached `Enumerable.Empty<T>()` (upstream `EmptyEnumerableCachedTest`). Python erases the type argument, so one instance serves all `T`. Safe because `FlpIt` exposes no mutator (only the private `_iterable` slot) and its source is the immutable `()`.
- `item_type` is **not** validated or inspected at runtime (zero cost, like `as_type`); passing `None` is the same as omitting it.
- All operators work on it: `count() == 0`, `first_or_default() is None`, `default_if_empty(1).to_list() == [1]`, `contains(x)` is `False`.
- `take(n)` with `n <= 0` and `take_last(n)` with `n <= 0` return the singleton (observable only through `is`; no test outside this card may rely on identity).

### 3.3 Implementation sketch
```python
# linq.py
_EMPTY: Final[FlpIt[Any]] = FlpIt(())

# flp.py
def empty(item_type=None, /):
    """Returns the shared empty query (.NET Enumerable.Empty<T>())."""
    return _EMPTY
```
- O(1) time and memory; no allocation per call.
- `iter(_EMPTY)` returns a fresh `tuple_iterator` each time (cheap); upstream's "same enumerator instance" assert is not reproduced (see 4).

### 3.4 Registry entry
```toml
[operators.empty]
category = "generation"
kind = "factory"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Empty"
python_equivalent = "iter(())"
entry_point = "flp.empty"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_empty.py` from `EmptyEnumerable.cs` (3; `UPSTREAM.toml` maps the non-standard file name):
  - `EmptyEnumerableCachedTest`: `flp.empty(int) is flp.empty(int)` and, stronger than .NET, `is flp.empty(str)`.
  - `EmptyEnumerableIsIndeedEmpty`: `list(flp.empty(T)) == []`, `count() == 0` for `int`, `str`, `object`; the `Assert.Same(GetEnumerator())` line is dropped (`INTERNAL_OPTIMIZATION`).
  - `NO_SPAN_OR_ARRAY`: `IListImplementationIsValid` (FlpIt is not a list; there is no read-only `IList` surface).
  - Target: 2 of 3 (67 %; the third is not applicable by design).
- **Optional cleanup**: ported tests that used `flp.it([])` where upstream wrote `Enumerable.Empty<int>()` (e.g. L02 `Empty`, L12 `TestData`) switch to `flp.empty(int)`.
- **Own unit tests** (`tests/unit/test_empty.py`): re-iterable 3 times; all terminal ops on it (`any`, `count`, `first_or_default`, `last_or_default`, `sum == 0`, `aggregate` raises `EmptySequenceError`); `concat` onto it; `take(0) is flp.empty()`; `flp.empty(None)` works.
- **Contracts** (auto, factory kind): re-iterable, returns `FlpIt`, no shared mutable state reachable through the public API.
- **Typing** (`tests/typing/test_types_empty.py`): `assert_type(flp.empty(int), FlpIt[int])`, `assert_type(flp.empty(), FlpIt[Any])`, `x: FlpIt[str] = flp.empty()` passes, `x: FlpIt[str] = flp.empty(int)` is an error.

## 5. Differential harness
`difftest/specs/empty.toml` (factory): compositions `empty().count()`, `empty().any()`, `empty().first_or_default()`, `empty().default_if_empty(7)`, `empty().concat([1])`, `empty().sequence_equal([])` (after L14); oracle element type `int?`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_empty.py`: `flp.empty().to_list()` vs `native` `list(())`, and `flp.empty().where(p).count()` vs `sum(1 for x in () if p(x))`. Constant-time op: the ratio is reported but not targeted; the PR records the absolute time per call (expected < 1 µs).

## 7. Docs
- Docstring: `.NET: Enumerable.Empty<T>()`; singleton; `item_type` is for type checkers only; typing tip for union item types.
- Doctests: `flp.empty(int).to_list()` gives `[]`; `flp.empty().count()` gives `0`; `flp.empty() is flp.empty(str)` gives `True`.
- README: factories section lists `flp.empty`. Translation map: `iter(())` / `Enumerable.Empty<T>()` → `flp.empty(T)`.

## 8. Expected outcomes
- `flp.empty` available and typed; `take(0)`/`take_last(0)` share the instance; 2 ported tests + own tests green.

## 9. Verification
VERIFY-std with `<op>=empty`, plus:
```bash
uv run pytest -q tests/nettests/test_empty.py tests/typing/test_types_empty.py -rs
uv run python -c "from flpit import flp; print(flp.empty(int).to_list(), flp.empty() is flp.empty(str), flp.it([1]).take(0) is flp.empty())"   # [] True True
```

## 10. Definition of Done
DoD-std, plus `flp.__all__` updated and the README factory list regenerated.

## 11. Risks / open questions
- If pyrefly infers the generic return type from the assignment context (`x: FlpIt[int] = empty()` with a single `def empty(item_type: type[T] | None = None) -> FlpIt[T]`), prefer that single generic signature over the `FlpIt[Any]` overload; decide in the typing test.
- Returning the singleton from `take(0)` is an identity-level change; harmless, but if any contract test asserts `take(...)` returns a *new* object, keep `take` returning `FlpIt(())`.
