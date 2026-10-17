import random

import httpx
import time
from flpit.task import task, Task, AggregateError
from flpit import FlpList

# ===================================================================================
"""
⚠️ TARGET INFRASTRUCTURE WARNING:
Setting 'calls = 200' or higher with 'max_workers = 1000' turns this script into an 
aggressive network burst engine. 

Running high volumes of concurrent hits against public servers (like httpbin.org) 
could trigger rate-limiting, risk overwhelming the backend, and get your IP banned.

HIGH CALL VOLUMES MUST ONLY BE RUN AGAINST YOUR OWN CUSTOM/LOCAL TARGETS.
"""
calls = 50
target = "https://httpbin.org/delay"

# ===================================================================================

# we are just i/o bound so it's "fine"
Task.configure(max_workers=1000, max_pending_background=2048)

my_limits = httpx.Limits(
    max_connections=200,
    max_keepalive_connections=60,
    keepalive_expiry=30.0
)
# it's supposed to be thread safe
client = httpx.Client(limits=my_limits)
data = {}

@task
def fetch_random_delay(task_id: int):
    # 1. Generate a random delay between 0.1 and 1.5 seconds
    # delay_duration = random.uniform(0.1, 1.5)
    delay_duration = 1
    url = f"{target}/{delay_duration:.2f}"
    print(f"Task #{task_id}: asking for a delay of {delay_duration:.4f}s")

    start_time = time.perf_counter()
    try:
            # 2. Make a standard sync request with a safe 30s timeout limit
            response = client.get(url, timeout=30)
            return response.json()

    finally:
        call_duration = time.perf_counter() - start_time
        diff = call_duration - delay_duration
        data[task_id] = (call_duration, diff,)
        print(f"Task #{task_id} completed. Call took {call_duration:.4f}s - diff from requested delay  {diff:.4f}s")

async def main():
    print(f"Spawning {calls} random web tasks concurrently onto flpit.task background thread pool...")

    start_time = time.perf_counter()

    try:
        tasks: FlpList[Task] = FlpList[Task]()
        for i in range(calls):
            tasks.add(fetch_random_delay(i))

        # Wait for all background requests to resolve parallelly
        await Task.when_all(tasks)

    except AggregateError as ex:
        print("Ex: ", ex.exceptions)
        return

    total_duration = time.perf_counter() - start_time

    print(f"All {calls} tasks finished successfully without hitting client timeouts! Run too {total_duration:.4f}s")
    # print(data)

# Execute your custom main runner
Task.run(main).result()
