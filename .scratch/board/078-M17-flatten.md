---
id: M17
title: flatten
status: todo
priority: 078
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (SelectMany flattens exactly one level)
  morelinq: Flatten.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; FlattenTest.cs has 14 [Test]/[TestCase])
pr:
---

# M17: `flatten`

## 1. Goal
`flatten` recursively unnests arbitrarily nested iterables into a flat stream: JSON-like data, nested config lists, trees given as nested lists. `select_many` does one level; Python has no stdlib deep flatten (people copy a recursive generator or install `more_itertools.collapse`). Effort M because the Python-specific rules (strings, bytes, mappings, recursion depth) need care.

## 2. Scope
**In:** `flatten(predicate=..., *, selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`): default form, predicate form, selector form. Iterative (explicit stack), no recursion limit.
**Out:** a `levels=` depth limit (not in MoreLINQ; `selector` can express it with external state); cycle detection (MoreLINQ has none; a self-containing list loops forever, documented).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `Flatten(this IEnumerable)` (everything except `string` is flattened) | `flatten()` (everything iterable except `str`, `bytes`, `bytearray`) |
| `Flatten(Func<IEnumerable, bool> predicate)` | `flatten(predicate)`: called for each nested iterable; truthy → flatten it |
| `Flatten(Func<object, IEnumerable?> selector)` | `flatten(selector=f)`: called for every element; returns the iterable to descend into, or `None` for a leaf |

`selector` is keyword-only: predicate and selector are both 1-argument callables and cannot be told apart at runtime.

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def flatten(self) -> FlpIt[Any]: ...
@overload
def flatten(self, predicate: Callable[[Iterable[Any]], bool]) -> FlpIt[Any]: ...
@overload
def flatten(self, *, selector: Callable[[Any], Iterable[Any] | None]) -> FlpIt[Any]: ...
```
`Any` result as in MoreLINQ (`IEnumerable<object>`): leaf types of arbitrary nesting are not expressible; users narrow with `.cast(T)` / `.of_type(T)` / `as_type`.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (a stack of iterators, one per open nesting level; no element buffer). Short-circuit: n/a.
- Order: depth-first, left to right (pre-order of leaves), same as MoreLINQ.
- **Default form:** an element is descended into iff `isinstance(x, collections.abc.Iterable)` and not `isinstance(x, (str, bytes, bytearray))`. Strings must stay atomic: a 1-character `str` iterates to itself, so recursing would never terminate (MoreLINQ's `obj is not string` rule has the same purpose; `char` is not enumerable in .NET).
- **Predicate form:** the same iterable test first (`str`/`bytes`/`bytearray` are **never** passed to the predicate, they are always leaves), then `predicate(x)` decides. Non-iterables never reach the predicate.
- **Selector form:** `selector(x)` is called for **every** element at every level (including strings); a non-`None` return is iterated (it may differ from `x`, e.g. `node.children`); `None` → `x` is yielded as a leaf. The selector owns termination: returning a 1-char string for a 1-char string loops forever (documented).
- Mappings: a `dict` is an `Iterable` of its keys, so the default form yields the keys (MoreLINQ yields `KeyValuePair` objects). Use `selector=` to descend into `.items()`/`.values()`. Documented.
- Nested iterators/generators are consumed when reached (lazily, MoreLINQ "evaluates inner sequences lazily"). `FlpIt`, `FlpList`, `Grouping` elements are iterables and get flattened.
- `None` elements are leaves. Empty nested iterables contribute nothing.
- Depth: unlimited (explicit stack). 100 000 nesting levels work.
- Validation (eager): `predicate=None` / `selector=None` → `ArgumentNoneError`; both given → `TypeError("flatten() takes either predicate or selector=")`.
- Exceptions from `iter()`, `next()` of any level, or the callbacks propagate at enumeration.
- Re-enumeration: re-iterates the source; nested one-shot iterators are consumed by the first pass.

### 3.3 Implementation sketch
```python
_ATOMIC = (str, bytes, bytearray)

def _generator():
    stack = [iter(src)]
    while stack:
        for x in stack[-1]:
            inner = descend(x)                      # default/predicate/selector, bound once
            if inner is not None:
                stack.append(iter(inner))
                break
            yield x
        else:
            stack.pop()

def _descend_default(x):
    return x if isinstance(x, Iterable) and not isinstance(x, _ATOMIC) else None
```
- `for x in stack[-1]` resumes the parent iterator after the child finishes (the `break`/`else` pair replaces MoreLINQ's `goto reloop`). O(total elements) time, O(depth) memory.
- `isinstance(x, Iterable)` hits the ABC cache per type; the default path checks `type(x) in _LEAF_FAST` (`int`, `float`, `bool`, `NoneType`) first, measured in the benchmark.
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.flatten]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.Flatten"
python_equivalent = "recursive generator: yield from flatten(x) if iterable and not str"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `FlattenTest.cs` (14 cases) as checklist:
  - covered: default flatten of mixed nesting, flatten + cast, laziness, predicate, predicate always false / always true, predicate is lazy, inner sequences evaluated lazily, selector is lazy, selector, selector filtering only integers, selector over a tree.
  - `OTHER` (no `IDisposable`): "fully iterated disposes inner sequences", "interrupted iteration disposes inner sequences".
  - Target: 100 % of applicable behaviours.
- **Own unit tests** (`tests/unit/morelinq/test_flatten.py`, both `flp_type`s):
  - `[1, [2, [3, [4]]], "ab", (5, 6), b"xy", {7}]` → `[1, 2, 3, 4, 'ab', 5, 6, b'xy', 7]`.
  - Predicate `lambda it: not isinstance(it, tuple)` keeps tuples whole; predicate never receives `str`/`bytes` or non-iterables (call log).
  - Selector: tree nodes via `lambda n: n.children if isinstance(n, Node) else None`; selector exploding multi-char strings into characters.
  - Dict yields keys; `selector=lambda x: x.items() if isinstance(x, dict) else None` variant.
  - Deep nesting (1e5 levels) does not hit `RecursionError`.
  - Nested generator is pulled lazily (`take(2)` leaves it partially consumed); empty nested lists; `None` leaves.
  - Validation: `None` callables, both arguments.
  - One-shot vs list re-enumeration.
- **Contracts:** auto via registry.
- **Typing:** `assert_type(flp.it([[1]]).flatten(), FlpIt[Any])`; selector returning `None | list` accepted.

## 5. Differential harness
`difftest/specs/flatten.toml`, oracle calls the three `MoreEnumerable.Flatten` overloads on `object[]` trees (pinned `morelinq` NuGet). Domains: nesting depth 0 to 4, ints, strings, empty arrays, nulls; predicates `always_true`, `always_false`, `len_lt(k)`; selectors from a catalogue (`children_of_node`, `only_int_arrays`). Probes: values, predicate/selector call log. Expected: MATCH; `UNCOMPARABLE` for byte arrays and dictionaries (atomic in flpit / KeyValuePair in .NET) and for predicate cases involving strings (MoreLINQ passes strings to the predicate), each with the reason recorded.

## 6. Benchmarks
`tests/benchmarks/test_bench_flatten.py`, sizes 1e3 / 1e5 leaves: (a) list of lists of ints (depth 2), (b) depth-10 nesting:
- `native`: the recursive generator a reviewer would write, materialised with `list(deep(data))`:
  ```python
  def deep(xs):
      for x in xs:
          if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
              yield from deep(x)
          else:
              yield x
  ```
  For (a) also `list(chain.from_iterable(xss))` as a 1-level reference.
- `flpit-FlpIt` / `flpit-FlpList`: `flatten().to_list()`.
- Target ratio ≤ 1.5× vs the recursive generator (expected faster for deep nesting, no generator-per-level chain).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Flatten([predicate | selector])`; Args (atomic types, predicate vs selector contract); Raises; `Execution:` deferred, streaming, iterative (no recursion limit); warning about cycles and selector termination.
- Doctest:
  ```python
  >>> flp.it([1, [2, [3, [4]]], "ab", (5, 6)]).flatten().to_list()
  [1, 2, 3, 4, 'ab', 5, 6]
  >>> flp.it([1, [2, (3, 4)]]).flatten(lambda it: not isinstance(it, tuple)).to_list()
  [1, 2, (3, 4)]
  ```
- Translation map: `.Flatten()` / `more_itertools.collapse(xs)` / recursive generator → `.flatten()`; `.SelectMany(x => x)` (one level) stays `.select_many(lambda x: x)`.
- Deviations (README): `bytes`/`bytearray` atomic and never passed to the predicate; dicts flatten to keys; strings excluded from the predicate form.

## 8. Expected outcomes
- `flatten` with three forms on all four types; ~15 own tests; difftest 0 MISMATCH (with declared UNCOMPARABLE cases); benchmark recorded.

## 9. Verification
VERIFY-std with `<op>=flatten`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_flatten.py
uv run python -c "from flpit import flp; print(flp.it([1,[2,[3,[4]]],'ab',(5,6)]).flatten().to_list())"   # [1, 2, 3, 4, 'ab', 5, 6]
```

## 10. Definition of Done
DoD-std, plus the three README deviation bullets for `flatten`.

## 11. Risks / open questions
- Mappings: flatten to keys (Python iteration semantics, proposed) or treat `Mapping` as atomic (closer to "a record is a leaf")? Proposal: keys, because any other choice special-cases one ABC; revisit if users object.
- `memoryview` and `array.array` iterate to numbers and are flattened by default; listed in the docstring rather than added to the atomic set.
