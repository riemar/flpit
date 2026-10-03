---
id: M26
title: for_each / consume
status: todo
priority: 086
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (related: List<T>.ForEach, not part of System.Linq)
  morelinq: ForEach.cs, Consume.cs @ morelinq master d217ab1 (reference only, D7; ForEachTest.cs 3 + ConsumeTest.cs 2 [Test] read for behaviour)
pr:
---

# M26: `for_each` / `for_each_indexed` / `consume`

## 1. Goal
Pipelines that end in a side effect (print, write, send) currently need `for x in query: f(x)` or the "list of Nones" anti-pattern `[f(x) for x in query]`. `for_each(action)` ends a fluent chain with an explicit side effect; `consume()` drains a query whose work happens in earlier `select`/`where` callbacks (the itertools `consume` recipe). Both are trivial but are in the curated list because .NET users reach for `ForEach` constantly.

## 2. Scope
**In:** `for_each(action)`, `for_each_indexed(action)` (D4 suffix for MoreLINQ's `Action<T, int>` overload) and `consume()` on `_LinqOps`.
**Out:** a chainable "tap"/"pipe" (MoreLINQ `Pipe`, not curated); parallel/async variants; guarding against mutation of a FlpList inside its own `for_each` (see §3.2).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `ForEach(Action<T>)` | `for_each(action)` |
| `ForEach(Action<T, int>)` | `for_each_indexed(action)` with `action(item, index)` (D4) |
| `Consume()` | `consume()` |

## 3. Detailed design
### 3.1 Signatures
```python
def for_each(self, action: Callable[[TItem], object]) -> None: ...
def for_each_indexed(self, action: Callable[[TItem, int], object]) -> None: ...
def consume(self) -> None: ...
```
`object` as the callback return type accepts any callable (`list.append`, `print`, lambdas returning values); the return value is ignored.

### 3.2 Semantics
- Kind: terminal (all three). Buffering: none, streaming. Short-circuit: none; the whole source is enumerated.
- Interleaving (observable, matches MoreLINQ's `foreach`): pull element i, call `action` on it, then pull element i + 1. An exception from `action` stops enumeration immediately; later elements are never pulled.
- `for_each_indexed`: index starts at 0 and increments per element (Python ints, no overflow; MoreLINQ's `int` would overflow after 2^31 elements).
- `consume()`: enumerates and discards; no callback. Useful after side-effecting `select`/`where`.
- Return value: `None` (MoreLINQ returns `void`). Not chainable by design.
- Validation (eager): `action is None` → `ArgumentNoneError("action")`; a non-callable → `TypeError` (`_require_callable`).
- Empty source: no calls. None elements are passed to `action` normally.
- FlpList: `for_each` iterates the backing list. .NET `List<T>.ForEach` throws `InvalidOperationException` when the list is modified during the loop; flpit follows Python list semantics (appending inside the action extends the loop). Documented, not guarded (a version counter would cost on every `add`).

### 3.3 Implementation sketch
```python
def for_each(self, action):
    _require_callable(action, "action")
    for item in self._source():
        action(item)

def for_each_indexed(self, action):
    _require_callable(action, "action")
    for index, item in enumerate(self._source()):
        action(item, index)

def consume(self):
    deque(self._source(), maxlen=0)          # itertools recipe, C-level drain
```
- O(n) time, O(1) memory. `deque(map(action, src), maxlen=0)` measured the same as the plain loop (4.0 ms vs 4.2 ms at 1e5) and gives worse tracebacks, so the loop is used for the callback forms.
- **FlpList fast path:** none. A no-op `consume()` on FlpList would be observably equivalent (iterating a list has no effects) but nobody consumes a materialised list; not worth an override (D1).

### 3.4 Registry entries
```toml
[operators.for_each]
category = "misc"
kind = "terminal"
buffering = "streaming"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.ForEach"
python_equivalent = "for x in xs: action(x)"
variations = ["for_each_indexed"]
contract_args = "(lambda x: None,)"
since = "0.4.0"   # adjust to the release that ships it
card = "M26"

[operators.consume]
category = "misc"
kind = "terminal"
buffering = "streaming"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.Consume"
python_equivalent = "collections.deque(xs, maxlen=0)"
contract_args = "()"
since = "0.4.0"
card = "M26"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design); MoreLINQ's 5 cases (action called per element, indexed action, consume enumerates) each have an own equivalent. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_for_each_consume.py`, both `flp_type`s):
  - `for_each(log.append)` logs every element in order; returns `None`.
  - `for_each_indexed` receives `(item, index)` in that order, indexes `0..n-1`.
  - Interleaving: an event log shared by an instrumented source and the action reads `pull 0, act 0, pull 1, act 1, ...`.
  - Action raising at element 2: elements 3+ are never pulled (counting source).
  - `consume()` on `select(side_effect)` triggers exactly n side effects; on an infinite source wrapped in `take(5)` terminates.
  - Empty source: zero calls. None elements passed through.
  - `for_each(None)` → `ArgumentNoneError`; `for_each(42)` → `TypeError`; both before iterating.
  - One-shot source exhausted afterwards.
- **Contracts** (auto): terminal, FlpList not mutated, eager validation.
- **Typing** (`tests/typing/test_types_for_each.py`): `assert_type(flp.it([1]).for_each(print), None)`; `for_each_indexed(lambda x, i: None)` accepted; `consume()` returns `None`.

## 5. Differential harness
`difftest/specs/for_each.toml`, `for_each_indexed.toml`, `consume.toml`; oracle `Operators/ForEach.cs` calling `MoreEnumerable.ForEach/Consume` statically. The action is the F09 catalogue's recording callback (`count_calls`, `throws_on(k)`), whose `fn.call` events land in the trace.
- Items: empty, singleton, `range(0, 20)`, ints with nulls; sources: `counting`, `one_shot`, `throwing_at(i)`.
- For `consume`, the pipeline is `select(count_calls)` → `consume` (the only observable is the trace).
- Probes: `trace` (pull/act interleaving and stop position on exceptions), result kind `void` (serialised as `null` on both sides).
- Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_for_each.py`, sizes 1e3 / 1e5, `f = lambda x: None`:
- `native` for_each: `for x in data: f(x)`; consume: `deque(map(f, data), maxlen=0)`.
- `flpit-FlpIt` / `flpit-FlpList`: `.for_each(f)`; `.select(f).consume()`.
- Target ratio ≤ 1.5× (streaming terminal).

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.ForEach(action)` / `ForEach(Action<T, int>)` / `Consume()`; Raises; `Execution: Terminal, enumerates the whole source, action interleaved with enumeration`; the FlpList mutation note; doctests:
  ```python
  >>> seen = []
  >>> flp.it("ab").for_each(seen.append)
  >>> seen
  ['a', 'b']
  >>> flp.it("ab").for_each_indexed(lambda x, i: print(i, x))
  0 a
  1 b
  >>> flp.it(range(3)).select(print).consume()
  0
  1
  2
  ```
- README deviation: FlpList `for_each` does not detect modification during iteration (.NET `List<T>.ForEach` does).
- Translation map: MoreLINQ `.ForEach(f)` / .NET `List<T>.ForEach(f)` / Python `for x in xs: f(x)` → `.for_each(f)`; `.ForEach((x, i) => ...)` / `for i, x in enumerate(xs)` → `.for_each_indexed(f)`; `.Consume()` / `deque(xs, maxlen=0)` → `.consume()`.

## 8. Expected outcomes
- Three side-effect terminals on all four types, typed and documented.
- difftest specs 0 MISMATCH on interleaving traces.

## 9. Verification
VERIFY-std with `<op>` = `for_each`, `for_each_indexed`, `consume`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_for_each_consume.py
uv run python -c "from flpit import flp; flp.it('ab').for_each_indexed(lambda x, i: print(i, x))"   # 0 a / 1 b
uv run python -c "from flpit import flp; flp.it(range(3)).select(print).consume()"                  # 0 / 1 / 2
```

## 10. Definition of Done
DoD-std, plus: `for_each_indexed` listed as a `variations` entry of `for_each` in the registry; README deviation for FlpList mutation.

## 11. Risks / open questions
- `for_each` on `FlpList` shadows nothing today, but if a future card adds .NET `List<T>` methods to FlpList, `ForEach` is one of them; this card's implementation already covers that use, so no second method should be added.
- D4 enumerates the .NET indexed methods; `for_each_indexed` extends the same pattern to a MoreLINQ overload. If the maintainer wants D4 to be exhaustive, add it to the D4 list in README.
