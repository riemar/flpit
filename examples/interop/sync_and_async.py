"""Sync and async functions together, in short.

Lines after each ``end`` marker are not shown in the docs; they check the results in CI.
"""
# --8<-- [start:await_sync]
import time

from flpit.task import Task, task


@task                                      # a plain, blocking function...
def read_report(name: str) -> str:
    time.sleep(0.05)
    return f"report {name}"


async def main() -> list[str]:
    first = await read_report("a")         # ...that you can simply await
    rest = await Task.when_all([read_report("b"), read_report("c")])   # or run side by side
    return [first, *rest]


reports = Task.run(main).result()          # ["report a", "report b", "report c"]
# --8<-- [end:await_sync]
assert reports == ["report a", "report b", "report c"]


import httpx

# Not shown in the docs: keeps this example offline. The delay in the URL is answered locally, in tenths of a second.
httpx.get = lambda url, **kwargs: (time.sleep(int(url.rsplit("/", 1)[1]) / 10), httpx.Response(200, content=url.encode()))[1]

# --8<-- [start:blocking_library]
from flpit import flp
from flpit.task import Task, task

links = [
    "https://httpbin.org/delay/3",         # slowest first
    "https://httpbin.org/delay/2",
    "https://httpbin.org/delay/1",
]


@task
def fetch(url: str) -> tuple[str, bytes]:
    return url, httpx.get(url, timeout=30).content        # plain, blocking httpx


pages = flp.it(links).select(fetch).when_all().result()   # all three at once, in order
# --8<-- [end:blocking_library]
assert [url for url, _ in pages] == links


# --8<-- [start:blocking_stream]
async def crawl() -> None:
    async for done in flp.it(links).select(fetch).when_each():
        url, page = await done             # finished already, just unwrapping
# --8<-- [end:blocking_stream]


Task.run(crawl).result()


# --8<-- [start:blocking_processed]
def parse(result: tuple[str, bytes]) -> tuple[str, int]:
    url, page = result
    return url, len(page)                  # any post-processing, a plain function or an async def


async def crawl_sizes() -> None:
    query = (
        flp.it(links)
        .select(fetch)      # one fetch task per link
        .when_each()        # yield the tasks in the order they finish
        .select_await()     # await each finished task to get its value
        .select(parse)      # post-process the value as it arrives
    )

    async for url, size in query:
        print(url, size)    # first finished, first served
# --8<-- [end:blocking_processed]


Task.run(crawl_sizes).result()


# --8<-- [start:call_async]
from flpit.task import twait


async def double(n: int) -> int:           # an ordinary coroutine function
    await Task.delay(0.01)
    return n * 2


answer = twait >> Task.run(double, 21)     # 42, reads like `await`
same = Task.run(double, 21).result()       # 42, as a method call
# --8<-- [end:call_async]
assert answer == same == 42


# --8<-- [start:query]
from flpit import flp
from flpit.task import CancellationToken


async def is_big(n: int, token: CancellationToken) -> bool:    # an async predicate
    return n > 2


# A plain lambda and an async function in the same query.
query = flp.ait(range(5)).select(lambda n: n * 2).where(is_big)
result = query.to_list().result()          # [4, 6, 8]
# --8<-- [end:query]
assert result == [4, 6, 8]
