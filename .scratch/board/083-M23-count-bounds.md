---
id: M23
title: at_least / at_most / exactly / count_between
status: todo
priority: 083
effort: S
depends_on: [F05, F06, F07, F08, F09, N10]
upstream:
  dotnet: n/a (related: CountTests.cs, already ported; N10 TryGetNonEnumeratedCount)
  morelinq: CountMethods.cs (+ CountUpTo in MoreEnumerable.cs) @ morelinq master d217ab1 (reference only, D7; AtLeastTest.cs 4 + AtMostTest.cs 4 + ExactlyTest.cs 4 + CountBetweenTest.cs 6 [Test]/[TestCase] read for behaviour)
pr:
---

# M23: `at_least` / `at_most` / `exactly` / `count_between`

## 1. Goal
`query.count() >= 3` enumerates the entire (possibly huge or infinite) source just to answer a bounded question. The four MoreLINQ quantity tests stop pulling **as soon as the answer is known**: `at_least(3)` reads at most 3 elements, `at_most(3)` / `exactly(3)` at most 4. This is the kind of execution-semantics guarantee flpit's contract tests and difftest traces were built to verify, which makes the card a good showcase despite its size.

## 2. Scope
**In:** `at_least(count)`, `at_most(count)`, `exactly(count)`, `count_between(min_count, max_count)` on `_LinqOps`, plus one private helper `_count_up_to(limit)`. Known-count fast path via N10.
**Out:** predicate overloads (MoreLINQ has none; write `where(p).at_least(n)`); `CompareCount` (not in the D16 curated list; can follow as its own card).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `AtLeast(int count)` | `at_least(count)` |
| `AtMost(int count)` | `at_most(count)` |
| `Exactly(int count)` | `exactly(count)` |
| `CountBetween(int min, int max)` | `count_between(min_count, max_count)` (renamed: `min`/`max` would shadow builtins and trip ruff `A002`) |

## 3. Detailed design
### 3.1 Signatures
```python
def at_least(self, count: int) -> bool: ...
def at_most(self, count: int) -> bool: ...
def exactly(self, count: int) -> bool: ...
def count_between(self, min_count: int, max_count: int) -> bool: ...
```
### 3.2 Semantics
- Kind: terminal. Buffering: none (counts only). Short-circuit: yes, with these **exact pull bounds** (MoreLINQ `CountUpTo(limit)` semantics, `while count < limit && MoveNext()`):

  | Call | Source elements pulled (non-collection source) | True when |
  |---|---|---|
  | `at_least(n)` | `min(n, len)`, plus the end probe when `len < n` (`at_least(0)` pulls nothing) | `len >= n` |
  | `at_most(n)` | `min(n + 1, len)`, plus the end probe when `len <= n` | `len <= n` |
  | `exactly(n)` | `min(n + 1, len)`, plus the end probe when `len <= n` | `len == n` |
  | `count_between(a, b)` | `min(b + 1, len)`, plus the end probe when `len <= b` | `a <= len <= b` |
- Known count: when N10's non-enumerated count is available (FlpList, and FlpIt over `list`/`tuple`/`range`/`str`/`dict`/`set` per N10's rule), the answer uses `len` and the source is **not iterated**. This mirrors MoreLINQ's `ICollection<T>.Count` path and is observationally equivalent for those built-ins (no iteration side effects). Tests cover a `list` source and the `non_collection` fixture.
- Validation (eager, before touching the source; `_require_index` first, so `None` → `ArgumentNoneError`, `1.5` → `TypeError`):
  - `count < 0` → `ArgumentOutOfRangeError("count")`, message `Count cannot be negative. (Parameter 'count')`.
  - `min_count < 0` → `Minimum count cannot be negative. (Parameter 'min_count')`.
  - `max_count < min_count` → `Maximum count must be greater than or equal to the minimum count. (Parameter 'max_count')`.
- Huge counts: Python ints do not overflow. MoreLINQ computes `count + 1` in `int`, so `at_most(int.MaxValue)`, `exactly(int.MaxValue)` and `count_between(_, int.MaxValue)` on a non-collection source throw `ArgumentOutOfRangeException` from `CountUpTo` (overflow to a negative limit). flpit returns the correct boolean; README deviation, difftest `EXPECTED_DIFFERENCE`.
- None elements count like any other. Exceptions raised by the source while counting propagate (only up to the bound: an exception at position ≥ limit is never reached).
- One-shot source: consumed up to the bound; the remaining elements stay in the iterator (tested).

### 3.3 Implementation sketch
```python
def _count_up_to(self, limit: int) -> int:                    # private, shared by the four ops
    known = self._known_count()                                # N10 helper: int | None, never iterates
    if known is not None:
        return known
    n = 0
    for n, _ in enumerate(islice(self._source(), limit), 1):   # C-level pull, O(1) memory
        pass
    return n

def at_least(self, count):
    count = _require_non_negative(_require_index(count, "count"), "count", "Count cannot be negative.")
    return self._count_up_to(count) >= count

def at_most(self, count):     # same validation
    return self._count_up_to(count + 1) <= count

def exactly(self, count):     # same validation
    return self._count_up_to(count + 1) == count

def count_between(self, min_count, max_count):
    ...validate as above...
    return min_count <= self._count_up_to(max_count + 1) <= max_count
```
- O(min(limit, n)) time, O(1) memory. `islice` stops pulling at `limit` exactly (no extra `next()`), which is what produces the pull bounds in the table.
- **FlpList fast path:** not a separate override; `_known_count()` already returns `len(data)` in O(1) for FlpList.
- If F05's `_require_non_negative` does not accept a custom message, extend it with an optional `message` argument here (MoreLINQ wording differs from .NET's generic one).

### 3.4 Registry entries
```toml
[operators.at_least]
category = "quantifier"
kind = "terminal"
buffering = "streaming"
short_circuit = true
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.AtLeast"
python_equivalent = "sum(1 for _ in islice(xs, n)) >= n"
contract_args = "(2,)"
contract_max_pull = 2
since = "0.4.0"   # adjust to the release that ships it
card = "M23"

# at_most:       morelinq = "MoreEnumerable.AtMost",       python_equivalent = "sum(1 for _ in islice(xs, n + 1)) <= n", contract_args = "(2,)",   contract_max_pull = 3
# exactly:       morelinq = "MoreEnumerable.Exactly",      python_equivalent = "sum(1 for _ in islice(xs, n + 1)) == n", contract_args = "(2,)",   contract_max_pull = 3
# count_between: morelinq = "MoreEnumerable.CountBetween", python_equivalent = "a <= sum(1 for _ in islice(xs, b + 1)) <= b", contract_args = "(1, 2)", contract_max_pull = 3
```

## 4. Tests
- **Ported:** none (D7, 0 % by design); the 18 MoreLINQ cases (negative count, empty/short/exact/long sources, collection shortcut, `min > max`) are a checklist covered by own tests. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_count_bounds.py`, both `flp_type`s plus a raw-generator FlpIt):
  - Truth tables: lengths 0..4 × counts 0..4 for each op; `count_between` with `a == b`, `a < b`, `a = 0`.
  - **Pull counts** on an instrumented infinite source (`counting_source(itertools.count())`): `at_least(3)` pulls 3; `at_most(3)` pulls 4 and returns False; `exactly(3)` pulls 4; `count_between(1, 3)` pulls 4. On a 2-element source, `at_most(3)` pulls 2 and sees the end.
  - Known-count path: FlpList and `flp.it([..])` never call `__iter__` (a `list` subclass whose `__iter__` raises proves it; N10 decides whether subclasses qualify, the test follows N10's rule).
  - Validation: negative values, `max_count < min_count`, `None`, `1.5`; raised before any pull; messages exact.
  - Exception at position ≥ limit is not reached; exception at position < limit propagates.
  - One-shot remainder: `it = iter(range(10)); flp.it(it).at_least(3)` then `next(it) == 3`.
  - Huge counts: `flp.it(gen()).at_most(2**31 - 1)` returns True for a short generator.
- **Contracts** (auto): `short_circuit = true` with `contract_max_pull` per op, FlpList not mutated.
- **Typing** (`tests/typing/test_types_count_bounds.py`): all four return `bool`.

## 5. Differential harness
`difftest/specs/{at_least,at_most,exactly,count_between}.toml`; oracle `Operators/CountMethods.cs` calling `MoreEnumerable.AtLeast/AtMost/Exactly/CountBetween` statically.
- Counts: `{-1, 0, 1, len-1, len, len+1, 2**31-1}`; pairs for `count_between` including `min > max` and `min < 0`.
- Sources: `counting`, `one_shot`, `throwing_at(i)` (non-collection, F09 default) **plus** an explicit `collection` opt-in kind (.NET `List<T>`, Python `list`) to compare the no-enumeration path.
- Probes: result, `trace` (number of `src.move_next` must equal the table bound), exception timing (`at: "call"`).
- Param-name mapping for messages: `min_count ↔ min`, `max_count ↔ max` (spec field `param_names`).
- Expected: MATCH, except `count = 2**31-1` on non-collection sources for `at_most`/`exactly`/`count_between(max)`: `EXPECTED_DIFFERENCE` (reason: "OTHER: MoreLINQ int overflow in count + 1").

## 6. Benchmarks
`tests/benchmarks/test_bench_count_bounds.py`, sizes 1e3 / 1e5, `k = n // 2`, source a generator function (so the known-count path is not taken):
- `native`: `sum(1 for _ in islice(gen(), k)) >= k`
- `flpit-FlpIt`: `flp.it(gen()).at_least(k)`; `flpit-FlpList`: `flp.lst(data).at_least(k)` vs native `len(data) >= k` (both O(1)).
- Target ratio ≤ 1.5× (terminal short-circuit default).

## 7. Docs
- Docstrings (one per method): summary; `MoreLINQ: MoreEnumerable.AtLeast(count)` etc.; the pull bound in `Execution: Terminal, short-circuits after at most N elements; no enumeration when the count is known`; doctests:
  ```python
  >>> flp.it(x for x in range(10)).at_least(3)
  True
  >>> flp.it([1, 2]).exactly(2)
  True
  >>> flp.it(range(10)).count_between(2, 5)
  False
  >>> flp.it([]).at_most(0)
  True
  ```
- README deviation: no `int` overflow at `2**31 - 1` (MoreLINQ throws).
- Translation map: MoreLINQ `.AtLeast(n)` / Python `sum(1 for _ in islice(xs, n)) >= n` → `.at_least(n)`; same pattern for the other three.

## 8. Expected outcomes
- Four bounded counting predicates whose pull counts are asserted by contract tests and by the difftest trace.
- A reusable `_count_up_to` helper (candidate for reuse by a future `compare_count`).

## 9. Verification
VERIFY-std with `<op>` = `at_least`, `at_most`, `exactly`, `count_between`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_count_bounds.py
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).at_least(5))"   # True (terminates)
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).at_most(5))"    # False (terminates)
uv run python -c "from flpit import flp; flp.it([]).count_between(3, 2)"                                   # ArgumentOutOfRangeError ... (Parameter 'max_count')
```

## 10. Definition of Done
DoD-std, plus: pull-count table reproduced in tests; README deviation for the overflow case.

## 11. Risks / open questions
- Depends on N10 for `_known_count()`. If N10 slips, implement the helper locally with N10's intended rule (exact built-in types only) and let N10 adopt it.
- Parameter rename `min_count`/`max_count` breaks keyword-call parity with MoreLINQ (`CountBetween(min: 1, max: 2)`); positional calls are unaffected. Revisit only if the maintainer prefers literal names over the ruff rule.
