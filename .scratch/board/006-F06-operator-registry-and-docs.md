---
id: F06
title: Operator registry, docstring conventions, docs generator
status: todo
priority: 006
effort: M
depends_on: [F05]
upstream:
  dotnet: src/libraries/System.Linq/ref/System.Linq.cs (overload inventory)
  morelinq: README operator list (names only)
pr:
---

# F06: Operator registry, docstring conventions, docs generator

## 1. Goal
Create **one machine-readable source of truth** for every operator, implemented or planned. It drives four consumers, so docs never drift:
1. the README operator matrix (D9),
2. registry-driven contract tests (F08),
3. the agent skill API reference and translation map (A01, D13),
4. the differential-harness coverage check (F09).

Also fix the docstring standard (Google style + runnable examples) and lint it.

## 2. Scope
**In**
- `src/flpit/_operators.toml`: shipped as package data, read with stdlib `tomllib`, never imported at runtime by the library itself (zero import cost).
- `scripts/gen_docs.py` with `--check` (exit 1 on diff); writes:
  - README block between `<!-- BEGIN:OPERATORS -->` / `<!-- END:OPERATORS -->`
  - targets registered by A01 (skill references), via a small target list in the script
- Seed the registry with **all current operators (status `implemented`) and all board cards (status `planned`, with `card` ID)**, so the README shows the roadmap.
- Docstring standard: ruff `D` rules with `convention = "google"` for `src/` only; rewrite existing docstrings to the standard (summary, `.NET:` line, Args/Returns/Raises, Execution, Examples).
- Contract test linking registry ↔ code.
- CI: add `uv run python scripts/gen_docs.py --check` to the `lint` job of `ci.yml`.

**Out:** a docs site (D9); skill files themselves (A01).

## 3. Detailed design
### 3.1 Registry schema
```toml
schema_version = 1

[operators.where]
category       = "filtering"          # filtering|projection|partitioning|ordering|grouping|set|join|
                                      # element|quantifier|aggregation|conversion|generation|
                                      # concatenation|windowing|combinatorics|misc
kind           = "intermediate"       # intermediate|terminal|factory
buffering      = "streaming"          # streaming|partial|full|hybrid (hybrid: buffers one input fully, streams the other)
short_circuit  = false                # terminal ops: stops early when result known
deferred_validation = false           # true only if an argument can't be validated eagerly
origin         = "dotnet"             # dotnet|dotnet-list (List<T> instance API on FlpList, D28)|morelinq|flpit
dotnet         = "Enumerable.Where"   # or "" for morelinq-only
morelinq       = ""                   # e.g. "MoreEnumerable.Window"
python_equivalent = "(x for x in xs if pred(x))"
variations     = ["where_indexed"]    # methods delivered together (D4/D5 variants)
aliases        = []                   # e.g. ["to_hash_set"] on to_set
contract_args  = "(lambda x: x > 1,)" # example args for registry-driven contract tests (F08)
contract_max_pull = ""                # short-circuit bound expression, e.g. "1" for first()
bench_target   = 1.5                  # optional override of the default ratio target (F07)
classes        = ["FlpIt", "FlpList", "OrderedIt", "Grouping"]   # default: all via _LinqOps
status         = "implemented"        # implemented|planned|dropped
since          = "0.1.0"
card           = "L15"                # board card that owns the next change
notes          = ""                   # deviation summary (links README section)
```
Factories (`flp.range`, `flp.empty`, ...) use `kind = "factory"` and `classes = ["flp"]`.

### 3.2 Generated README matrix (example rows)
| Operator | Category | .NET | MoreLINQ | Python idiom | Execution | Status |
|---|---|---|---|---|---|---|
| `where` (+`where_indexed`) | filtering | `Where` | | `(x for x in xs if p(x))` | deferred · streaming | ✅ 0.1.0 |
| `skip` | partitioning | `Skip` | | `islice(xs, n, None)` | deferred · streaming | 🗓 L01 |
| `window` | windowing | | `Window` | `zip(*(islice(xs,i,None) for i in range(k)))` | deferred · partial | 🗓 M02 |

Grouped by category, sorted by name; a summary line "N/M .NET operators, K MoreLINQ operators implemented".

### 3.3 `gen_docs.py`
- Pure stdlib (`tomllib`, `inspect`, `importlib`, `difflib`); runs in < 1 s.
- Pulls the **first docstring line** of each implemented operator via `inspect.getdoc` for the skill reference (A01), so docstrings remain the source for prose and the registry the source for metadata.
- `--check` prints a unified diff and exits 1 when any target is stale.
- Deterministic output (sorted keys, no timestamps), so CI diffs are stable.

### 3.4 Docstring standard (template)
```python
def skip(self, count: int) -> FlpIt[TItem]:
    """Bypasses a specified number of elements and returns the remaining elements.

    .NET: ``Enumerable.Skip(count)``

    Args:
        count: Number of elements to skip. Values <= 0 skip nothing.

    Returns:
        A deferred query over the remaining elements.

    Raises:
        ArgumentNoneError: If ``count`` is None (raised immediately).
        TypeError: If ``count`` is not an integer (raised immediately).

    Execution:
        Deferred, streaming. Re-iterable if the source is.

    Examples:
        >>> flp.it(range(5)).skip(2).to_list()
        [2, 3, 4]
    """
```
- Ruff: `[tool.ruff.lint.pydocstyle] convention = "google"`, `extend-select = ["D"]` scoped to `src/` via `per-file-ignores` for `tests/**`.
- Doctests: `--doctest-modules src` (already in F03). `conftest.py` at `src/` level injects `flp`, `FlpIt`, `FlpList` into the doctest namespace (`doctest_namespace` fixture), so examples stay short.

### 3.5 Contract test `tests/contracts/test_registry.py`
- Every public operator method on `_LinqOps`/`OrderedIt`/`Grouping` and every public function in `flpit.flp` has a registry entry with `status = "implemented"`, and vice versa (names + `variations`).
- Every `planned` entry references an existing board card ID (pattern `^[FLNBMAX]\d\d$`).
- Enum fields contain only allowed values.

## 4. Tests
- `test_registry.py` as above, and it fails if a method is added without a registry entry.
- `gen_docs.py --check` in CI.
- Doctests for every existing operator (≥ 1 example each); all pass.
- ruff `D` rules clean on `src/`.

## 5. Differential harness
F09 reads `dotnet`/`morelinq` names from the registry to know which operators need a spec; F09's coverage check lists implemented operators lacking `difftest/specs/<op>.toml`.

## 6. Benchmarks
n/a (generator runtime asserted < 1 s in its own unit test).

## 7. Docs
- README: generated matrix replaces the hand-written tables; keep the narrative sections.
- `CONTRIBUTING.md`: "Adding an operator" = DoD-std, with the docstring template.

## 8. Expected outcomes
- README shows the full roadmap matrix (implemented vs planned with card IDs).
- Any undocumented or unregistered public operator fails CI.
- Every existing operator has a runnable, verified example.

## 9. Verification
```bash
uv run python scripts/gen_docs.py && git diff --stat README.md     # matrix inserted
uv run python scripts/gen_docs.py --check; echo $?                  # 0
uv run pytest -q tests/contracts/test_registry.py
uv run pytest -q --doctest-modules src
uv run ruff check src --select D
# negative: add a dummy public method → test_registry fails; edit README matrix by hand → --check fails
```

## 10. Definition of Done
- [ ] Registry with all implemented and planned operators
- [ ] gen_docs.py (+ --check) and CI step
- [ ] Docstrings rewritten to the standard; ruff D clean; doctests green
- [ ] Registry contract test
- [ ] README matrix generated; CONTRIBUTING.md

## 11. Risks / open questions
- Registry lives in `src/flpit/` (shipped in the wheel, ~20 KB) so tools and agents can read it from site-packages; it's not imported at runtime. Alternative would be `meta/operators.toml` outside the package. Chosen: ship it, cheap and useful for A01.
