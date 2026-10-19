"""
Example: Moving from a Synchronous Scope into Parallel Execution

This example demonstrates a core use case of flpit: transitioning from a standard,
blocking synchronous function into a parallel processing pipeline using background threads.

Key Takeaways:
1. **Sync to Parallel Boundary**:
    Calling a @task function or passing a plain function to Task.run() without blocking
    spawns the background execution branches, instantly shifting a single synchronous
    execution path into multiple concurrent tracks.

2. **Synchronous Collection**:
    Since the operations execute concurrently, you can block and collect their results
    sequentially at the end without losing the parallel execution advantage.
"""
import time
from flpit.task import Task, task


@task
def step_alpha(duration: float) -> str:
    """A blocking function wrapped with the @task decorator."""
    print("Worker Thread: Alpha starting heavy work...")
    time.sleep(duration)
    return "Alpha Payload"


def step_beta(duration: float) -> str:
    """A raw, standard blocking function with no decorator."""
    print("Worker Thread: Beta starting heavy work...")
    time.sleep(duration)
    return "Beta Payload"


def main():
    print("Main Thread: Dispatching parallel work from a pure sync scope...")
    start_time = time.monotonic()

    # Mix of @task and Task.run(...)
    # Both are immediately kicked off in parallel on the background threads
    task_1 = step_alpha(1.5)
    task_2 = Task.run(step_beta, 1.0)

    print("Main Thread: Both dispatched non-blockingly. Blocking for results...")

    # collect results sequentially.
    # Because they ran in parallel, total block time is max(1.5, 1.0) = 1.5s
    res_1 = task_1.result()
    res_2 = task_2.result()

    # alternatively
    #Task.when_all(task_1, task_2).result()

    print(f"\nMain Thread: Received -> {res_1} and {res_2}")

    total_duration = time.monotonic() - start_time
    print(f"Parallel execution completed in {total_duration:.2f} seconds.")


if __name__ == "__main__":
    main()
