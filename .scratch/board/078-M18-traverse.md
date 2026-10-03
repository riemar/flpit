---
id: M18
title: traverse_depth_first / traverse_breadth_first
status: todo
priority: 078
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Traverse.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; TraverseTest.cs has 6 [Test]/[TestCase])
pr:
---

# M18: `traverse_depth_first` / `traverse_breadth_first`

## 1. Goal
Walk any tree (file systems, ASTs, org charts, nested menus) from a root and a "children of" function, as a lazy flp query: `flp.traverse_depth_first(root, lambda n: n.children).where(...).select(...)`. Python users write recursive generators, which hit `RecursionError` on deep trees, or ad-hoc stack loops; these factories give both orders, iteratively, with LINQ composition.

## 2. Scope
**In:** two factories in the `flp` module (next to `flp.it`, `flp.range`, `flp.repeat`): `flp.traverse_depth_first(root, children)` and `flp.traverse_breadth_first(root, children)`, returning `FlpIt[T]`.
**Out:** instance-method forms (MoreLINQ only offers static methods; a forest is `flp.it(roots).select_many(lambda r: flp.traverse_depth_first(r, f))`); cycle detection / visited sets (MoreLINQ has none; documented); post-order traversal.

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `MoreEnumerable.TraverseDepthFirst<T>(T root, Func<T, IEnumerable<T>> childrenSelector)` | `flp.traverse_depth_first(root, children)` |
| `MoreEnumerable.TraverseBreadthFirst<T>(T root, Func<T, IEnumerable<T>> childrenSelector)` | `flp.traverse_breadth_first(root, children)` |

The factories live on `flp` because they do not start from a sequence; this follows `flp.range`/`flp.repeat` (static `Enumerable.Range` → module function).

## 3. Detailed design
### 3.1 Signatures
```python
# src/flpit/flp.py
def traverse_depth_first(root: TItem, children: Callable[[TItem], Iterable[TItem]]) -> FlpIt[TItem]: ...
def traverse_breadth_first(root: TItem, children: Callable[[TItem], Iterable[TItem]]) -> FlpIt[TItem]: ...
```
Parameter name `children` (short and Pythonic) instead of `children_selector`; the docstring maps it to MoreLINQ's `childrenSelector`.

### 3.2 Semantics
- Kind: factory, deferred. Buffering: partial (DFS: stack of pending siblings, O(depth × branching); BFS: queue of the frontier, O(width)). Short-circuit: n/a (the consumer stops it; `take`, `first` work on infinite trees).
- The root is always yielded first, even if it is `None` (`root` is a value, not validated).
- **Depth-first** = pre-order; children are visited in the order `children(node)` returns them.
- **Breadth-first** = level order; children appended in returned order.
- **Laziness:** `children(node)` is called only when the element **after** `node` is requested (after `node` was yielded and the consumer resumed). `flp.traverse_depth_first(root, f).first()` never calls `f` (MoreLINQ "is streaming" tests).
- The children iterable of a node is fully enumerated when `children(node)` is called (DFS needs it reversed onto the stack; MoreLINQ does the same via `Reverse()`). An infinite children iterable therefore never returns (same as MoreLINQ).
- Returning `None` from `children` raises `TypeError` at enumeration (Python's "'NoneType' object is not iterable"; MoreLINQ throws `NullReferenceException`). Idiom documented: `lambda n: n.children or ()`.
- Validation (eager): `children is None` → `ArgumentNoneError("children")`; not callable → `TypeError`.
- Cycles are not detected: a cyclic graph produces an infinite sequence (bounded use with `take` still works).
- Re-enumeration restarts from `root` and calls `children` again (re-iterable via `_FactoryIterable`).
- No recursion: explicit `list` stack / `collections.deque`; trees of depth 10^6 work.

### 3.3 Implementation sketch
```python
def traverse_depth_first(root, children):
    _require_callable(children, "children")
    def _generator():
        stack = [root]
        pop, extend = stack.pop, stack.extend
        while stack:
            node = pop()
            yield node
            kids = list(children(node))
            kids.reverse()                 # so the first child is popped first
            extend(kids)
    return FlpIt(_FactoryIterable(_generator))

def traverse_breadth_first(root, children):
    _require_callable(children, "children")
    def _generator():
        queue = deque((root,))
        popleft, extend = queue.popleft, queue.extend
        while queue:
            node = popleft()
            yield node
            extend(children(node))
    return FlpIt(_FactoryIterable(_generator))
```
- O(nodes + edges) time. A stack of child *iterators* (lazier, O(depth) memory) was considered; rejected because it changes when children iterables are enumerated relative to MoreLINQ (observable through side-effecting `children`).
- No `FlpList` involvement (factory).

### 3.4 Registry entries
```toml
[operators.traverse_depth_first]
category = "generation"
kind = "factory"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.TraverseDepthFirst"
python_equivalent = "stack loop: pop, yield, push reversed(children(node))"
classes = ["flp"]
since = "0.4.0"   # Phase 3 target; adjust when the release is cut

[operators.traverse_breadth_first]
category = "generation"
kind = "factory"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.TraverseBreadthFirst"
python_equivalent = "deque loop: popleft, yield, extend(children(node))"
classes = ["flp"]
since = "0.4.0"
```

## 4. Tests
- **Ported:** none (D7). `TraverseTest.cs` (6 cases) as checklist, all applicable and covered: DFS with a throwing children selector is lazy, BFS is streaming, DFS/BFS preserve children order, BFS level order, DFS pre-order. Target: 100 %.
- **Own unit tests** (`tests/unit/morelinq/test_traverse.py`):
  - Tree `{1: [2, 3], 2: [4, 5], 3: [6]}`: DFS `[1, 2, 4, 5, 3, 6]`, BFS `[1, 2, 3, 4, 5, 6]`.
  - `first()` never calls `children`; `take(k)` calls it exactly k-1 times (call log).
  - Children order preserved (DFS reversal correctness on 3+ children).
  - Depth 10^6 linear chain: no `RecursionError`, correct count (`count()`).
  - Infinite tree (`lambda n: (2 * n, 2 * n + 1)`) with `take(7)` → `[1, 2, 4, 8, ...]` for DFS and `[1, 2, ..., 7]` for BFS.
  - `None` root yielded; `children` returning `None` → `TypeError` at the right step; `children=None` → `ArgumentNoneError` at call time.
  - Re-enumeration restarts at the root; children given as generators work.
  - Composition: `.where(...).select(...)` on the factory result; forest via `select_many`.
- **Contracts:** registry-driven factory checks (deferral: constructing does not call `children`; re-iterable).
- **Typing** (`tests/typing/test_types_traverse.py`): `assert_type(flp.traverse_depth_first(1, lambda n: [n]), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/traverse_depth_first.toml`, `traverse_breadth_first.toml`; source kind `factory` (new in the F09 protocol for factories: `{"kind": "factory", "op": "...", "root": 1, "children": {"fn": "children_from_table", "arg": {...}}}`), oracle calls `MoreEnumerable.TraverseDepthFirst/BreadthFirst` statically (pinned `morelinq` NuGet). New portable catalog function `children_from_table(table)` (node → list of child ids; missing → empty) plus `throws_on(k)`. Domains: single node, chain, balanced binary depth 4, wide (20 children), unbalanced; terminals `to_list`, `first`, `take(3)`. Probes: values, `fn.call` trace. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_traverse.py`, sizes 1e3 / 1e5 nodes (complete 4-ary tree in a dict):
- `native`: the hand-written stack loop (DFS) and `deque` loop (BFS) as a reviewer would write them, collected into a list; also the recursive DFS generator for reference (size 1e3 only).
- `flpit`: `flp.traverse_depth_first(0, tree.__getitem__).to_list()` (and BFS). No `FlpList` variant (factory); the group records "n/a" for it.
- Target ratio ≤ 1.3× (partial buffering; same loop plus the `FlpIt` wrapper).

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.TraverseDepthFirst/TraverseBreadthFirst(root, childrenSelector)`; Args; Raises; `Execution:` deferred, lazy children calls, iterative, cycles not detected.
- Doctest:
  ```python
  >>> tree = {1: [2, 3], 2: [4, 5], 3: [6], 4: [], 5: [], 6: []}
  >>> flp.traverse_depth_first(1, tree.__getitem__).to_list()
  [1, 2, 4, 5, 3, 6]
  >>> flp.traverse_breadth_first(1, tree.__getitem__).to_list()
  [1, 2, 3, 4, 5, 6]
  ```
- Translation map: `MoreEnumerable.TraverseDepthFirst(root, f)` / recursive generator → `flp.traverse_depth_first(root, f)`; `TraverseBreadthFirst` / `deque` BFS loop → `flp.traverse_breadth_first(root, f)`.
- Deviations (README): module-level factories instead of static methods; `children` returning `None` raises `TypeError`.

## 8. Expected outcomes
- Two new `flp` factories exported in `flp.__all__`; ~12 own tests; two difftest specs 0 MISMATCH; benchmark recorded.
- F09 protocol gains the `factory` source kind (also usable later by B07 `range`, B08 `repeat`, N12 `sequence`).

## 9. Verification
VERIFY-std with `<op>=traverse_depth_first` and `<op>=traverse_breadth_first`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_traverse.py
uv run python -c "from flpit import flp; print(flp.traverse_breadth_first(1, lambda n: [2*n, 2*n+1] if n < 4 else []).to_list())"
# [1, 2, 3, 4, 5, 6, 7]
```

## 10. Definition of Done
DoD-std, plus `flp.__all__` updated and the registry/docs generator handles `classes = ["flp"]` factories (if F06 does not yet, extend it in this PR).

## 11. Risks / open questions
- Cross-card: if B07/B08/N12 introduce the factory source kind in F09 first, reuse it; otherwise this card adds it.
- A `max_depth=` keyword or a `visited` key set would be useful extensions; deferred until requested (not in MoreLINQ, no oracle).
