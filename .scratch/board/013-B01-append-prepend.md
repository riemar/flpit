---
id: B01
title: append / prepend
status: todo
priority: 013
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: AppendPrependTests.cs @ dotnet/runtime main 6f1d9331 (28 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# B01: `append` / `prepend` (backfill)

## 1. Goal
`append`/`prepend` exist but have no ported .NET tests, and reading `linq.py` against `AppendPrependTests.cs` shows a real defect: every call nests one more generator (`yield from self`), so a chain of ~1000 `append`/`prepend` calls raises `RecursionError` on enumeration (measured on 3.12: 900 ok, 1000 fails). .NET represents chains as linked lists (`AppendPrependN`) precisely to avoid this. This card ports the tests, flattens chains, and lands the shared `_ChainIterable` node that B02 (`concat`) reuses.

## 2. Scope
**In:** `append(element)`, `prepend(element)` on `_LinqOps` (so `FlpIt`, `FlpList`, `OrderedIt`, `Grouping`); new private `_ChainIterable` + `_Node` (persistent singly linked list) in `linq.py`; port of `AppendPrependTests.cs`; docstrings, registry, typing, benchmark, difftest spec.
**Out:** `concat` (B02, reuses the node); `Count()` overflow semantics (Python ints do not overflow); a mutating `FlpList.append` (that is `add`, `List<T>.Add`).

## 3. Detailed design
### 3.1 Signatures
```python
def append(self, element: TItem) -> FlpIt[TItem]: ...
def prepend(self, element: TItem) -> FlpIt[TItem]: ...
```
.NET overloads: `Append(source, element)`, `Prepend(source, element)`: both mapped 1:1. No comparer/indexed variants exist.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: `prepend(x).first()` pulls 0 source elements; `append` yields `element` only after the source is exhausted.
- Validation: none beyond F05 source checks. `element` may be `None` (it is a value, not an argument to validate).
- Re-enumeration: each enumeration re-enumerates the source (re-iterable stays re-iterable, one-shot stays one-shot).
- Live sources: `flp.it(lst).prepend(4)` built before `lst.append(42)` yields `[4, 42]` (`PrependNoIteratingSourceBeforeFirstItem`). `FlpList.append(x)` wraps the live list, so mutation through `add` before enumeration is visible, the same as .NET deferred execution over `List<T>`.
- Branching: `q = src.append(3); a = q.append(5); b = q.append(6)` must keep `a` and `b` independent (`AppendCombinations`). The linked list is persistent (nodes are never mutated), so sharing a tail is safe.
- `OrderedIt.append(x)`: `x` is appended after sorting (it is not part of the ordering). Result type is `FlpIt`, as .NET returns `IEnumerable<T>`.
- Python name clash: `FlpList.append` is LINQ `Append` (non-mutating, returns a query), not `list.append`. Already true today; documented in README "Intentional Semantic Deviations" (use `add` to mutate).

### 3.3 Implementation sketch
```python
class _Node(NamedTuple):            # persistent cons cell
    value: Iterable[Any]
    next: "_Node | None"

class _ChainIterable(Iterable[T]):
    __slots__ = ("_source", "_head", "_tail")   # _head: prepended (latest first), _tail: appended (latest first)
    def __iter__(self) -> Iterator[T]:
        parts: list[Iterable[T]] = []
        node = self._head
        while node is not None:           # iterative walk, no recursion
            parts.append(node.value); node = node.next
        parts.append(self._source)
        tail = []
        node = self._tail
        while node is not None:
            tail.append(node.value); node = node.next
        parts.extend(reversed(tail))
        return chain.from_iterable(parts)

def append(self, element):
    src, head, tail = self._chain_parts()          # unwraps an existing _ChainIterable only when type(self) is FlpIt
    return FlpIt(_ChainIterable(src, head, _Node((element,), tail)))
```
- `_chain_parts()` returns `(self._iterable.source, head, tail)` when `type(self) is FlpIt and isinstance(self._iterable, _ChainIterable)`, else `(self._source(), None, None)`. The `type(self) is FlpIt` guard is essential: `OrderedIt._iterable` is the *unsorted* input and must never be unwrapped.
- Cost: O(1) per call; O(k) setup per enumeration for k chained calls; per element the C-level `chain.from_iterable`. Memory O(k). No recursion at any depth.
- **FlpList fast path:** none needed; the mixin default wraps the live list. Decision recorded, no override.

### 3.4 Registry entry
```toml
[operators.append]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Append"
python_equivalent = "itertools.chain(xs, (x,))"
since = "0.2.0"          # pre-registry operator

[operators.prepend]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.Prepend"
python_equivalent = "itertools.chain((x,), xs)"
since = "0.2.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_append_prepend.py` from `AppendPrependTests.cs` (28):
  - Ported directly (18): `SameResultsRepeatCalls*` (4, use `concat`), `RepeatIteration`, `EmptyAppend`/`EmptyPrepend` (`CreateSources` → list, tuple, `NonCollectionIterable`, generator factory), `PrependNoIteratingSourceBeforeFirstItem`, `Combined` (strings), `AppendCombinations`, `PrependCombinations`, `Append1/Prepend1/AppendN/PrependN/AppendPrependToArrayToList` (5, `ToArray` → `tuple(...)`), `AppendPrependRunOnce` (`run_once` fixture), `AppendPrepend_First_Last_ElementAt`.
  - Adapted (3): `ForcedToEnumeratorDoesnt*` → assert the query is not an `Iterator` (`not isinstance(q, collections.abc.Iterator)`), the Python analogue of "cannot be forced to an enumerator".
  - Skips: `OTHER` 1 (`SourceNull`: no extension methods on `None`); `NO_VALUE_TYPES` 6 (`*OverflowCount*`: Python `int` does not overflow; also `LONG_RUNNING` on 2**31 elements).
  - Target: 21/28 = 75 % ported, not skipped.
- **Own unit tests** (`tests/unit/test_append_prepend.py`):
  - 10 000 chained `append` and 10 000 chained `prepend` enumerate without `RecursionError`; result equals `[*reversed(pre), *src, *app]`.
  - Mixed chain `prepend(1).append(4).prepend(0).append(5)` on a one-shot generator: correct once, empty on second enumeration.
  - `order_by(k).append(x)`: `x` last even if it sorts first; `append` after `OrderedIt` is not unwrapped.
  - `append(None)`, `prepend(None)` yield `None`.
  - `flp.lst(data).append(9)` leaves the `FlpList` unchanged; `add` before enumeration is visible.
- **Contracts** (auto): deferral, one-shot, no FlpList mutation. Specific: `prepend(x).first()` pulls 0 elements; `append(x).first()` pulls 1.
- **Typing** `tests/typing/test_types_append_prepend.py`: `assert_type(flp.lst([1]).append(2), FlpIt[int])`; `OrderedIt[int].prepend(0)` is `FlpIt[int]`.

## 5. Differential harness
`difftest/specs/append_prepend.toml`: sources {empty, singleton, ints with duplicates, nullable ints with `None`, strings}; programs = random sequences of 1–6 `append`/`prepend` calls with values in {-1, 0, 42, None}; a branching probe (two children from one shared parent); probe `elements_pulled` for `.prepend(x).first()` (0) and `.append(x).first()` (1). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_append_prepend.py`, sizes 1e3 and 1e5:
- `native`: `list(itertools.chain(data, (x,)))`; `flpit-FlpIt`: `flp.it(data).append(x).to_list()`; `flpit-FlpList`: `flp.lst(data).append(x).to_list()`.
- Chain case: 100 appends; native `list(chain(data, extras))`.
- Target ≤ 1.5×. Today ≈ 4.9× (2.68 ms vs 0.55 ms at 1e5) because of the generator layer; the `chain`-based node removes it, the rest is `to_list` (see B09).

## 7. Docs
- Docstrings: `.NET: Enumerable.Append(source, element)` / `Prepend`; deferred, streaming; note that `FlpList.append` does not mutate (use `add`). Doctest: `flp.it([1, 2]).append(3).prepend(0).to_list()` → `[0, 1, 2, 3]`.
- README deviation entry: "`FlpList.append` / `prepend` are LINQ operators, not `list.append`".
- Translation map: `.Append(x)` / `itertools.chain(xs, (x,))` / `[*xs, x]` → `.append(x)`; `.Prepend(x)` / `chain((x,), xs)` → `.prepend(x)`.

## 8. Expected outcomes
- ~21 ported .NET tests green; chains of any length enumerate (no recursion limit).
- `_ChainIterable` available for B02.
- Benchmark ratio ≤ 1.5× recorded; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=append_prepend`, plus:
```bash
uv run pytest -q tests/nettests/test_append_prepend.py -rs
uv run python -c "from flpit import flp; q=flp.it([0])
for i in range(10_000): q=q.append(i)
print(q.count())"                                                       # 10001
uv run python -c "from flpit import flp; print(flp.it([1, 2]).append(3).prepend(0).to_list())"   # [0, 1, 2, 3]
```

## 10. Definition of Done
DoD-std, plus: the deep-chain regression test exists; the `type(self) is FlpIt` unwrap guard has a test with `OrderedIt`; README deviation entry added.

## 11. Risks / open questions
- B02 needs the same node. If B02 lands first it introduces `_ChainIterable`; this card then only adds `append`/`prepend` on top (same pattern as L15/L16).
- Users may expect `FlpList.append` to mutate (Python reflex). Out of scope to change; the docstring and README call it out.
