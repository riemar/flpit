## 1. Mission

Build a **private, extensible differential-testing system** for a Python implementation of .NET LINQ.

The purpose is not merely to test that each operator returns plausible values. The goal is to determine whether the Python implementation matches the **observable behavior of modern .NET LINQ** as closely as Python reasonably allows.

Use the **current .NET LTS** as the behavioral oracle. Do not spend test capacity maintaining separate .NET 8/9/10 expected behaviors unless a real compatibility difference is discovered later.

The system must be designed so that:

- every implemented operator is covered,
- new operators are cheap to add to the test surface,
- individual operator tests and compositions are both exercised,
- deterministic regression tests coexist with generated/property-based tests,
- failures are reproducible from a seed and test-case ID,
- semantic differences are classified rather than hidden,
- genuinely incomparable .NET/Python cases are explicitly skipped/classified,
- the harness itself is reusable and maintainable.

This is a **private verification suite initially**, not a public testing package.

---

## 2. Core philosophy

### 2.1 Oracle principle

.NET LINQ is the behavioral oracle.

Do not make the Python implementation the source of truth for what "correct" means.

For each comparable scenario:

```text
Generated scenario
      |
      +----> .NET LINQ execution
      |
      +----> Python LINQ execution
      |
      v
Normalized observable result
      |
      v
Strict comparison
```
When the two implementations disagree:

reproduce exactly,
classify the discrepancy,
determine whether the Python behavior is wrong,
add a permanent regression test when appropriate.
2.2 Observable semantics over internal implementation

Do not require the Python implementation to copy .NET's internal classes or algorithms.

The target is observable behavior:

returned values,
element order,
duplicate behavior,
laziness/deferred execution,
enumeration timing,
repeated enumeration,
source consumption,
side-effect timing,
exceptions,
mutation visibility where applicable,
default-value behavior,
equality/comparison semantics,
grouping behavior,
materialization/persistence behavior when externally observable.

Implementation architecture can differ as long as observable behavior matches.

2.3 Never weaken the oracle to make tests pass

Do not normalize away meaningful differences merely because they are inconvenient.

Do not:

sort results unless the operator is explicitly unordered,
ignore side effects,
ignore enumeration count,
turn lazy execution into eager execution in the test oracle,
discard exception-message differences merely because exception types differ,
silently remove hard cases,
compare only final values when execution behavior is part of the semantics.

Instead classify cases honestly.

3. Scope
3.1 What is tested

Test only operators actually implemented by the Python project.

Maintain an explicit operator registry/manifest containing at minimum:

operator name
Python API
.NET equivalent
operator category
argument schema
result shape
supported comparability levels
test generator
normalizer/comparator
known intentional differences

The design must make adding a new operator straightforward.

When a new operator is implemented in the Python library, adding its differential tests should ideally require:

adding one operator specification,
adding or reusing argument generators,
adding any required semantic probes,
enabling composition participation.

Avoid scattered hand-written special cases.

3.2 What is not automatically tested

Do not attempt to force equivalence where the languages/runtime models fundamentally differ.

Cases may be classified as:

MATCH
MISMATCH
EXPECTED_DIFFERENCE
UNCOMPARABLE
INVALID_TEST_CASE
ORACLE_ERROR
PYTHON_ERROR
HARNESS_ERROR

UNCOMPARABLE must mean genuinely unrepresentable or semantically ambiguous, not merely "difficult to implement."

4. Strictness model

Testing should progress from simple/direct comparisons toward increasingly difficult semantics.

Level 1 — Basic values

Use portable scalar data:

integers
strings
booleans
empty sequences
repeated values
negative values
small numeric ranges

Verify:

output values,
order,
cardinality,
duplicates.
Level 2 — Boundaries

Test:

empty source,
singleton source,
all matching,
none matching,
first matching,
last matching,
duplicate keys,
duplicate elements,
zero,
one,
negative indexes where applicable,
index equal to count,
large/small take/skip,
default cases.
Level 3 — Functions

Test:

predicates,
selectors,
key selectors,
result selectors,
indexed overloads where available,
stateful functions,
functions with side effects,
functions that raise.
Level 4 — Deferred execution

Test exactly when work happens.

Examples:

constructing a query must not eagerly consume a deferred source when .NET does not,
predicate/selector invocation should occur at the same observable point,
ToList/materialization should force execution at the equivalent point,
exceptions should occur at equivalent execution time where comparable.
Level 5 — Re-enumeration

Explicitly test:

enumerate once
enumerate again
call an operator
enumerate again
combine operations that enumerate the source multiple times

Distinguish:

the query object being re-enumerable,
the source itself being one-shot,
returned groupings being re-enumerable/persistent.

Do not accidentally treat Python generators as equivalent to a re-iterable .NET IEnumerable<T>.

Level 6 — One-shot sources

Create special source probes representing Python one-shot iteration.

Verify how the Python library behaves relative to the intended .NET scenario.

Where the source models cannot be made equivalent, record the limitation explicitly rather than manufacturing equivalence.

Level 7 — Side effects and enumeration counts

Use instrumented sources and callbacks.

Observe:

how many times the source is enumerated,
how many elements are requested,
callback invocation counts,
callback order,
timing of callback side effects.

Examples:

first -> should stop early
any(predicate) -> should stop at first match
element_at(n) -> should not consume beyond n when .NET does not
count -> may consume full sequence
to_list -> consumes full sequence

This dimension is critical.

Level 8 — Equality/comparers

Introduce .NET-style comparer semantics progressively.

Start with simple equality.

Then test explicit/custom comparers where a meaningful Python equivalent can be constructed.

The intended model is:

create the arguments and comparison behavior as .NET does, then expose an equivalent behavior to Python where possible.

Do not skip comparer coverage just because Python's equality protocol differs.

Level 9 — Complex objects/reference semantics

Introduce structured objects and test:

value equality,
object identity where observable,
mutable objects,
keys,
duplicate references,
projection to objects.

Only compare semantics that can be represented reliably in both runtimes.

Level 10 — Operator compositions

Composition is mandatory.

Do not stop at isolated operator correctness.

Generate combinations such as:

Where -> Select
Select -> Where
Where -> OrderBy -> Take
GroupBy -> Select
GroupBy -> SelectMany
SelectMany -> Where
OrderBy -> ThenBy -> Select
Distinct -> Where -> Take
Skip -> Take -> Select
...

The exact composition space should be generated from operator metadata and validity constraints.

Level 11 — Generated/fuzzed compositions

Use property-based generation to create large numbers of:

input sequences,
predicates/selectors,
operator arguments,
operator chains.

The generator must understand argument/result shape so that it does not produce meaningless invalid pipelines.

Level 12 — Inherently incomparable cases

When a .NET concept cannot be represented faithfully in Python:

identify why,
classify as UNCOMPARABLE,
record the reason,
do not silently omit it,
do not convert it into a weaker comparison.
5. Test architecture

Recommended architecture:
```
tests/
  harness/
    models.py
    registry.py
    generators.py
    scenarios.py
    serialization.py
    comparator.py
    normalization.py
    runner.py
    probes.py
    classifications.py

  operators/
    test_<operator>.py

  compositions/
    test_generated_compositions.py

  regression/
    test_known_discrepancies.py

dotnet_oracle/
  Oracle.sln
  Oracle.csproj
  Program.cs
```

Possible conceptual modules:

models.py

Define structured representations for:

test case,
source specification,
operator invocation,
pipeline,
expected result,
observed result,
failure,
execution trace.
registry.py

One authoritative operator registry.

Example conceptual entry:
```
OperatorSpec(
    name="where",
    python_method="where",
    dotnet_method="Where",
    argument_generators=[...],
    result_shape="sequence",
    supports_indexed=True,
    comparison_profile="sequence",
    composition_input_types=[...],
    composition_output_types=[...],
)
```
Do not duplicate operator metadata throughout the test suite.

generators.py

Contains reusable generators for:

scalar values,
sequences,
keys,
predicates,
selectors,
comparers,
indexes,
operator arguments,
operator chains.
probes.py

Special instrumentation for semantic behavior:

counting iterable,
logging iterable,
side-effect callbacks,
exception callbacks,
mutation-aware objects,
repeatability probes,
one-shot sources.
comparator.py

Compare normalized .NET/Python observations.

It must understand the operator's comparison profile.

regression/

Every meaningful discovered discrepancy should become a permanent deterministic test.

6. .NET oracle protocol

Use a separate .NET executable as the oracle.

Preferred architecture:
```
Python test harness
        |
        | JSON Lines
        v
.NET oracle executable
        |
        v
System.Linq
        |
        v
JSON Lines result
```

Use a structured protocol, preferably JSONL, rather than scraping console text.

6.1 Input

Each request should contain a fully serialized test scenario.

Conceptually:
```
{
  "case_id": "where-basic-001",
  "seed": 12345,
  "operator": "...",
  "source": [...],
  "arguments": {...},
  "pipeline": [...],
  "probes": {...}
}
```
6.2 Output

Return structured observations, for example:
```
{
  "case_id": "where-basic-001",
  "status": "ok",
  "result": [...],
  "exception": null,
  "trace": {
    "source_enumerations": 1,
    "source_items_requested": 4,
    "callback_invocations": 4
  }
}
```
Do not require every field for every operator, but design the schema so execution semantics can be captured.

7. Serialization and data model

Create a portable test domain first.

Prefer types that have faithful representations on both sides:

null / None where semantically appropriate
bool
integer
string
small structured records
lists / sequences
objects with explicit fields

Use tagged representations where necessary.

Example concept:
```
{"type": "int", "value": 3}
{"type": "string", "value": "abc"}
{"type": "record", "fields": {"id": 1, "name": "A"}}
```
Do not let serialization accidentally erase distinctions relevant to LINQ semantics.

For object/reference tests, the protocol may need explicit object IDs:
```
{
  "object_id": "o17",
  "value": {...}
}
```

This allows identity/reference behavior to be observed when appropriate.

8. Result normalization

Normalization must be operator-aware.

Ordered operators

Compare exact sequence:

[element0, element1, ...]
Unordered operators

Only treat output as unordered when .NET semantics genuinely permit arbitrary ordering.

Never sort an ordered result merely to hide a mismatch.

Grouping

Compare:
```
group keys,
group order where defined/observable,
members,
member order where defined,
repeatability of returned groups.
Sets/distinct-like operations
```
Compare according to .NET's actual ordering semantics, not Python set behavior.

Floating-point / unusual values

Define explicit rules before enabling such cases.

Do not accidentally use Python serialization behavior as the semantic definition.

9. Exception comparison

Exceptions are observable output.

Capture at least:

whether an exception occurred,
exception type,
exception message,
execution timing where applicable.

Priority:

behavior must agree,
message should match where meaningful,
type is a soft/secondary comparison dimension because .NET and Python exception taxonomies differ.

Suggested classification:

EXACT_EXCEPTION_MATCH
MESSAGE_MATCH_TYPE_DIFF
TYPE_MATCH_MESSAGE_DIFF
EXPECTED_EXCEPTION_MAPPING
UNCOMPARABLE_EXCEPTION
MISMATCH

Do not silently collapse all Python exceptions into "an error occurred."

10. Execution trace model

A major objective is to compare how a query executes, not only what it returns.

Possible trace fields:
```
source enumeration count
source item request count
source item values observed
predicate call count
predicate call order
selector call count
selector call order
key selector call count
callback side effects
exception timing
materialization point
second enumeration behavior
```
Not every operator needs every trace field.

The test harness should probe only what is semantically meaningful.

11. Repeatability model

Explicitly distinguish:

Re-iterable source

Equivalent conceptual behavior:

[1, 2, 3]
One-shot source

Equivalent conceptual behavior:

iter([1, 2, 3])

The test system must know which kind of source is being modeled.

Do not accidentally write all tests against lists and conclude the implementation matches .NET iteration semantics.

12. Property-based testing

Use Hypothesis when practical.

The property is not simply:

python_result == expected_result

The core property is:

run_same_scenario_in_.NET_and_Python
        =>
observable_behaviors_are_equivalent

Generate:

source data,
operator arguments,
predicates/selectors,
comparer configurations,
valid operator compositions,
execution probes.

Every generated case must have a reproducible seed/case identity.

Record enough information to recreate a failing example exactly.

13. Composition generator

Operator metadata must support composition.

Each operator should declare conceptual input/output shape, for example:

sequence[T] -> sequence[T]
sequence[T] -> sequence[U]
sequence[T] -> scalar
sequence[T] -> grouping sequence

The composition generator uses those shapes to build valid pipelines.

Example:

source
 -> Where
 -> Select
 -> OrderBy
 -> Take
 -> ToList

Avoid generating only random names. Generate semantically valid pipelines.

Composition dimensions should include:

short chains: 2–3 operators,
medium chains: 4–6,
long chains: 7+,
repeated operators,
materializing operators,
branching/reused queries where possible,
operators that enumerate more than once.
14. Deterministic test corpus

Maintain a deliberate corpus covering:

Input shapes
empty
one
two
many
all equal
all different
alternating
sorted
reverse sorted
duplicates
negative values
mixed values
strings
null-like values where representable
Execution shapes
list / re-iterable source
one-shot iterator
instrumented source
source with side effects
source that throws
Callback shapes
always true
always false
first only
last only
multiple matches
never matches
stateful callback
callback with side effect
callback that throws
Composition shapes

At minimum include:

projection before filter
filter before projection
ordering before projection
projection before ordering
grouping before projection
grouping followed by flattening
set operator followed by filtering
pagination chains
materialization boundaries
15. Regression strategy

Every discovered semantic discrepancy should have:

case ID
operator/pipeline
source
arguments
seed
.NET observed result
Python observed result
classification
root cause
expected status

Once understood, move the case into permanent regression coverage.

Do not delete a regression merely because the implementation was fixed.

16. Coverage model

Do not judge completeness by raw test count alone.

Track coverage across these dimensions:

operator coverage
overload coverage
argument-shape coverage
boundary coverage
exception coverage
ordering coverage
duplicate coverage
deferred-execution coverage
re-enumeration coverage
one-shot-source coverage
side-effect coverage
enumeration-count coverage
comparer coverage
object/reference coverage
composition coverage
generated-case coverage
regression coverage

Produce a machine-readable coverage report.

Example:

Operators implemented: 31
Operators with deterministic tests: 31
Operators with generated tests: 29
Composition-enabled operators: 31
Execution-semantics probes: 24
Comparer-aware operators: 11
Known intentional differences: 3
Uncomparable scenarios: 7
Open mismatches: 0

The numbers above are examples only.

17. Test volume goals

Do not optimize for a fixed number of handwritten tests.

A reasonable target is:

Tier A — deterministic semantic corpus

Approximately:

1,500–4,000+ deliberately designed cases

depending on the operator surface.

Tier B — property-based generation

At least:

50,000+ generated cases

per substantial run, increasing toward hundreds of thousands as the harness stabilizes.

Tier C — composition fuzzing

Tens of thousands of generated valid operator pipelines.

Tier D — regression suite

All historically discovered bugs and semantic mismatches.

The system should make it cheap to increase generated-case volume without increasing code size proportionally.

18. Reproducibility

Every generated case must be reproducible.

Minimum identifying information:

seed
case ID
generator version
operator/pipeline description
serialized input
serialized arguments

A failing fuzz case must be promotable to a deterministic regression case.

Example:

FAILED CASE
seed=918273
case=composition-18429
generator=v7

Running that exact case again must reproduce the discrepancy unless the underlying implementation or oracle has changed.

19. Failure analysis pipeline

When a case fails:

1. Re-run Python alone
2. Re-run .NET oracle alone
3. Compare raw observations
4. Compare normalized observations
5. Inspect execution trace
6. Determine whether mismatch is:
   - Python bug
   - oracle/test bug
   - harness bug
   - intentional semantic difference
   - incomparable case
7. Create regression test if meaningful

Do not immediately change expected output.

20. Important semantic traps

The harness must specifically guard against these common mistakes:

Generator/iterator confusion

Python iterators are commonly one-shot; .NET IEnumerable<T> is generally an abstraction that can return a fresh enumerator each time.

Grouping semantics

A returned .NET grouping is normally independently enumerable and retains its grouped elements.

Deferred execution

Creating a query is often lazy. Enumeration can trigger work later.

Repeated enumeration

A query can be enumerated multiple times. The source itself may or may not support this depending on how it was created.

Short-circuit operators

Operators such as:

Any
All
First
FirstOrDefault
Single
SingleOrDefault
ElementAt
Take
Contains

can have important consumption/termination behavior.

Ordering

LINQ often has explicit ordering guarantees. Do not treat everything as a set.

Stable ordering

Where .NET preserves relative ordering among equal keys, test it.

Materialization boundaries

ToList, ToArray, and related operators can turn deferred execution into persistent data.

Set operators

Distinct, Except, Intersect, Union, etc. have semantics beyond Python set.

GroupBy

Do not reduce GroupBy to a Python dictionary comparison. Test grouping order, element order, key semantics, and repeatability.

Join operations

Test matching, duplicate matches, ordering, comparer behavior, and empty sides.

21. Operator implementation strategy

Do not start by generating thousands of cases.

First:

inspect the provided Python implementation,
build an operator inventory,
identify overloads,
identify operators that require special execution probes,
define the portable data model,
build the .NET oracle,
establish a small trusted deterministic suite,
verify the harness itself,
then scale generated testing.

The harness must be trustworthy before the test count becomes large.

22. Validation of the harness itself

A differential harness can be wrong.

Therefore introduce harness self-tests.

Examples:

intentionally mutate expected Python behavior and verify the harness detects it,
intentionally alter the .NET oracle serialization and verify the harness reports it,
test ordering comparison with deliberately reordered sequences,
test exception comparison with different messages,
test enumeration counters with known cases,
test seeded generation for deterministic replay.

Do not trust green results until the harness has demonstrated that it can detect planted defects.

23. Suggested workflow
Phase 1 — Inspect implementation

Input: relevant Python source provided by the user.

Produce:

operator inventory,
supported overloads,
type/shape model,
known execution architecture,
obvious semantic risk areas.
Phase 2 — Build oracle

Create the .NET LTS console application.

Implement:

scenario decoding,
LINQ execution,
result serialization,
exception serialization,
execution probes.
Phase 3 — Basic differential suite

Start with:

scalar sequences,
straightforward arguments,
direct result comparison.

Goal: prove that the end-to-end pipeline works.

Phase 4 — Semantic probes

Add:

deferred execution,
enumeration counts,
re-enumeration,
one-shot sources,
side effects,
exceptions.
Phase 5 — Property generation

Add Hypothesis strategies.

Phase 6 — Composition generation

Add valid operator chains.

Phase 7 — Scale

Increase generated cases toward:

50k
100k
250k
500k+

depending on runtime and signal quality.

Phase 8 — Regressionization

Promote every meaningful discrepancy to deterministic regression coverage.

Phase 9 — Coverage report

Produce an explicit report showing:

what is covered,
what is not,
what is incomparable,
what still mismatches.
24. Definition of "verified"

Do not claim:

"The LINQ implementation is bug-free."

Use a more defensible statement:

"The implementation has been differentially tested against the current .NET LTS LINQ behavior across the documented comparable test domain, including deterministic edge cases, execution semantics, property-generated inputs, and operator compositions. Remaining differences are explicitly classified."

"Verified" means:

no unexplained differential mismatches in the executed corpus,
no known failing regression cases,
sufficient operator and semantic coverage,
harness self-tests pass,
generated failures are reproducible,
incomparable cases are documented.
25. Agent operating rules

When executing this specification:

Do
inspect source before assuming APIs,
derive the operator inventory from the actual implementation,
reuse generator infrastructure,
prefer data-driven tests,
make failures reproducible,
preserve failing seeds,
test semantics, not just outputs,
add regression tests for discovered bugs,
report uncertainty explicitly,
distinguish harness failures from implementation failures.
Do not
invent unsupported operators,
silently skip difficult cases,
treat every sequence as a Python list,
compare unordered values by sorting unless justified,
normalize away meaningful differences,
equate "no exception" with correctness,
declare success because a small sample passes,
claim exhaustive correctness from finite testing,
hard-code thousands of nearly identical tests when generation can express the same coverage.
26. Final deliverables

The finished private test system should provide:

Source
Python differential harness
.NET oracle
operator registry
data generators
composition generator
execution probes
comparators
regression corpus
Commands

At minimum, provide commands conceptually equivalent to:

# small deterministic verification
pytest tests/differential -m smoke

# full deterministic suite
pytest tests/differential

# generated differential run
pytest tests/differential -m generated

# larger fuzz run
pytest tests/differential -m fuzz

# reproduce one failure
pytest tests/regression/test_case_<id>.py

Exact command structure may differ according to the actual repository.

Reports

Produce:

operator coverage
semantic coverage
generated-case counts
match/mismatch counts
uncomparable counts
regression status
reproducible failing cases
27. Current project decisions

These are already decided and should not be re-litigated unless new evidence requires it:

Target:
    Python LINQ implementation currently being developed locally.

Oracle:
    Current .NET LTS System.Linq.

Test scope:
    Only operators currently implemented by the Python project.

Compatibility:
    Strict observable-semantic compatibility.

Exception handling:
    Exception behavior is tested.
    Message equivalence is important.
    Exception type is a soft/secondary dimension because runtime taxonomies differ.

Hard cases:
    Work from easy -> hard -> inherently incomparable.
    Do not force incomparable cases into fake equivalence.

Property-based testing:
    Yes, use Hypothesis where practical.

Oracle transport:
    Separate .NET executable communicating through a structured protocol, preferably JSON Lines.

Reproducibility:
    Mandatory seed + case ID + serialized scenario.

Compositions:
    Mandatory and first-class.

Testing status:
    Private verification suite initially.

Scalability:
    Prefer generators and metadata over thousands of manually duplicated tests.

Primary objective:
    Find semantic mismatches that ordinary example-based unit tests are likely to miss.
28. First task for a fresh agent

Do not immediately generate thousands of tests.

First inspect the provided Python code and produce:

the implemented LINQ operator inventory,
the required operator metadata schema,
the portable data-domain proposal,
the first-pass .NET oracle protocol,
the execution-semantic probes needed by this specific implementation,
the initial deterministic test matrix,
any semantic ambiguities that must be resolved from the implementation.

Then build the smallest end-to-end differential slice:

one operator
    +
.NET oracle
    +
Python runner
    +
structured comparison
    +
one execution probe
    +
one deterministic regression test

Only after that slice is demonstrated to work should the harness expand across the full operator surface.

29. Guiding principle

The project is not trying to prove that the Python implementation is "reasonable."

It is trying to answer a much stronger question:

For every behavior we claim to support, does the Python implementation behave observably like .NET LINQ on the same scenario?

Build the test infrastructure around that question.
"""

path = Path("/mnt/data/linq_differential_test_harness_master_context.md")
path.write_text(content, encoding="utf-8")

print(path)