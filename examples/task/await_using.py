"""
Example: cleanup when a loop ends early (C#: await foreach / await using)

C#'s `await foreach` always disposes the stream it iterates, however the loop ends:

    await foreach (var row in RowsAsync(10))
    {
        if (row == 3) break;     // RowsAsync's finally blocks run here
    }

Python's `async for` does not close an async generator when the loop is left early.
flpit fills that gap on three levels:

1. **Always**: flpit closes a stream that is left early, right after the loop, so its
   `finally` blocks run even when they await. Nothing to write, but nothing waits for it.
2. **Block scope** (C#: `await using (var e = ...) { }`): `async with
   stream.get_async_enumerator() as rows:` - the stream is closed when the block is left.
3. **Function scope** (C#: `await using var e = ...;`): `@await_using` - every stream the
   function iterated is closed before the function returns.

Use 2 or 3 when the cleanup must be completed before you go on: releasing a connection,
a lock or a semaphore slot, or checking the outcome in a test.
"""

from collections.abc import AsyncGenerator

from flpit import async_flpit
from flpit.task import CancellationToken, Task, await_using


class Connection:
    """A resource that must be released, and releasing it takes I/O."""

    async def close(self) -> None:
        await Task.delay(0.05)  # e.g. tell the server goodbye
        print("  connection closed")


@async_flpit
async def rows(n: int, token: CancellationToken = CancellationToken.none()) -> AsyncGenerator[int]:
    connection = Connection()

    try:
        for i in range(1, n + 1):
            await Task.delay(0.01, token=token)
            yield i

    finally:
        await connection.close()  # must run even if the consumer stops early


async def plain_loop() -> None:
    # 1. Nothing to write: flpit closes the stream after the break.
    async for row in rows(10):
        if row == 3:
            break

    print("plain loop done (the connection closes shortly after)")


async def block_scope() -> None:
    # 2. C#: await using (var items = Rows(10).GetAsyncEnumerator()) { ... }
    async with rows(10).get_async_enumerator() as items:
        async for row in items:
            if row == 3:
                break

    print("block done (the connection is already closed)")


@await_using  # 3. C#: await using var items = ...;
async def function_scope() -> None:
    async for row in rows(10):
        if row == 3:
            break

    print("function body done (the connection may still be closing)")
    # ... but it is closed before function_scope() returns


async def main() -> None:
    await plain_loop()
    await Task.delay(0.1)  # let the background close finish, to keep the output in order

    print()
    await block_scope()

    print()
    await function_scope()
    print("function returned (the connection is closed)")


if __name__ == "__main__":
    Task.run(main).result()
