# AGENTS.md — AI & Contributor Guidelines

## Domain Context: Lightweight Python LINQ Extension
Provide a .NET LINQ-like fluent API as a natural extension of standard Python iterables and collections. Prioritize Python-native iterator semantics, static typing, predictable lazy/eager boundaries, and streaming efficiency without recreating .NET internals.

---

## Execution Semantics & Boundaries

1. **Deferred vs. Terminal Operations:**
   - **Intermediate operations** (`where`, `select`, `select_many`, `take`, `skip`, `distinct`, etc.) MUST return a deferred `FlpIt` or `OrderedIt` without consuming the source or executing eagerly.
   - **Terminal operations** (`to_list`, `first`, `single`, `count`, `any`, `all`, `contains`, etc.) define explicit execution boundaries and MAY consume the source.
   - **Short-circuiting:** Terminal operations MUST stop enumeration as soon as the result is known (e.g., `first` stops after the first element, `any` on the first match, `single` upon detecting a second match).

2. **Single-Use & Replayability:**
   - `FlpIt` MUST preserve single-use semantics of its underlying iterable. It MUST NOT introduce implicit caching or replayability.

3. **Buffering & Materialization:**
   - Algorithms requiring state (`order_by`, `group_by`, `join`, `distinct`) MAY buffer internally.
   - **Internal buffering does not constitute an API-level materialization boundary.** Never materialize merely for convenience.

4. **Callbacks & Exceptions:**
   - User callbacks (predicates, selectors, key-selectors) MUST execute lazily during iteration.
   - Exceptions must propagate naturally without being swallowed.

---

## Architecture & Data Structures

- **`FlpList[TItem]`:** Materialized container extending `collections.UserList` and `typing.Sequence`.
- **`FlpIt[TItem]`:** Deferred query implementing `typing.Iterable[TItem]` (not `Sequence`).
- **`OrderedIt[TItem]`:** Subclass of `FlpIt[TItem]`. Stable sorting where `.then_by()` **augments** (rather than replaces) existing ordering.
- **`Grouping[TKey, TItem]`:** Subclass of `FlpIt[TItem]` with a `.key` property.

---

## Typing & Validation

- **Static First:** Generic parameters (`TItem`, `TKey`, `TResult`, `TOther`) rely on static type inference (`mypy`/`pyright`).
- **Runtime Validation:** Use $O(1)$ sample checks only via `.add()` and `.add_range()`. Native mutation methods (`append`, `extend`) remain untouched.
- **`.as_type(T)` Identity Contract:** Must perform no runtime validation, inspection, allocation, copying, wrapping, or transformation. It MUST return `self` exactly (`result is self`).

---

## Performance & Testing Invariants

- **Streaming & Efficiency:** Maximize generator streaming (`yield`) for lazy chain operations; use $O(N + M)$ hash-joins for `.join()`. Avoid duplicate enumeration, redundant wrappers, or per-element runtime type checks.
- **Test Verification:** Tests must verify observable architectural invariants, including:
   - query construction does not consume the source;
   - lazy operations execute only during iteration;
   - single-use iterators remain single-use;
   - `.as_type()` returns the exact same object (`result is self`);
   - short-circuiting terminal operations stop when their result is known;
   - ordering remains stable and `.then_by()` preserves primary ordering;
   - native `append()` / `extend()` behavior remains unchanged.

---

## Guiding Principle

> **Correctness includes both the returned values and the execution behavior.**