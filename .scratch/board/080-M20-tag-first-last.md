---
id: M20
title: tag_first_last
status: todo
priority: 080
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: TagFirstLast.cs @ morelinq master d217ab1 (reference only, D7; TagFirstLastTest.cs 7 [Test] read for behaviour)
pr:
---

# M20: `tag_first_last`

## 1. Goal
Rendering and formatting code often needs "is this the first/last element?" (separators, table borders, closing brackets). With a one-shot source the last element cannot be detected without a one-element look-ahead, which is easy to get wrong by hand. `tag_first_last` provides it as a streaming operator, with a Python-friendly default result (a NamedTuple) in addition to MoreLINQ's result-selector form.

## 2. Scope
**In:** `tag_first_last()` (default projection to `TaggedItem`) and `tag_first_last(result_selector)` on `_LinqOps`; new public generic NamedTuple `TaggedItem[T]` exported from `flpit`. No FlpList override.
**Out:** an indexed variant (not in MoreLINQ; use `index()` from N01 if needed).

## 3. Detailed design
### 3.1 Signatures
```python
class TaggedItem(NamedTuple, Generic[TItem]):
    item: TItem
    is_first: bool
    is_last: bool

@overload
def tag_first_last(self) -> FlpIt[TaggedItem[TItem]]: ...
@overload
def tag_first_last(
    self, result_selector: Callable[[TItem, bool, bool], TResult]
) -> FlpIt[TResult]: ...
def tag_first_last(
    self, result_selector: Callable[[TItem, bool, bool], Any] | _Sentinel = _SENTINEL
) -> FlpIt[Any]: ...
```
.NET overload mapping: `TagFirstLast(Func<TSource, bool, bool, TResult>)` → `tag_first_last(result_selector)` with the same argument order `(item, is_first, is_last)`. The no-argument form is a Python addition (MoreLINQ users write `(x, f, l) => (x, f, l)`).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial, a look-ahead of exactly one element. Short-circuit: n/a, but it never pulls more than one element beyond what it has yielded.
- Pull order (observable, matches MoreLINQ): to yield element `i` the source has been advanced to element `i + 1` (or to its end). So `tag_first_last().first()` pulls 2 elements; on a singleton it pulls 1 and hits the end.
- `result_selector` is called once per element, lazily, right before that element is yielded; never on an empty source.
- Singleton: one result with `is_first=True, is_last=True`. Empty: nothing.
- None elements are ordinary items.
- Validation (eager): `result_selector is None` raises `ArgumentNoneError("result_selector")`; omitting it selects the default.
- Exceptions from the source while looking ahead surface **before** the current element is yielded (same as MoreLINQ, since `MoveNext` happens first).
- Re-enumeration re-runs the source.

### 3.3 Implementation sketch
```python
def tag_first_last(self, result_selector=_SENTINEL):
    if result_selector is None:
        raise ArgumentNoneError("result_selector")
    def _generator():
        it = iter(self)
        for current in it:
            break
        else:
            return
        first = True
        if result_selector is _SENTINEL:
            new, cls = tuple.__new__, TaggedItem          # skips NamedTuple.__new__ overhead
            for nxt in it:
                yield new(cls, (current, first, False))
                first, current = False, nxt
            yield new(cls, (current, first, True))
        else:
            for nxt in it:
                yield result_selector(current, first, False)
                first, current = False, nxt
            yield result_selector(current, first, True)
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(1) memory. `tuple.__new__(TaggedItem, ...)` produced the same objects ~1.5x faster than `TaggedItem(...)` in the prototype (20 ms vs 32 ms at n = 1e5); a unit test asserts the result is a real `TaggedItem` (fields, `_asdict`, equality).
- **FlpList fast path:** rejected. With a known length one could use `enumerate` and `i == n - 1`, but the look-ahead loop is already O(1) per element and keeps one code path; the measurement is recorded in the PR.

### 3.4 Registry entry
```toml
[operators.tag_first_last]
category = "projection"
kind = "intermediate"
buffering = "partial"      # one-element look-ahead
short_circuit = false
morelinq = "MoreEnumerable.TagFirstLast"
python_equivalent = "[(x, i == 0, i == len(xs) - 1) for i, x in enumerate(xs)]"
since = "0.4.0"   # adjust to the release that ships it
```

## 4. Tests
- **Ported:** none (D7, 0 % by design); skip categories n/a.
- **Own unit tests** (`tests/unit/morelinq/test_tag_first_last.py`, `flp_type`-parametrized):
  - Empty → `[]`; singleton → `[TaggedItem(x, True, True)]`; two and many elements: only the first has `is_first`, only the last has `is_last`.
  - Default result is a `TaggedItem` (isinstance, field names, `_asdict()`, tuple unpacking `for item, first, last in ...`).
  - Selector form receives `(item, is_first, is_last)` in that order; call count = n; no call on empty.
  - Pull-count probe: `tag_first_last().first()` pulls exactly 2 elements from an instrumented source; on a singleton exactly 1 plus the end.
  - A source that raises on element 2 raises before element 1 is yielded.
  - None elements tagged normally; `tag_first_last(None)` raises `ArgumentNoneError` eagerly.
  - One-shot vs list re-enumeration.
- **Contracts** (auto): deferral, lazy callbacks, `buffering = partial` look-ahead bound of 1.
- **Typing** (`tests/typing/test_types_tag_first_last.py`): `assert_type(flp.it([1]).tag_first_last(), FlpIt[TaggedItem[int]])`; `assert_type(flp.it([1]).tag_first_last(lambda x, f, l: str(x)), FlpIt[str])`; `assert_type(t.item, int)` for an element `t`.

## 5. Differential harness
`difftest/specs/tag_first_last.toml`; oracle calls `MoreEnumerable.TagFirstLast(source, (x, f, l) => new { x, f, l })` serialized as `[x, f, l]`; the Python side maps `TaggedItem` to the same 3-element list.
- Sources: empty, singleton, two, many, strings, nullable ints, a throwing source (throws at index 0, 1, 2).
- Probes: result, `source_items_requested` after `first()` and after `take(k)`, `selector_calls`, exception timing.
- Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_tag_first_last.py`:
- `native`: `n = len(data); [(x, i == 0, i == n - 1) for i, x in enumerate(data)]`
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(data).tag_first_last().to_list()`; plus a selector variant `tag_first_last(lambda x, f, l: x)` against native `[x for x in data]` with the same lambda.
- Target ratio ≤ 1.8× for the default form (NamedTuple construction, native uses plain tuples), ≤ 1.5× for the selector form.

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.TagFirstLast(resultSelector)`; Args/Returns/Raises; `Execution: Deferred, streaming with a one-element look-ahead`; doctests:
  ```python
  >>> flp.it("abc").tag_first_last().to_list()
  [TaggedItem(item='a', is_first=True, is_last=False), TaggedItem(item='b', is_first=False, is_last=False), TaggedItem(item='c', is_first=False, is_last=True)]
  >>> flp.it([1, 2, 3]).tag_first_last(lambda x, f, l: f"{'[' if f else ''}{x}{']' if l else ''}").to_list()
  ['[1', '2', '3]']
  ```
- `TaggedItem` gets its own docstring and is listed in the README public types.
- Translation map: MoreLINQ `.TagFirstLast((x, f, l) => ...)` / Python `enumerate` + `len` → `.tag_first_last(lambda x, f, l: ...)` or `.tag_first_last()`.

## 8. Expected outcomes
- Streaming first/last tagging on one-shot sources, with a typed NamedTuple default.
- `TaggedItem` exported from `flpit` and `flpit.core`.
- difftest spec 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=tag_first_last`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_tag_first_last.py
uv run python -c "from flpit import flp; print(flp.it('a').tag_first_last().to_list())"   # [TaggedItem(item='a', is_first=True, is_last=True)]
uv run python -c "from flpit import TaggedItem; print(TaggedItem._fields)"                  # ('item', 'is_first', 'is_last')
```

## 10. Definition of Done
DoD-std, plus: `TaggedItem` exported and documented; pull-count test for the look-ahead.

## 11. Risks / open questions
- Field names `item/is_first/is_last` are a public API choice; alternatives (`value`, `first`, `last`) were rejected because `first`/`last` would shadow the tuple-unpacking intent and collide with LINQ method names in readers' minds.
- Generic NamedTuple needs Python ≥ 3.11 (fine with D2); confirm pyrefly infers `TaggedItem[int]` correctly, else add an explicit `cast`.
