# What "LINQ semantics" means

Matching LINQ is more than matching method names. For every operator FlpIt implements, the following should
be the same as in .NET's `System.Linq.Enumerable`:

- **When work happens.** Building a query reads nothing; enumeration does the work.
- **How much is read.** Operators such as `first`, `any`, `single` and `take` stop as soon as the answer is known.
- **What comes out.** Results, their order, and how equal keys are treated.
- **How it fails.** The exception that is raised, and the hierarchy it belongs to.
- **How it composes.** All of the above must still hold when operators are chained, and queries derived from
  one another must not interfere.

The next pages show each of these as running code:

- [The contract](contract.md): one behaviour at a time.
- [Chaining](chaining.md): the same behaviours across composed queries.
- [Verification](verification.md): how closeness to .NET is checked.

!!! note
    FlpIt is under active development, and the semantic goal is stated as a goal. If you find a behaviour
    that differs from .NET LINQ, please [open an issue](https://github.com/riemar/flpit/issues).
