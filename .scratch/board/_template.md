---
id: XNN
title: <operator or task>
status: todo            # todo | doing | review | done | dropped
priority: NNN           # matches file prefix
effort: S               # S | M | L
depends_on: [F05, F06, F08, F09]
upstream:
  dotnet: <File>Tests.cs @ dotnet/runtime main (<n> [Fact]/[Theory])   # or n/a
  morelinq: <Name>.cs (reference only, D7)                              # or n/a
pr: <link once opened>
---

# XNN: <title>

## 1. Goal
One paragraph: what the user gains and why now (priority rationale).

## 2. Scope
**In:** methods, overloads, variations, and which classes (FlpIt via `_LinqOps`; FlpList fast path?).
**Out:** what is explicitly not done, and why.

## 3. Detailed design
### 3.1 Signatures
```python
# exact overloads with typing
```
### 3.2 Semantics
- Kind: intermediate (deferred) | terminal | factory
- Buffering: streaming | partial (bounded buffer of size k) | full
- Short-circuit: when enumeration stops
- Argument validation (eager): which errors, which messages
- Edge cases: empty, None elements, negative/zero/huge counts, one-shot source, re-enumeration
- Exceptions raised during enumeration
### 3.3 Implementation sketch
Pseudo-code / algorithm, complexity (time and memory), FlpList / Sequence fast paths and why they are observationally equivalent.
### 3.4 Registry entry (`src/flpit/_operators.toml`)
```toml
[operators.<name>]
...
```

## 4. Tests
- Ported: `tests/nettests/test_<op>.py` from `<File>Tests.cs` (count; expected skips by category).
- Own unit tests: bullet list of behaviours.
- Contracts: auto (registry) + any operator-specific invariants.
- Typing: `tests/typing/test_types_<op>.py` checks.

## 5. Differential harness
`difftest/specs/<op>.toml`: arg domains, probes, expected classifications.

## 6. Benchmarks
Cases, native baseline code, target ratio.

## 7. Docs
Docstring outline, README matrix row, deviations (if any), translation-map row.

## 8. Expected outcomes
Observable results once merged.

## 9. Verification
Exact commands (VERIFY-std plus op-specific ones) and the manual checks.

## 10. Definition of Done
DoD-std + card-specific items.

## 11. Risks / open questions
