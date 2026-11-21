"""AsyncFlpIt: LINQ over async streams."""
# --8<-- [start:pipeline]
from flpit import async_flpit, flp
from flpit.task import CancellationToken, Task


@async_flpit                                   # C#: async IAsyncEnumerable<int> Pages(...)
async def pages(token: CancellationToken = CancellationToken.none()):
    for page in range(1, 6):
        await Task.delay(0.01, token=token)    # the enumeration's token reaches the producer
        yield page


async def is_odd(page: int, token: CancellationToken) -> bool:   # an async predicate
    return page % 2 == 1


query = pages().where(is_odd).select(lambda page: page * 10)   # nothing has run yet


async def main() -> None:
    async for item in query:                   # C#: await foreach
        assert item in (10, 30, 50)

    assert await query.to_list() == [10, 30, 50]   # terminal operators return a Task
    assert await query.first() == 10


Task.run(main).result()
# --8<-- [end:pipeline]

# --8<-- [start:sync_bridge]
# From synchronous code, block on the Task a terminal operator returns.
assert flp.ait(range(10)).where(lambda x: x % 2 == 0).count().result() == 5
# --8<-- [end:sync_bridge]

# --8<-- [start:cancel]
from flpit.task import CancellationTokenSource, OperationCanceledError


async def cancel_demo() -> None:
    cts = CancellationTokenSource()
    seen = []

    try:
        async for page in pages().with_cancellation(cts.token):
            seen.append(page)
            cts.cancel()                       # the next Task.delay(token=...) in the producer raises
    except OperationCanceledError:
        pass

    assert seen == [1]


Task.run(cancel_demo).result()
# --8<-- [end:cancel]

# --8<-- [start:cleanup]
closed: list[bool] = []


@async_flpit
async def rows():
    try:
        for row in range(10):
            yield row
    finally:
        closed.append(True)                    # e.g. release a connection


async def cleanup_demo() -> None:
    async with rows().get_async_enumerator() as items:   # C#: await using
        async for row in items:
            if row == 3:
                break

    assert closed == [True]                    # the producer's finally block has already run


Task.run(cleanup_demo).result()
# --8<-- [end:cleanup]
