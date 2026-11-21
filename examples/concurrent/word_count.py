"""
Example: counting from many tasks at once (ConcurrentDictionary)

Several workers update one dictionary. A plain `dict` with `counts[word] = counts.get(word, 0) + 1`
loses updates when two threads read the same old value. The .NET answer is an atomic
read-modify-write:

    var counts = new ConcurrentDictionary<string, int>();

    Parallel.ForEach(lines, line =>
    {
        foreach (var word in line.Split(' '))
            counts.AddOrUpdate(word, 1, (_, n) => n + 1);
    });

The same in flpit. Key takeaways:
1. **Atomic updates**: `add_or_update(key, add_value, update)` retries until its update wins.
2. **Lazy values**: `get_or_add(key, factory)` creates a value only for a missing key. A callable
   is the factory because the dictionary knows its value type: create it with its types,
   `ConcurrentDictionary[str, int]()` (or the short `CDict[str, int]()`).
3. **A Python mapping**: `in`, `[key]`, `len()` and iteration (over a snapshot) work as for `dict`.
"""

from flpit.concurrent import ConcurrentDictionary
from flpit.task import Task

LINES = [
    "the quick brown fox",
    "the lazy dog",
    "the quick dog",
] * 1000


def count_words(counts: ConcurrentDictionary[str, int], lines: list[str]) -> None:
    for line in lines:
        for word in line.split():
            counts.add_or_update(word, 1, lambda _, n: n + 1)


def main() -> None:
    counts = ConcurrentDictionary[str, int]()

    chunks = [LINES[i::4] for i in range(4)]  # four workers, one shared dictionary
    Task.wait_all([Task.run(count_words, counts, chunk) for chunk in chunks])

    for word, n in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"{word:>6}: {n}")  # the: 3000, quick: 2000, dog: 2000, ...

    first_seen = ConcurrentDictionary[str, list[int]]()
    positions = first_seen.get_or_add("fox", lambda _: [])  # list values: the lambda is the factory
    positions.append(3)

    print(first_seen)  # ConcurrentDictionary({'fox': [3]})


if __name__ == "__main__":
    main()
