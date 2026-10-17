"""
Example: Streaming Completed Tasks Using Task.collect

This example demonstrates how to use the `Task.collect` asynchronous generator
to consume and process background tasks one by one as they finish,
instead of waiting for the entire batch to complete.

Key Takeaways:
1. **The Collect Pattern**: Passing a list of tasks to `Task.collect` allows you
   to iterate over them using a standard `async for` loop.
2. **Immediate Processing**: Tasks are yielded the exact millisecond they finish
   execution, allowing you to process results while other threads are still running.
3. **Preserved Identity**: Unlike native python alternatives, `Task.collect` yields
   the actual, original `Task` object, allowing you to safely inspect task metadata
   and results.
"""

import time
import random
from flpit.task import task, Task


@task
def dynamic_network_worker(task_id: int) -> str:
    """Simulates an unpredictable network request with varying durations."""
    duration = random.uniform(0.5, 2.5)
    time.sleep(duration)  # Safe blocking OS sleep inside the thread pool
    return f"Task #{task_id} completed after {duration:.2f}s"


async def main():
    calls = 5
    print(f"Main: Firing {calls} variable-runtime tasks into the pool...")

    # 1. Fire all tasks concurrently into the background OS thread pool
    tasks = [dynamic_network_worker(i) for i in range(calls)]

    print("Main: Collecting and processing tasks as they trickle in:\n")

    # 2. Stream the completed tasks natively using your clean new API
    async for completed_task in Task.collect(tasks):
        result = await completed_task # await just unpacks the result .result() would be also possible
        print(f"Main: Handled -> {result}")

    print("\nMain: All tasks collected successfully!")


if __name__ == "__main__":
    # Bootstraps the application root tree via the main Task runner
    Task.run(main).result()
