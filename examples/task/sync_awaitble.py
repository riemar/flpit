"""
Example: Making Synchronous Functions Awaitable using @task

This example demonstrates the core philosophy of flpit: converting standard,
blocking synchronous functions into native awaitable tasks without forcing
the developer into single-threaded asyncio loop structures.

Key Takeaways:
1. The @task Decorator: Placed on a standard `def` function, it automatically
   transforms it to return a managed, awaitable `Task`.
   When the function is then invoked it's executed immediately!
   Multiple calls without await will lead to "parallel" execution in so far the GIL allows for it.

2. **Direct Inline Await**: You can invoke and `await` the synchronous function
   directly inside any async context. The runtime offloads the blocking work
   to a native background OS thread seamlessly.

3. **No Cognitive Load**: Write clean, sequential, blocking code for your I/O
   or heavy tasks, and compose them naturally using the `await` keyword.
"""

import time
from flpit.task import task, Task


@task
def compute_heavy_sync_work(task_id: int, duration: float) -> str:
    """A standard, blocking synchronous function performing a heavy operation."""
    print(f"Worker Thread: Starting sync task #{task_id}...")
    time.sleep(duration)  # Standard blocking sleep, completely safe here... until it isn't
    return f"Result from task #{task_id}"


async def main():
    print("Main: Dispatching and awaiting synchronous tasks concurrently...")

    # By simply calling the decorated function, it triggers a background worker.
    # We can then 'await' it directly to pause execution until the thread finishes.
    result_1 = await compute_heavy_sync_work(1, 1.5)
    print(f"Main: Received -> {result_1}")

    result_2 = await compute_heavy_sync_work(2, 0.5)
    print(f"Main: Received -> {result_2}")


if __name__ == "__main__":
    # Bootstraps the application via the main Task runner
    Task.run(main).result()
