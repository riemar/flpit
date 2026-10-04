---
id: M15
title: equi_zip
status: todo
priority: 076
effort: S
depends_on: [F05, F06, F07, F08, F09, M14]
upstream:
  dotnet: n/a (Enumerable.Zip silently stops at the shortest)
  morelinq: EquiZip.cs, ZipImpl.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; EquiZipTest.cs has 8 [Test]/[TestCase])
pr:
---

# M15: `equi_zip`

## 1. Goal
`equi_zip` zips sequences that **must** have the same length and raises when they do not: parallel columns, keys and values read from two files, expected vs actual lists. Silent truncation by `zip` hides data bugs; Python fixed this with `zip(strict=True)` (3.10), and this card exposes the same guarantee fluently with a dedicated, catchable error.

## 2. Scope
**In:** `equi_zip(*others, result_selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`); new exception `SequenceLengthMismatchError(ValueError)` exported from `flpit`.
**Out:** a `strict=` flag on the existing `zip` (possible later in N08; this card keeps the MoreLINQ name).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `EquiZip(second, Func<T1, T2, TResult>)` | `equi_zip(second, result_selector=f)` |
| `EquiZip(second, third, Func<...>)` | `equi_zip(second, third, result_selector=f)` |
| `EquiZip(second, third, fourth, Func<...>)` | `equi_zip(second, third, fourth, result_selector=f)` |
| (none) | no selector → tuples; more than 3 others → `tuple[Any, ...]` |

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def equi_zip(self, second: Iterable[T2], /) -> FlpIt[tuple[TItem, T2]]: ...
@overload
def equi_zip(self, second: Iterable[T2], /, *, result_selector: Callable[[TItem, T2], TResult]) -> FlpIt[TResult]: ...
@overload
def equi_zip(self, second: Iterable[T2], third: Iterable[T3], /) -> FlpIt[tuple[TItem, T2, T3]]: ...
@overload
def equi_zip(self, second: Iterable[T2], third: Iterable[T3], /, *,
             result_selector: Callable[[TItem, T2, T3], TResult]) -> FlpIt[TResult]: ...
# (second, third, fourth): same two shapes
@overload
def equi_zip(self, *others: Iterable[Any], result_selector: Callable[..., TResult]) -> FlpIt[TResult]: ...
@overload
def equi_zip(self, *others: Iterable[Any]) -> FlpIt[tuple[Any, ...]]: ...

class SequenceLengthMismatchError(ValueError):
    """Raised by equi_zip when the sequences have different lengths."""
    index: int                      # 0-based position of the sequence reported as too short
    def __init__(self, index: int) -> None:
        super().__init__(f"{_ordinal(index)} sequence too short.")   # "First sequence too short."
```
`_ordinal` gives `First..Fourth` (MoreLINQ wording) and `Sequence #<n>` beyond that.

### 3.2 Semantics (mirrors `ZipImpl` with the EquiZip error rule)
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: n/a (it raises at the first round that detects a length difference).
- All equal-length rows are yielded before the error; the error is raised when the mismatch is **discovered**, never ahead of time.
- **Pull pattern per round** (identical in MoreLINQ and CPython `zip(strict=True)`): `next` is called on sequences in order. If sequence k > 0 is exhausted while 0..k-1 produced an element → error immediately (later sequences are not advanced). If sequence 0 is exhausted, the others are probed in order and the error is raised at the first one that still produces an element; if none do, iteration ends normally.
- **Which sequence is named:** the first exhausted one. Sequence k (k > 0) ended early → `index = k` ("Second sequence too short."); sequence 0 ended while a later one continued → `index = 0` ("First sequence too short.").
- Validation (eager): at least one other (`TypeError`), `None` in `others` → `ArgumentNoneError("others")`, `result_selector=None` → `ArgumentNoneError("result_selector")` (helpers shared with M14).
- Exception type: `SequenceLengthMismatchError` is a `ValueError` (Python's `zip(strict=True)` raises `ValueError`; flpit maps .NET `InvalidOperationException` cases to `ValueError` subclasses, e.g. `EmptySequenceError`). Code catching `ValueError` from `zip(strict=True)` keeps working.
- Re-enumeration re-iterates all sequences; exceptions from sources and the selector propagate unchanged.

### 3.3 Implementation sketch
```python
_STRICT_MSG = re.compile(r"zip\(\) argument (\d+) is (shorter|longer) than argument")

def _generator():
    rows = zip(src, *others, strict=True)
    if result_selector is not _SENTINEL:
        rows = starmap(result_selector, rows)
    try:
        yield from rows
    except ValueError as exc:
        m = _STRICT_MSG.match(str(exc)) if type(exc) is ValueError else None
        if m is None:
            raise                                         # a source/selector ValueError, untouched
        index = int(m.group(1)) - 1 if m.group(2) == "shorter" else 0
        raise SequenceLengthMismatchError(index) from None
```
- C-level `zip(strict=True)`; the mapping runs once, on failure. "argument N is shorter" → sequence N-1 ended early; "is longer than argument(s) 1[-k]" → sequence 0 ended first. O(total) time, O(k) memory.
- A source raising a plain `ValueError` whose text happens to match the CPython message would be remapped; acceptable (documented risk). A unit test pins the CPython messages on 3.12 to 3.14 so a wording change fails CI loudly.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.equi_zip]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.EquiZip"
python_equivalent = "zip(a, b, strict=True)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `EquiZipTest.cs` (8 cases) as checklist:
  - covered: equal lengths, first shorter, first longer, laziness, "MoveNext is not called unnecessarily" (3 sequences, the third throws if advanced past the mismatch round).
  - `OTHER` (no `IDisposable`): both "sequences disposed with unequal lengths" cases and "disposes inner sequences when GetEnumerator throws".
  - Target: 100 % of applicable behaviours.
- **Own unit tests** (`tests/unit/morelinq/test_equi_zip.py`, both `flp_type`s):
  - Equal lengths (2, 3, 5 sequences); both empty.
  - Mismatch matrix: `([1,2],"abc")` → index 0 "First sequence too short."; `([1,2,3],"ab")` → index 1; `([1,2],[1,2],[1,2,3])` → index 0; `([1,2,3],[1,2],[1,2,3])` → index 1; `([1,2,3],[1,2,3],[1,2])` → index 2 "Third ...".
  - All matched rows are yielded before the error (`take` on the matching prefix never raises).
  - Pull trace equals §3.2 (third sequence never advanced in the `([1,2],[1,2,3],<throws on 3rd>)` case).
  - `SequenceLengthMismatchError` is a `ValueError`, has `.index`; a `ValueError` raised by a source or selector propagates unchanged (not remapped).
  - Pinned CPython strict-zip messages (guard test).
  - Validation errors at call time.
- **Contracts:** auto via registry.
- **Typing:** `assert_type(flp.it([1]).equi_zip(["a"]), FlpIt[tuple[int, str]])`, 3/4-arity, selector, fallback.

## 5. Differential harness
`difftest/specs/equi_zip.toml`, oracle calls the 2/3/4-sequence `MoreEnumerable.EquiZip` overloads with a tuple selector (pinned `morelinq` NuGet). Domains: per-sequence lengths from {0, 1, 2, 3}, int/string sources, one source with `throws_on(k)`. Probes: values yielded before the error, exception (`InvalidOperationException` + message ↔ `SequenceLengthMismatchError` + message; classifier mapping added to F09's table), `move_next` trace. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_equi_zip.py`, sizes 1e3 / 1e5, equal lengths:
- `native`: `list(zip(a, b, strict=True))`.
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(a).equi_zip(b).to_list()`.
- Target ratio ≤ 1.5× (expected ≈ 1.1×: one extra generator frame).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.EquiZip(...)`; Args; Raises (`SequenceLengthMismatchError` with message format and `.index`); `Execution:` deferred, streaming, raises on discovery.
- Doctest:
  ```python
  >>> flp.it([1, 2, 3]).equi_zip("abc").to_list()
  [(1, 'a'), (2, 'b'), (3, 'c')]
  >>> flp.it([1, 2, 3]).equi_zip("ab").to_list()
  Traceback (most recent call last):
  ...
  flpit.core.errors.SequenceLengthMismatchError: Second sequence too short.
  ```
- Translation map: `.EquiZip(b, f)` / `zip(a, b, strict=True)` → `.equi_zip(b, result_selector=f)`.
- Deviations (README): `ValueError` subclass instead of `InvalidOperationException`; more than four sequences allowed.

## 8. Expected outcomes
- `equi_zip` on all four types; new public exception exported from `flpit`; ~14 own tests; difftest 0 MISMATCH; benchmark ≈ native.

## 9. Verification
VERIFY-std with `<op>=equi_zip`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_equi_zip.py
uv run python -c "from flpit import flp, SequenceLengthMismatchError as E
try: flp.it([1,2]).equi_zip('abc').to_list()
except E as e: print(e.index, e)"                                    # 0 First sequence too short.
```

## 10. Definition of Done
DoD-std, plus `SequenceLengthMismatchError` in `flpit.__all__`, in the errors module and in the F09 exception-mapping table.

## 11. Risks / open questions
- Parsing CPython's message is the price for C-speed `zip(strict=True)`. Fallback if a future CPython changes the wording: the guard test fails, and the pure-Python round loop (≈2× slower) replaces the mapping. Alternative considered: always the Python loop; rejected for speed.
- Doctest exception path depends on the F05 module layout (`flpit.core.errors`); adjust if F05 lands differently.
