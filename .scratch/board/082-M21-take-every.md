---
id: M21
title: take_every
status: todo
priority: 082
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: TakeEvery.cs @ morelinq master d217ab1 (reference only, D7; TakeEveryTest.cs 8 [Test]/[TestCase] read for behaviour)
pr:
---

# M21: `take_every`

## 1. Goal
Down-sampling ("every 10th reading", "odd positions") is `xs[::step]` for lists, but there is no fluent form for lazy pipelines, and `islice(xs, 0, None, step)` is rarely remembered. `take_every(step)` is a one-line streaming wrapper over `islice`, cheap to deliver and frequently asked for by .NET users moving to Python.

## 2. Scope
**In:** `take_every(step)` on `_LinqOps` (FlpIt, FlpList, OrderedIt, Grouping).
**Out:** a start offset (`xs[start::step]`): not in MoreLINQ; compose `skip(start).take_every(step)` (L01). Negative steps (reverse sampling): use `reverse()` (L11) first.

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `TakeEvery(int step)` | `take_every(step)` |

## 3. Detailed design
### 3.1 Signatures
```python
def take_every(self, step: int) -> FlpIt[TItem]: ...
```
### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: n/a.
- Yields the elements at positions `0, step, 2*step, ...` (the first element is always included when the source is non-empty).
- `step == 1` yields the whole source; `step >= len(source)` yields only the first element.
- Validation (eager, at call time, like MoreLINQ, whose method is not an iterator): `step = _require_index(step, "step")` (`None` → `ArgumentNoneError`, `1.5` → `TypeError`); `step <= 0` → `ArgumentOutOfRangeError("step")` with the .NET message `Specified argument was out of the range of valid values. (Parameter 'step')`.
- Pull pattern (identical to MoreLINQ's `Where((_, i) => i % step == 0)`): element `k*step` is yielded after exactly `k*step + 1` pulls; after the last match the source is drained to its end. So `take_every(3).take(2)` over an infinite source pulls 4 elements.
- None elements are ordinary values. Huge steps (`2**31 - 1`) are fine: `islice` skips without materialising.
- Re-enumeration re-enumerates the source; one-shot stays one-shot. Source exceptions propagate at enumeration, including from skipped positions.

### 3.3 Implementation sketch
```python
def take_every(self, step):
    step = _require_positive(_require_index(step, "step"), "step")   # F05 helpers
    src = self._source()
    if step == 1:
        return FlpIt(_FactoryIterable(lambda: iter(src)))           # still deferred, re-iterable
    return FlpIt(_FactoryIterable(lambda: islice(src, 0, None, step)))
```
- `islice` is C-level: O(n) time, O(1) memory.
- **FlpList fast path:** `iter(data[::step])` taken at enumeration time. It copies n/step references and changes nothing observable (operators never mutate the list; a list has no pull side effects). Adopt only if the benchmark shows ≥ 15 % gain at 1e5 with `step = 2`; record the measurement in the PR either way.

### 3.4 Registry entry
```toml
[operators.take_every]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.TakeEvery"
python_equivalent = "itertools.islice(xs, 0, None, step)  # xs[::step] for lists"
contract_args = "(2,)"
since = "0.4.0"   # adjust to the release that ships it
card = "M21"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design). The 8 MoreLINQ cases (zero/negative step, empty, step 1, typical, laziness) are a behaviour checklist; each has an own equivalent below. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_take_every.py`, both `flp_type`s):
  - `range(10)` with step 1, 2, 3, 10, 11; empty source; singleton.
  - `step` in `{0, -1}` → `ArgumentOutOfRangeError` at call time on a `NoIterList` source; `None` → `ArgumentNoneError`; `1.5` → `TypeError`; message names `step`.
  - Pull count on an instrumented infinite source (`itertools.count()` wrapped): `take_every(3).take(2)` pulls 4.
  - A source raising at a skipped position raises during enumeration.
  - None elements kept; `order_by(...).take_every(2)` samples the sorted order.
  - One-shot generator vs list re-enumeration.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated, eager validation.
- **Typing** (`tests/typing/test_types_take_every.py`): `assert_type(flp.lst([1]).take_every(2), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/take_every.toml`; oracle `difftest/oracle/Operators/TakeEvery.cs` calls `MoreEnumerable.TakeEvery(source, step)` statically.
- `step ∈ {-1, 0, 1, 2, 3, len-1, len, len+1, 2**31-1}`; items: empty, singleton, `range(0, 20)`, strings, ints with nulls; sources: `list`, `one_shot`, `counting`, `throwing_at(i)`.
- Terminals: `to_list`, `first`, `take(k)` then `to_list`.
- Probes: values, `trace` (pull pattern), exception type/message/timing (`at: "call"` for invalid steps).
- Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_take_every.py`, sizes 1e3 / 1e5, `step = 3`:
- `native`: `list(itertools.islice(data, 0, None, 3))` (for the FlpList variant the reviewer idiom `data[::3]` is reported as a second native row).
- `flpit-FlpIt`: `flp.it(data).take_every(3).to_list()`; `flpit-FlpList`: `flp.lst(data).take_every(3).to_list()`.
- Target ratio ≤ 1.5× vs `islice` (streaming default).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.TakeEvery(step)`; Args (`step >= 1`); Raises (`ArgumentNoneError`, `TypeError`, `ArgumentOutOfRangeError`, all immediate); `Execution: Deferred, streaming`; doctest:
  ```python
  >>> flp.it(range(10)).take_every(3).to_list()
  [0, 3, 6, 9]
  ```
- Translation map: MoreLINQ `.TakeEvery(n)` / Python `xs[::n]`, `islice(xs, 0, None, n)` → `.take_every(n)`.
- No semantic deviation.

## 8. Expected outcomes
- `take_every` on all four types, typed and documented, C-level speed.
- difftest spec 0 MISMATCH including the pull-pattern trace.

## 9. Verification
VERIFY-std with `<op>=take_every`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_take_every.py
uv run python -c "from flpit import flp; print(flp.it(range(10)).take_every(3).to_list())"   # [0, 3, 6, 9]
uv run python -c "from flpit import flp; flp.it([1]).take_every(0)"                        # ArgumentOutOfRangeError ... (Parameter 'step')
```

## 10. Definition of Done
DoD-std, plus the FlpList slicing measurement and decision recorded in the PR.

## 11. Risks / open questions
- None significant. If users ask for `xs[start::step]`, prefer documenting `skip(start).take_every(step)` over adding a parameter that MoreLINQ does not have.
