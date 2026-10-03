---
id: N12
title: flp.sequence / flp.infinite_sequence
status: todo
priority: 056
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: SequenceTests.cs (7 [Fact]/[Theory]) + InfiniteSequenceTests.cs (4 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331
  morelinq: Sequence.cs (reference only, D7; superseded by the .NET 10 factory)
pr:
---

# N12: `flp.sequence` / `flp.infinite_sequence`

## 1. Goal
.NET 10 adds two generic number generators: `Sequence(start, endInclusive, step)` (finite, inclusive end, any numeric type, negative steps) and `InfiniteSequence(start, step)`. `flp.range(start, count)` only covers "count ints from start"; Python's `range` is exclusive and int-only, and float stepping needs a hand-written loop. These factories close Phase 2 and give users an `arange`-like generator with exactly .NET's termination rules, re-iterable and composable.

## 2. Scope
**In:** `flp.sequence(start, end_inclusive, step)` and `flp.infinite_sequence(start, step)` in `src/flpit/flp.py` (added to `__all__`); int fast path on `range`; count provider for the int path (N10).
**Out:** a default `step` (.NET requires it; `flp.range` covers the step-1 int case); `numpy`-style "num points" spacing (`linspace`); renaming/changing `flp.range` (B07).

## 3. Detailed design
### 3.1 Signatures
```python
def sequence[T: (int, float, Decimal, Fraction)](start: T, end_inclusive: T, step: T) -> FlpIt[T]: ...

class _SupportsSelfAdd(Protocol):
    def __add__(self, other: Self, /) -> Self: ...

def infinite_sequence[T: _SupportsSelfAdd](start: T, step: T) -> FlpIt[T]: ...
```
| .NET | flpit |
|---|---|
| `Enumerable.Sequence<T>(start, endInclusive, step) where T : INumber<T>` | `flp.sequence(start, end_inclusive, step)` |
| `Enumerable.InfiniteSequence<T>(start, step) where T : IAdditionOperators<T,T,T>` | `flp.infinite_sequence(start, step)` |

### 3.2 Semantics
**`sequence`** (mirrors `Sequence.cs`):
- Kind: factory, deferred (validation eager, values lazy). Buffering: streaming. Re-iterable: every enumeration starts again at `start`.
- Validation (eager, .NET order): `start` `None` → `ArgumentNoneError("start")`, NaN → `ArgumentOutOfRangeError("start")`; same for `end_inclusive`, then `step`. `start + step` is evaluated once at call time so incompatible types (`Decimal` + `float`) raise `TypeError` at call, not mid-iteration.
- `step == 0`: if `start == end_inclusive` yields `[start]` once, else `ArgumentOutOfRangeError("step")` (would be infinite).
- `step > 0` requires `end_inclusive >= start`, `step < 0` requires `end_inclusive <= start`, else `ArgumentOutOfRangeError("end_inclusive")`. `start == end_inclusive` yields `[start]` for any step.
- Values are produced by **repeated addition** (`current += step`, like .NET, not `start + i*step`), so float results are bit-identical to .NET `double`. `end_inclusive` is yielded only if hit exactly.
- **Saturation guard** (float): iteration stops when `current + step` no longer moves past `current` (e.g. `sequence(2.0**53, 1e308, 1.0)` yields one element), mirroring .NET's `next <= current` check. `inf` bounds are allowed (not NaN); such a sequence ends only at saturation, as in .NET.
- `bool` arguments are treated as ints (yield ints).
- Deviation (README "no fixed-width integer overflow", shared with N01/N02): Python ints never overflow, so the .NET overflow guard only matters for floats.

**`infinite_sequence`**:
- Kind: factory, deferred, never terminates; compose with `take`, `take_while`, `zip`.
- Validation (eager): `start` / `step` `None` → `ArgumentNoneError`. No NaN or sign checks (same as .NET); `step == 0` repeats `start` forever.
- Values: `start, start + step, start + step + step, ...` (repeated addition). Works for any type whose `+` returns the same type (`str`, `timedelta`, `Fraction`...), like .NET's `IAdditionOperators` constraint.
- Re-iterable; `try_get_non_enumerated_count()` is `None`.

### 3.3 Implementation sketch
```python
def sequence(start, end_inclusive, step):
    _validate_number(start, "start"); _validate_number(end_inclusive, "end_inclusive"); _validate_number(step, "step")
    start + step                                                  # type probe, eager TypeError
    if step == 0:
        if start != end_inclusive:
            raise ArgumentOutOfRangeError("step")
        return FlpIt((start,))
    if (step > 0 and end_inclusive < start) or (step < 0 and end_inclusive > start):
        raise ArgumentOutOfRangeError("end_inclusive")
    if isinstance(start, int) and isinstance(end_inclusive, int) and isinstance(step, int):
        s, e, st = int(start), int(end_inclusive), int(step)
        return FlpIt(builtins.range(s, e + 1 if st > 0 else e - 1, st))    # C-level, Sized, re-iterable
    gen = _incrementing if step > 0 else _decrementing
    return FlpIt(_FactoryIterable(lambda: gen(start, end_inclusive, step)))

def _incrementing(cur, end, step):
    yield cur
    while True:
        nxt = cur + step
        if nxt >= end or nxt <= cur:                 # end reached, or saturation
            if nxt == end and cur != nxt:
                yield nxt
            return
        yield nxt
        cur = nxt
# _decrementing: mirror with <= end / >= cur

def infinite_sequence(start, step):
    _require_not_none(start, "start"); _require_not_none(step, "step")
    if isinstance(start, Number) and isinstance(step, Number):
        return FlpIt(_FactoryIterable(lambda: itertools.count(start, step)))   # C, repeated addition
    def _gen():
        cur = start
        while True:
            yield cur
            cur = cur + step
    return FlpIt(_FactoryIterable(_gen))
```
- `_validate_number`: `None` check, then NaN check (`x != x` for float/Decimal/Fraction; signalling `Decimal('sNaN')` comparisons raise `InvalidOperation`, so use `Decimal.is_nan()` for Decimals).
- `range(s, e+1, st)` yields exactly the values `<= e` (or `>= e` for negative steps) that repeated addition would, so the int path is observationally identical and gives `len()` for N10.
- `itertools.count` with non-int numbers uses repeated addition (checked: ten steps of `0.1` give `0.9999999999999999`, same as a `+=` loop).
- Complexity: O(1) per element, O(1) memory.

### 3.4 Registry entry
```toml
[operators.sequence]
category = "generation"
kind = "factory"
buffering = "streaming"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.Sequence"
python_equivalent = "range(start, end + 1, step) (ints) / while-loop with += (floats)"
classes = ["flp"]
since = "0.4.0"
card = "N12"
notes = "Inclusive end; step sign validated; repeated addition with float saturation guard."

[operators.infinite_sequence]
category = "generation"
kind = "factory"
buffering = "streaming"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.InfiniteSequence"
python_equivalent = "itertools.count(start, step)"
classes = ["flp"]
since = "0.4.0"
card = "N12"
notes = "Never ends; any self-addable type."
```

## 4. Tests
- **Ported** `tests/nettests/test_sequence.py` (`SequenceTests.cs`, 7) and `tests/nettests/test_infinite_sequence.py` (`InfiniteSequenceTests.cs`, 4). .NET iterates over 17 numeric types; Python runs each check over `int`, `float`, `Decimal`, `Fraction` (`NO_VALUE_TYPES` adaptation, not a skip):
  - `InvalidArguments_Throws`: `None` arguments → `ArgumentNoneError` with param names; `float("nan")` → `ArgumentOutOfRangeError`.
  - `EndOutOfRange_Throws`: sign/direction rules and the `start == end` with steps 0, 1, 2 cases.
  - `Step1_MatchesRange`, `Numbers_ProduceExpectedSequence`, `MultipleGetEnumeratorCalls_ReturnsUniqueInstances`: ported; rows using `T.MaxValue`/`T.MinValue` run for `float` (`sys.float_info.max`) and are dropped for unbounded types (`NO_VALUE_TYPES` comment).
  - `FloatingPoints_ProduceExpectedSequence`: the `0.123f` cases ported with `pytest.approx(abs=1e-3)`; the float32 saturation cases (`16_777_216f`) adapted to their double analogue (`2.0**53`).
  - `SmallIntegers_ProducesFullRange`: ported as int ranges (0..255, -128..127, 0..65535, -32768..32767).
  - InfiniteSequence: all 4 ported; wrap-around expectations are computed in the test with Python `+`, so they hold without overflow.
  - Target: 11/11 test functions ported (100 %), some data rows adapted or dropped.
- **Own unit tests** (`tests/unit/test_sequence.py`): int path returns a `range`-backed query (`try_get_non_enumerated_count()` known) and equals the generic path on the same ints; `step == 0` rules; eager `TypeError` for `Decimal` + `float`; `bool` arguments yield ints; `infinite_sequence` over `str` and `timedelta`; re-iteration starts over; `infinite_sequence(...).take(n)` and `.zip(...)` compositions; nothing computed before enumeration (generic path).
- **Contracts**: registry `kind = "factory"` checks (re-iterable, deferred values).
- **Typing**: `assert_type(flp.sequence(0, 10, 2), FlpIt[int])`; `assert_type(flp.sequence(0.0, 1.0, 0.1), FlpIt[float])`; `assert_type(flp.infinite_sequence(Decimal(1), Decimal(1)), FlpIt[Decimal])`.

## 5. Differential harness
`difftest/specs/sequence.toml` and `infinite_sequence.toml` (both in .NET 10 GA): int and double domains for `start, end, step ∈ {-5, -1, 0, 1, 3, 0.1, 0.25}`, including invalid direction and zero step; `infinite_sequence` probed through `Take(20)`. Probes: values (doubles compared bit-exactly, since both sides use repeated addition), exception type and param name at call time. Expected: all MATCH; int domains near `int.MaxValue` are excluded (overflow deviation).

## 6. Benchmarks
`tests/benchmarks/test_bench_sequence.py`, sizes 1e3 and 1e5 elements:
- int: native `list(range(0, 3 * n, 3))` vs `flp.sequence(0, 3 * n - 1, 3).to_list()`; target ≤ 1.3×.
- float: native `x = 0.0; out = []; while x <= end: out.append(x); x += 0.5` vs `flp.sequence(0.0, end, 0.5).to_list()`; target ≤ 1.5×.
- infinite: native `list(islice(count(0, 2), n))` vs `flp.infinite_sequence(0, 2).take(n).to_list()`; target ≤ 1.3×.

## 7. Docs
- Docstrings (both in `flp.py`): summary; `.NET: Enumerable.Sequence` / `Enumerable.InfiniteSequence`; Args (`end_inclusive` is inclusive), Raises, Execution (validation eager, values lazy, re-iterable; float saturation). Examples:
  ```python
  >>> flp.sequence(0, 10, 3).to_list()
  [0, 3, 6, 9]
  >>> flp.sequence(1, -4, -2).to_list()
  [1, -1, -3]
  >>> flp.sequence(0.0, 1.0, 0.25).to_list()
  [0.0, 0.25, 0.5, 0.75, 1.0]
  >>> flp.infinite_sequence(10, -3).take(4).to_list()
  [10, 7, 4, 1]
  ```
- README matrix rows (factories section next to `flp.range`, with a one-line "inclusive end vs `range(start, count)`" note); shared deviation entry.
- Translation map: `Enumerable.Sequence(a, b, s)` / `range(a, b + 1, s)` → `flp.sequence(a, b, s)`; `Enumerable.InfiniteSequence(a, s)` / `itertools.count(a, s)` → `flp.infinite_sequence(a, s)`.

## 8. Expected outcomes
- Two new factories with .NET 10 semantics, re-iterable, fully typed; int sequences run at `range` speed and know their count.
- 11 ported .NET test functions green; benchmarks recorded; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=sequence` and again with `<op>=infinite_sequence`, plus:
```bash
uv run pytest -q tests/nettests/test_sequence.py tests/nettests/test_infinite_sequence.py -rs
uv run python -c "from flpit import flp; print(flp.sequence(0.0, 1.0, 0.25).to_list())"   # [0.0, 0.25, 0.5, 0.75, 1.0]
uv run python -c "from flpit import flp; flp.sequence(1, 5, -1)"                          # ArgumentOutOfRangeError('end_inclusive')
```

## 10. Definition of Done
DoD-std (for both factories), plus `flp.__all__` updated and both appear in the README factories list.

## 11. Risks / open questions
- Constrained TypeVar `(int, float, Decimal, Fraction)` may reject numeric types users expect (numpy scalars); widen to a `SupportsAdd + SupportsRichComparison` protocol if requested. Runtime accepts any comparable, addable type already.
- `itertools.count` fast path for `infinite_sequence` relies on CPython's repeated-addition behaviour for non-int steps; a unit test pins it.
