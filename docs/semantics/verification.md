# Verification

How closeness to .NET LINQ is checked, from the broadest evidence to the most specific.

## 1. Migrated .NET runtime tests

The .NET runtime's own LINQ tests are migrated to Python and run against both core types, `FlpIt` and
`FlpList`. Together with the migrated tests for async queries, channels, concurrent collections and threading,
that is more than 10,000 test cases; the per-module breakdown is in the
[README](https://github.com/riemar/flpit#migrated-net-unit-tests). The tests live in
[`tests/nettests/`](https://github.com/riemar/flpit/tree/main/tests/nettests).

Where the .NET tests use `RunOnce()` to model a one-shot source, the migrated tests use a one-shot generator.

## 2. The .NET oracle (in development)

Per-operator tests can't cover every composition. A .NET oracle is being built to extend the check beyond the
migrated tests, so that behavioural equality with `System.Linq` can be checked on generated pipelines as well.
This page will describe its scope and results once it is running.

## 3. Executable documentation

Every snippet in these docs is a real file under
[`examples/`](https://github.com/riemar/flpit/tree/main/examples), and `tests/test_examples.py` runs all of
them in CI. The [contract](contract.md) and [chaining](chaining.md) pages are therefore tests as well as
explanation.
