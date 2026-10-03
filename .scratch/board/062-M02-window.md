---
id: M02
title: window / window_left / window_right
status: todo
priority: 062
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Window.cs, WindowLeft.cs, WindowRight.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7)
pr:
---

# M02: `window` / `window_left` / `window_right`

## 1. Goal
Sliding windows (moving averages, n-gram features, local maxima) are the most common sequence pattern without a stdlib operator: Python only documents a `sliding_window` *recipe* in `itertools`. MoreLINQ provides three variants: full windows only (`Window`), and windows that are partial at the end (`WindowLeft`) or at the start (`WindowRight`). The three share one bounded-deque core, so they ship together.

## 2. Scope
**In:** `window(size)`, `window_left(size)`, `window_right(size)` on `_LinqOps`; each window is a fresh `FlpList` (consistent with `chunk`); own tests; MoreLINQ oracle ops.
**Out:** padded windows (`more_itertools.windowed` `fillvalue`; use M12 `pad`); step > 1 (`chunk` covers step = size; others are not in MoreLINQ); zero-copy views.

## 3. Detailed design
### 3.1 Signatures
```python
def window(self, size: int) -> FlpIt[FlpList[TItem]]: ...
def window_left(self, size: int) -> FlpIt[FlpList[TItem]]: ...
def window_right(self, size: int) -> FlpIt[FlpList[TItem]]: ...
```
MoreLINQ `Window(size)`, `WindowLeft(size)`, `WindowRight(size)` (single overloads, `IList<TSource>` windows) map 1:1.

### 3.2 Semantics
For source `[1, 2, 3, 4]`, `size = 3`:

| op | windows | count |
|---|---|---|
| `window` | `[1,2,3] [2,3,4]` | `max(0, n - size + 1)` |
| `window_left` | `[1,2,3] [2,3,4] [3,4] [4]` | `n` |
| `window_right` | `[1] [1,2] [1,2,3] [2,3,4]` | `n` |

- Kind: intermediate, deferred. Buffering: partial (bounded deque of `size`). Short-circuit: `window(k).first()` and `window_left(k).first()` pull `min(k, n)` elements; `window_right(k).first()` pulls 1.
- `window` on a source shorter than `size` yields nothing; `window_left` then yields the shrinking suffixes (`[1,2] [2]` for `[1, 2]`, size 3).
- Validation (eager, all three): `size = operator.index(size)`; `size <= 0` → `ArgumentOutOfRangeError("size", size)`. **MoreLINQ quirk:** `WindowRight` only rejects `size < 0`, and `WindowRight(0)` yields one-element windows; flpit rejects `0` for all three (consistency; difftest `EXPECTED_DIFFERENCE`).
- Independence: every window is a new `FlpList`; mutating one (`add`, slice assignment) never affects the next, the previous, or a re-enumeration (MoreLINQ copies before exposing a window; same contract).
- **Copy-per-window cost:** O(size) time and allocation per yielded window, so O(n · size) overall. Documented with the alternative: when only an aggregate is needed, `pairwise`/`scan` or the tuple recipe avoid the copies.

### 3.3 Implementation sketch
```python
def window(self, size):
    size = _require_positive_index(size, "size")
    def _generator():
        it = iter(self)
        d = deque(islice(it, size), maxlen=size)
        if len(d) < size:
            return
        yield FlpList._adopt(list(d))
        for x in it:
            d.append(x)                                   # maxlen drops the oldest
            yield FlpList._adopt(list(d))
    return FlpIt(_FactoryIterable(_generator))

def window_right(self, size):                             # partial at the start
    ...
        d = deque(maxlen=size)
        for x in self:
            d.append(x); yield FlpList._adopt(list(d))

def window_left(self, size):                              # partial at the end
    ...
        d = deque(maxlen=size)
        for x in self:
            d.append(x)
            if len(d) == size: yield FlpList._adopt(list(d))
        if len(d) == size: d.popleft()                    # that full window was already yielded
        while d:
            yield FlpList._adopt(list(d)); d.popleft()
```
- `deque(maxlen=size)` gives O(1) slide; `list(d)` is the per-window copy. Memory: O(size) live state.
- `FlpList._adopt` (B09) avoids the ~1.4 µs `FlpList(...)` overhead; without B09 use `FlpList(d)`.
- **FlpList fast path** (`data[i:i + size]` slices): candidate, adopted only if ≥ 20 % faster at size 5 and 100; it must then read `len(data)` lazily per step so mutations during enumeration behave like the iterator path. Default: no override.

### 3.4 Registry entry
```toml
[operators.window]
category = "windowing"
kind = "intermediate"
buffering = "partial"          # deque of size
short_circuit = false
morelinq = "MoreEnumerable.Window"
python_equivalent = "itertools sliding_window recipe"
since = "0.3.0"                # next minor at merge time
# window_left / window_right: identical keys, morelinq = "MoreEnumerable.WindowLeft" / "WindowRight",
# python_equivalent = "deque(maxlen=n) loop"
```

## 4. Tests
- **Own tests** `tests/unit/morelinq/test_window.py` (from scratch, D7), parametrised over the three ops where the property is shared:
  - Table above for `n ∈ {0, 1, 2, 3, 4, 7}` × `size ∈ {1, 2, 3, 10}` against a naive reference (`[xs[i:i+size] ...]` slicing per variant).
  - `size = 1`: all three equal `select(lambda x: [x])`; `size ≥ n`: `window` empty, `window_left` = suffixes, `window_right` = prefixes.
  - `size ∈ {0, -1, None, 2.5}` raise at call time (including `window_right(0)`).
  - Independence: mutate each yielded window; later windows and a re-enumeration unchanged.
  - Pull counts: `window(3).first()` pulls 3, `window_right(3).first()` pulls 1; infinite source + `.take(2)` terminates for `window`/`window_right`.
  - One-shot vs re-iterable source; `FlpList` source not mutated; `None` elements kept.
- **Contracts** (auto, three registry entries).
- **Typing** `tests/typing/test_types_window.py`: `assert_type(flp.it([1]).window(2), FlpIt[FlpList[int]])` for all three.

## 5. Differential harness
`difftest/specs/window.toml` (three ops), oracle = MoreLINQ NuGet: sources {empty, 1, 2, 5, 9 ints, strings}; `size ∈ {1, 2, 3, len, len+1}`; invalid `size ∈ {0, -5}` → `ArgumentOutOfRange` except `window_right(0)` → `EXPECTED_DIFFERENCE` (MoreLINQ accepts 0). Windows compared as lists. Probe `elements_pulled` for `.first()`. Expected: MATCH otherwise.

## 6. Benchmarks
`tests/benchmarks/test_bench_window.py`, sizes 1e3 and 1e5, window sizes 5 and 100:
- `native`: the `itertools` docs `sliding_window` recipe yielding `list(window)` (a tuple-yielding run is also recorded for information).
- `flpit-FlpIt`, `flpit-FlpList`: `.window(k).to_list()`; `window_left`/`window_right` with the matching deque loop as native.
- Target ≤ 1.5× vs the list-yielding recipe with B09 `_adopt` (today's `FlpList(...)` cost would put it near 10×: 184 ms vs 18 ms for 1e5 windows of 5).

## 7. Docs
- Docstrings: `MoreLINQ: MoreEnumerable.Window/WindowLeft/WindowRight`; the table; per-window copy cost; independence of windows. Doctests: `flp.it([1, 2, 3, 4]).window(3).to_list()` → `[[1, 2, 3], [2, 3, 4]]`; `flp.it([1, 2, 3, 4]).window_left(3).to_list()` → `[[1, 2, 3], [2, 3, 4], [3, 4], [4]]`; `flp.it([1, 2, 3, 4]).window_right(3).to_list()` → `[[1], [1, 2], [1, 2, 3], [2, 3, 4]]`.
- Translation map: MoreLINQ `.Window(n)` / `itertools` `sliding_window(xs, n)` recipe / `more_itertools.sliding_window` → `.window(n)`; `.WindowLeft(n)` → `.window_left(n)`; `.WindowRight(n)` / pandas `rolling(n, min_periods=1)` → `.window_right(n)`.

## 8. Expected outcomes
- Three windowing operators with consistent validation and independent `FlpList` windows.
- MoreLINQ oracle 0 MISMATCH (one documented expected difference).
- Benchmark within 1.5× of the recipe once B09 is in.

## 9. Verification
VERIFY-std with `<op>=window` (and `window_left`, `window_right` for the difftest command), plus:
```bash
uv run pytest -q tests/unit/morelinq/test_window.py
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3, 4]).window_left(3).to_list())"   # [[1, 2, 3], [2, 3, 4], [3, 4], [4]]
```

## 10. Definition of Done
DoD-std for each of the three operators, plus: the deviation on `window_right(0)` recorded in the difftest spec and in the docstring.

## 11. Risks / open questions
- Soft dependency on B09 for the benchmark target only.
- A tuple-yielding variant would be ~2× cheaper; rejected for consistency with `chunk` (`FlpList` everywhere). Revisit only with user demand.
