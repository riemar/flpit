"""
Example: Running Multiple Tasks in Parallel

This example shows how to fire a batch of separate tasks into the background
at the exact same time, and wait until every single one of them is finished.

Key Takeaways:
1. **Instant Parallel Blast**: When you call a `@task` function inside a list,
   all those tasks are dumped into the background pool immediately. They run
   in parallel across your CPU cores.

2. **Waiting for the Batch**: `await Task.when_all(tasks)` stops your main code
   from moving forward until the entire group of tasks is done.

3. **No Sequential Delay**: Instead of waiting for each task one after another
   (which would take 5 seconds total here), they all run at once and finish
   together in about 1 second.
"""
import time
from flpit.task import task, Task


@task
def fetch_data_worker(task_id: int) -> str:
    """A standard, blocking function simulating a heavy network call."""
    print(f"Worker Thread: Fetching data chunk #{task_id}...")
    time.sleep(1.0)  # Simulating a hard 1-second physical I/O barrier
    return f"Data Chunk {task_id}"


async def main():
    calls = 5
    print(f"Main: Firing {calls} tasks concurrently into the background pool...")

    start_time = time.perf_counter()

    # 1. Populate the task container.
    # Every call instantly creates a Task object and schedules it onto a worker.
    tasks = [fetch_data_worker(i) for i in range(calls)]

    # 2. Wait for the entire batch to resolve parallelly.
    # Instead of taking 5 seconds sequentially, the OS multiplexes the 1-second sleeps.
    await Task.when_all(tasks)

    # 3. Safely extract all returned payloads.
    results = [t.result() for t in tasks]

    total_duration = time.perf_counter() - start_time
    print(f"Main: All tasks cleared! Batch processing took {total_duration:.4f}s")
    print(f"Main: Gathered Results: {results}")


if __name__ == "__main__":
    # Bootstraps the application via the main Task runner
    Task.run(main).result()