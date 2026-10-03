---
id: A01
title: Agent skill (SKILL.md + generated references)
status: todo
priority: 010
effort: M
depends_on: [F06]
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# A01: Agent skill `flpit`

## 1. Goal
Coding agents should (a) **find** flpit when it fits (a project depends on it, or the user writes LINQ-style or iterable-heavy Python, or translates C#), and (b) **use it efficiently**, in two senses:
- **token-efficient for the agent**: a short SKILL.md with progressive disclosure into grep-able generated references, so the agent loads one line per operator, not the source;
- **runtime-efficient code**: pick the cheapest correct operator, respect lazy/terminal boundaries, avoid accidental re-enumeration of one-shot sources.

The references are **generated from the registry and docstrings** (F06), so they cannot drift from the code (D13).

## 2. Scope
**In** (files live where the plugin will ship them, A02):
```
plugins/flpit/skills/flpit/
  SKILL.md                          # hand-written, < 200 lines
  references/
    operators.md                    # GENERATED: one block per operator (signature, 1-line doc, kind, since)
    translation-map.md              # GENERATED: C# LINQ / MoreLINQ / itertools / comprehension → flpit
    semantics.md                    # hand-written: lazy vs terminal, re-iteration, buffering, errors
    performance.md                  # hand-written: efficient patterns + anti-patterns (with bench evidence)
    recipes.md                      # hand-written: 10–15 task recipes (paging, group+aggregate, joins, windows)
  scripts/
    list_operators.py               # prints operators available in the INSTALLED flpit (reads shipped registry)
```
- `gen_docs.py` (F06) gets two new targets: `operators.md`, `translation-map.md`.
- Registry fields added: `cs_example` (C# one-liner), `py_example` (flpit one-liner), and `idioms` (list of equivalent Python/itertools expressions), used by the translation map.
- An eval suite for the skill (run manually / on demand, see §4).

**Out:** plugin packaging and marketplace (A02); MCP server; slash commands (not chosen); llms.txt (not chosen).

## 3. Detailed design
### 3.1 SKILL.md (outline)
```markdown
---
name: flpit
description: >-
  Write, refactor or review Python that queries iterables with flpit (fluent LINQ for Python):
  filter/map/group/join/order/aggregate pipelines, C# LINQ or MoreLINQ ports, or replacing nested
  comprehensions/itertools chains. Use when pyproject/requirements list flpit, code imports flpit,
  or the user asks for LINQ-style Python.
---
# flpit
## Detect & install
- Present if `flpit` is in pyproject/requirements or `import flpit` appears. Otherwise suggest
  `uv add flpit` only when the user wants LINQ-style code; never add a dependency silently.
- Installed version: `python -c "import flpit; print(flpit.__version__)"`.
  Operators available in that version: `python ${CLAUDE_SKILL_DIR}/scripts/list_operators.py [--grep NAME]`.
## Import idiom
`from flpit import flp` → `flp.it(iterable)` (lazy), `flp.lst(iterable)` (materialised), factories `flp.range/repeat/empty/...`.
Never `import flp` (deprecated namespace).
## Core rules (the 8 that matter)
1. Intermediate ops are lazy; nothing runs until iteration or a terminal (`to_list`, `first`, `count`, `any`...).
2. A generator source is one-shot: materialise with `.to_list()` once if you need two passes.
3. Prefer short-circuit terminals: `any()` not `count() > 0`; `first()` not `to_list()[0]`; `contains(x)` not `x in to_list()`.
4. `count()` is LINQ count (all or predicate), not `list.count(value)`.
5. `order_by/group_by/reverse/...` buffer the whole input at enumeration; put `where` before them.
6. `*_or_default(..., default=...)` instead of try/except around `first()`.
7. Comparers don't exist; use `*_by(key)` variants.
8. Indexed callbacks use `_indexed` methods: `where_indexed(lambda x, i: ...)`.
## Looking things up (load on demand)
- Operator signatures: grep `references/operators.md` for `### <name>`.
- Translating C#/MoreLINQ/itertools: grep `references/translation-map.md` for the source name.
- Semantics questions: `references/semantics.md`; performance: `references/performance.md`; patterns: `references/recipes.md`.
## Don'ts
- Don't wrap a `FlpList` in `flp.it()` (already queryable); don't call `to_list()` mid-pipeline "to be safe".
- Don't rely on `FlpList` being a `list` (`isinstance(x, list)` is False; use `list(x)` at API boundaries).
```
### 3.2 Generated `operators.md` format (grep-friendly, ~4 lines per op)
```markdown
### skip
`skip(count: int) -> FlpIt[T]` · partitioning · deferred/streaming · since 0.3.0 · .NET `Skip`
Bypasses a specified number of elements and returns the remaining elements.
e.g. `flp.it(range(5)).skip(2).to_list()  # [2, 3, 4]`
```
Signatures come from `inspect.signature` with overloads rendered from `typing.get_overloads` (3.11+), first doc line and example from the docstring, metadata from the registry. Planned operators are **excluded** (agents must not hallucinate unreleased APIs); `since` lets the agent compare with the installed version.

### 3.3 Generated `translation-map.md`
Sections: "From C# LINQ", "From MoreLINQ", "From itertools/builtins/comprehensions". Rows: `source form → flpit form → note` (e.g. `xs.Where(x => x > 0).Select(x => x * 2).ToList()` → `flp.it(xs).where(lambda x: x > 0).select(lambda x: x * 2).to_list()`; `itertools.pairwise(xs)` → `.pairwise()`; `sorted(xs, key=k)[:n]` → `.partial_sort_by(n, k)`).

### 3.4 `list_operators.py`
Reads `importlib.resources.files("flpit") / "_operators.toml"` from the **installed** package, so it's version-correct even when the skill is newer than the user's flpit. Falls back to `dir(flpit.FlpIt)` for pre-registry versions (< 0.3.0).

### 3.5 Staleness gate
`gen_docs.py --check` (already in CI lint) covers the two generated files; a test asserts every implemented operator appears in `operators.md` and SKILL.md stays < 200 lines.

## 4. Tests
- `tests/unit/test_skill_files.py`: frontmatter parses; `name` == directory; description ≤ 1024 chars; every relative link in SKILL.md resolves; `list_operators.py --grep skip` prints the skip line against the dev install.
- **Eval suite** (`plugins/flpit/evals/`, format of `claude plugin eval`), ablation with/without the plugin:
  1. `translate-csharp`: port a 6-operator C# LINQ query; graders: regex (`from flpit import flp`, `.where(`, no `import flp\b`), llm (semantic equivalence, lazy until terminal).
  2. `refactor-comprehension`: nested comprehension + `sorted` + `groupby` → flpit pipeline; llm grader checks no extra materialisation.
  3. `efficient-terminal`: task naturally tempting `count() > 0` / `to_list()[0]`; regex grader requires `any(` / `first(`.
  4. `one-shot-trap`: pipeline over a generator used twice; llm grader requires a single `to_list()` or re-creation.
  5. `no-dependency-added`: project without flpit, plain Python task; grader: `pyproject.toml` unchanged.
  Target: with-plugin pass rate ≥ 0.8 and a positive Δ vs without on cases 1–4; case 5 must pass in both arms.
- Evals are billable, so they run via `workflow_dispatch` (`.github/workflows/plugin-eval.yml`, secret `ANTHROPIC_API_KEY`, `--max-cost-usd 10`, `--no-publish`, `--json`) and before each release that changes the skill, **not** on every PR.

## 5. Differential harness
n/a

## 6. Benchmarks
`performance.md` cites ratios from the F07 history for its claims (e.g. "any() vs count()>0 on 1e5 items: 10⁴× fewer pulls"). Claims without a benchmark are not allowed.

## 7. Docs
README "Using flpit with AI coding agents" → install instructions (A02) + what the skill does.

## 8. Expected outcomes
- An agent with the skill writes idiomatic, lazy-correct flpit code on first try in ≥ 80 % of eval runs.
- References are generated and therefore always in sync; SKILL.md stays small (fast to load, cheap in tokens).

## 9. Verification
```bash
uv run python scripts/gen_docs.py --check
uv run pytest -q tests/unit/test_skill_files.py
uv run python plugins/flpit/skills/flpit/scripts/list_operators.py --grep skip
wc -l plugins/flpit/skills/flpit/SKILL.md            # < 200
claude plugin eval plugins/flpit --runs 3 --no-publish --json /tmp/eval.json --threshold 0.8
```

## 10. Definition of Done
- [ ] SKILL.md + hand-written references; generated references via gen_docs
- [ ] list_operators.py (installed-version aware)
- [ ] Skill file tests; staleness gate
- [ ] Eval suite (5 cases) + manual workflow; first run results (pass rates, Δ) in the PR
- [ ] README section

## 11. Risks / open questions
- Skill-vs-installed version skew: handled by `since` + `list_operators.py`.
- Description wording drives triggering; iterate using eval results (case 5 guards against over-triggering).
- Portability: SKILL.md uses only `name`/`description` frontmatter plus plain Markdown, so the same folder works for other agents that read skill folders (no Claude-only frontmatter is required for correctness; `${CLAUDE_SKILL_DIR}` is the only Claude-specific token and has a relative-path fallback in the text).
