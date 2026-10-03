---
id: B02
title: concat
status: todo
priority: 053
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ConcatTests.cs @ dotnet/runtime main 6f1d9331 (15 [Fact]/[Theory] + 1 [ConditionalFact])
  morelinq: n/a
pr:
---

# B02: `concat` (backfill)

## 1. Goal
`concat` is advertised in the README but has no ported tests and three defects found by reading `linq.py` against `ConcatTests.cs`: (1) **`FlpList.concat` does not exist** (drift between the two classes); (2) `concat(None)` is accepted and only fails with a bare `TypeError` after the whole first sequence has been yielded, whereas .NET throws `ArgumentNullException("second")` at call time; (3) each call nests a generator, so ~1000 chained `concat` calls raise `RecursionError`, while .NET has four `OuterLoop` tests chaining 30 000 concats. This card fixes all three and ports the tests.

## 2. Scope
**In:** `concat(second)` on `_LinqOps` (fixes the FlpList gap even if F05 has not removed every delegate yet); chain flattening through `_ChainIterable` (introduced by B01, or here if B02 lands first); eager `second` validation; port of `ConcatTests.cs`.
**Out:** variadic `concat(*seconds)` (not a .NET overload; `.concat(a).concat(b)` is O(1) per call with the node); count overflow (Python ints).

## 3. Detailed design
### 3.1 Signatures
```python
def concat(self, second: Iterable[TItem]) -> FlpIt[TItem]: ...
```
.NET `Concat(first, second)` maps 1:1. `first` is `self`.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: `second` is not touched (`iter()` not called) until `self` is exhausted; `concat(x).first()` on a non-empty `self` never touches `second`.
- Validation (eager): `second is None` → `ArgumentNoneError("second")`. No eager `isinstance(second, Iterable)` check: objects iterable through `__getitem__` stay accepted; a non-iterable fails with Python's `TypeError` when reached (documented).
- `str` as `second` concatenates characters (consistent with `flp.it("abc")`).
- Re-enumeration: re-enumerates both parts; `q.concat(q)` is valid for re-iterable `q` (`ConcatWithSelfData`).
- Live sources: lists are read at enumeration time, so mutation between construction and enumeration is visible (same as .NET).
- `OrderedIt.concat(x)`: sorted `self`, then `x` unsorted; returns `FlpIt`.

### 3.3 Implementation sketch
```python
def concat(self, second):
    if second is None:
        raise ArgumentNoneError("second")
    src, head, tail = self._chain_parts()          # B01 helper; unwraps only when type(self) is FlpIt
    return FlpIt(_ChainIterable(src, head, _Node(second, tail)))
```
- `_ChainIterable.__iter__` walks the head/tail lists iteratively and returns `itertools.chain.from_iterable(parts)`: no recursion, so 30 000 links enumerate fine. O(1) per `concat` call, O(k) setup per enumeration, C-level per element.
- `append(x)` is `concat((x,))` on the same tail list, so mixed `append`/`concat` chains also stay flat (`AppendedPrependedConcatAlternationsData`). `prepend` adds to the head list. A `concat` whose *argument* is a chain is not merged (it is just an iterable part).
- **FlpList:** no override; the mixin wraps the live list.

### 3.4 Registry entry
```toml
[operators.concat]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Concat"
python_equivalent = "itertools.chain(xs, ys)"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_concat.py` from `ConcatTests.cs` (16 incl. the `[ConditionalFact]`):
  - Ported (13): `SameResultsWithQueryAndRepeatCalls_Int/_String`, `PossiblyEmptyInputs` (3 rows), `SecondNull` (→ `ArgumentNoneError`), `VerifyEquals` and `First_Last_ElementAt` over all `MemberData` generators (array → `tuple`, list → `list`, non-collection → `NonCollectionIterable`, select-array, concat-of-concats, concat-with-self, chained collections, appended/prepended alternations, concat with empty; `ElementAt(0)` on empty → `IndexError`, the flpit convention), `ManyConcats`, `ManyConcatsRunOnce`, `CollectionInterleavedWithLazyEnumerables_ToArray` (`ToArray` → `to_list`), and the four `*ResilientToStackOverflow` tests with 30 000 links (`Count()` → `count()`, `GetEnumerator/MoveNext` → `next(iter(q))`).
  - Adapted (1): `ForcedToEnumeratorDoesntEnumerate` → query is not an `Iterator`.
  - Skips: `OTHER` 1 (`FirstNull`: no extension methods on `None`); `NO_VALUE_TYPES` 1 (`CountOfConcatIteratorShouldThrowExceptionOnIntegerOverflow`, a `[ConditionalFact]`).
  - Target: 14/16 ≈ 87 % ported.
- **Own unit tests** (`tests/unit/test_concat.py`):
  - `flp.lst([1]).concat([2])` exists and returns `FlpIt` (regression for the missing method).
  - `concat(None)` raises at call time, before any enumeration (`NoIterList` source).
  - `second` is a one-shot generator: first enumeration complete, second yields only `self`.
  - `second.__iter__` is not called when the consumer stops inside `self` (spy iterable).
  - 30 000-link chain built with mixed `append`/`prepend`/`concat` equals the reference list.
- **Contracts** (auto) + `concat(spy).first()` touches `spy` 0 times.
- **Typing**: `assert_type(flp.it([1]).concat([2]), FlpIt[int])`; `flp.lst([1]).concat(...)` type-checks (it did not before).

## 5. Differential harness
`difftest/specs/concat.toml`: `first`, `second` ∈ {empty, singleton, ints with duplicates, nullable ints, strings}; probe programs: `a.concat(b)`, `a.concat(a)`, chains of 2–8 mixed `concat`/`append`/`prepend`; probes `elements_pulled` on `.first()` and `.take(k)` across the boundary. Expected: all MATCH (the `null` second case is checked by unit tests only, the harness never passes `None` as a sequence).

## 6. Benchmarks
`tests/benchmarks/test_bench_concat.py`, sizes 1e3 and 1e5 (two halves):
- `native`: `list(itertools.chain(a, b))`; `flpit-FlpIt`: `flp.it(a).concat(b).to_list()`; `flpit-FlpList`: `flp.lst(a).concat(b).to_list()`.
- Many-parts case: 1 000 parts of 100; native `list(chain.from_iterable(parts))`, flpit = folded `.concat` chain.
- Target ≤ 1.5× (the node is `chain.from_iterable`; remaining cost is `to_list`, B09).

## 7. Docs
- Docstring: `.NET: Enumerable.Concat(first, second)`; deferred; `second` touched only after `self` is exhausted; `Raises: ArgumentNoneError` if `second is None`. Doctest: `flp.it([1, 2]).concat([3, 4]).to_list()` → `[1, 2, 3, 4]`.
- README: the existing "Independent Query Pipelines" `concat` example now runs on `FlpList` too.
- Translation map: `.Concat(ys)` / `itertools.chain(xs, ys)` / `[*xs, *ys]` → `.concat(ys)`.

## 8. Expected outcomes
- `FlpList.concat` exists; `concat(None)` fails fast with the .NET parameter name.
- Concat chains of any depth enumerate; ~14 ported .NET tests green including the 30 000-link stack tests.
- Benchmark recorded; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=concat`, plus:
```bash
uv run pytest -q tests/nettests/test_concat.py -rs
uv run python -c "from flpit import flp; print(flp.lst([1, 2]).concat([3]).to_list())"     # [1, 2, 3]
uv run python -c "from flpit import flp; flp.it([1]).concat(None)"   # ArgumentNoneError: ... 'second'
```

## 10. Definition of Done
DoD-std, plus: the four 30 000-link tests run in the default suite (not deselected), and the PR states whether `_ChainIterable` was introduced here or by B01.

## 11. Risks / open questions
- Ordering with B01: whichever lands first introduces `_ChainIterable`; the second card only adds its method and tests.
- The 30 000-link tests are `OuterLoop` in .NET; in Python they take milliseconds with the flat node. If CI time grows, mark them `slow` rather than skipping.
