"""
Example: Fast-Response Win Using Task.when_any

This example shows how to fire multiple tasks concurrently and react
immediately to whichever task finishes first, ignoring the rest.
"""

import time
import random
from flpit.task import task, Task


@task
def fetch_from_server(server_name: str, delay: float) -> str:
    """Simulates a response from a specific mirror server."""
    time.sleep(delay)
    return f"Response from {server_name}"


async def main():
    print("Main: Querying primary and secondary mirrors simultaneously...")

    # 1. Fire two parallel requests with unpredictable network speeds
    t1 = fetch_from_server("Primary US Server", delay=1.5)
    t2 = fetch_from_server("Backup EU Server", delay=0.4)

    # 2. The race is on: Task.when_any blocks until the FIRST task completes
    fastest_task = await Task.when_any(t1, t2)

    # 3. Grab the winner's result instantly
    winner_result = fastest_task.result()
    print(f"\nMain: Winner cleared! -> {winner_result}")


if __name__ == "__main__":
    Task.run(main).result()
