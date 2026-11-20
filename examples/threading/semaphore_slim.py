"""
Example: IAsyncEnumerable<Task<T>> with limited parallelism (SemaphoreSlim)

A common .NET pattern: an async iterator that *starts* work and yields the running
tasks, using a SemaphoreSlim so that at most N of them are in flight at once:

    async IAsyncEnumerable<Task<Page>> StartAllAsync(
        IEnumerable<int> ids, SemaphoreSlim throttle,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        foreach (var id in ids)
        {
            await throttle.WaitAsync(ct);         // back-pressure: wait for a free slot
            yield return RunAndReleaseAsync(id);  // started, not awaited
        }

        async Task<Page> RunAndReleaseAsync(int id)
        {
            try { return await FetchAsync(id, ct); }
            finally { throttle.Release(); }       // free the slot, success or failure
        }
    }

    var pending = new List<Task<Page>>();
    await foreach (var task in StartAllAsync(ids, throttle))
        pending.Add(task);
    Page[] pages = await Task.WhenAll(pending);

The same in flpit: an `async def` with `yield` produces `Task[str]` objects, and
`flpit.threading.SemaphoreSlim` limits how many run at a time.

Key takeaways:
1. **Back-pressure**: the producer awaits `throttle.wait_async()` *before* starting
   each task, so iteration pauses while N tasks are running. Nothing is queued up front.
2. **Release in `finally`**: every started task gives its slot back, even when it fails.
3. **Ordered results**: `Task.when_all` returns results in the order the tasks were yielded.
4. **Cancellation**: with `AsyncFlpIt.create`, the enumeration's token reaches the
   producer's `wait_async(token)`: cancelling stops new work from starting, already
   running tasks finish, and no slot is lost.
"""

import random
import sys
import threading
import time
from collections.abc import AsyncGenerator

from flpit import AsyncFlpIt
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task
from flpit.threading import SemaphoreSlim

MAX_PARALLEL = 3


class InFlight:
    """Counts running fetches and remembers the peak, to show the limit holds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self) -> int:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            return self.current

    def exit(self) -> None:
        with self._lock:
            self.current -= 1


in_flight = InFlight()
started_at = time.monotonic()


_print_lock = threading.Lock()


def log(message: str) -> None:
    # Tasks run on several pool threads: write whole lines so output doesn't interleave.
    with _print_lock:
        sys.stdout.write(f"[{time.monotonic() - started_at:5.2f}s] {message}\n")


async def fetch_page(page_id: int, token: CancellationToken) -> str:
    """Stands in for an HTTP call or a database query."""
    running = in_flight.enter()

    try:
        log(f"  start page {page_id:2}  (in flight: {running})")
        await Task.delay(random.uniform(0.1, 0.3), token=token)

        return f"page {page_id}"

    finally:
        in_flight.exit()


async def run_and_release(page_id: int, throttle: SemaphoreSlim, token: CancellationToken) -> str:
    try:
        return await fetch_page(page_id, token)
    finally:
        throttle.release()  # give the slot back, success or failure


async def start_all(
        page_ids: range, throttle: SemaphoreSlim, token: CancellationToken = CancellationToken.none()
) -> AsyncGenerator[Task[str]]:
    """The counterpart of `async IAsyncEnumerable<Task<string>>`: yields tasks that are already running."""
    for page_id in page_ids:
        await throttle.wait_async(token)  # back-pressure: wait for a free slot
        # The token goes to the coroutine, not to Task.run: a task cancelled before it
        # starts would never reach its `finally`, and its slot would be lost.
        yield Task.run(run_and_release, page_id, throttle, token)


async def main() -> None:
    random.seed(7)

    print(f"1) await foreach over IAsyncEnumerable<Task<T>>, at most {MAX_PARALLEL} in flight\n")

    throttle = SemaphoreSlim(MAX_PARALLEL)
    pending: list[Task[str]] = []

    async for task in start_all(range(1, 11), throttle):  # C#: await foreach (var task in ...)
        pending.append(task)

    log(f"all {len(pending)} tasks started, waiting for the rest to finish")

    pages = await Task.when_all(*pending)  # results in yield order

    log(f"done: {pages}")
    log(f"peak in flight: {in_flight.peak} (limit {MAX_PARALLEL})")
    log(f"free slots afterwards: {throttle.current_count}\n")

    print("2) the same producer as an AsyncFlpIt query, cancelled after 0.4s\n")

    throttle = SemaphoreSlim(MAX_PARALLEL)
    query = AsyncFlpIt.create(lambda token: start_all(range(1, 101), throttle, token))

    cts = CancellationTokenSource()
    cts.cancel_after(0.4)
    pending = []

    try:
        async for task in query.with_cancellation(cts.token):
            pending.append(task)
    except OperationCanceledError:
        log(f"cancelled: {len(pending)} of 100 pages were started, no more will be")

    # Tasks that were already running see the same token; their slots come back either way.
    finished = cancelled = 0

    for task in pending:
        try:
            await task
            finished += 1
        except OperationCanceledError:
            cancelled += 1

    log(f"finished: {finished}, cancelled mid-flight: {cancelled}")
    log(f"free slots afterwards: {throttle.current_count} (limit {MAX_PARALLEL}): no slot leaked")


if __name__ == "__main__":
    Task.run(main).result()
