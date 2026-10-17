import asyncio
import random
import time
import httpx


# ===================================================================================
"""
⚠️ TARGET INFRASTRUCTURE WARNING:
Setting 'calls = 500' or higher with 'max_workers = 1000' turns this script into an 
aggressive network burst engine. 

Running high volumes of concurrent hits against public servers (like httpbin.org) 
could trigger rate-limiting, risk overwhelming the backend, and get your IP banned.

HIGH CALL VOLUMES MUST ONLY BE RUN AGAINST YOUR OWN CUSTOM/LOCAL TARGETS.
"""
calls = 50
target = "https://httpbin.org/delay"

# ===================================================================================

my_limits = httpx.Limits(
    max_connections=200,
    max_keepalive_connections=60,
    keepalive_expiry=30.0,
)
# supposed to be thread safe
client = httpx.AsyncClient(limits=my_limits)
data = {}

# Note: No @task decorator here. This is a pure standard Python coroutine.
async def fetch_random_delay(task_id: int):
    # 1. Generate a random delay between 0.1 and 1.5 seconds
    # delay_duration = random.uniform(0.1, 1.5)
    delay_duration = 1
    url = f"{target}/{delay_duration:.2f}"
    print(f"Task #{task_id}: asking for a delay of {delay_duration:.4f}s")

    start_time = time.perf_counter()
    try:
        # The 'await' here yields control instantly, letting other tasks run
        response = await client.get(url, timeout=30)
        return response.json()
    finally:
        total_duration = time.perf_counter() - start_time
        diff = total_duration - delay_duration
        data[task_id] = (total_duration, diff,)
        print(f"Task #{task_id} completed. Call took {total_duration:.4f}s - diff from requested delay  {diff:.4f}s")


async def main():
    print(
        f"Spawning {calls} random web tasks concurrently onto the asyncio event loop..."
    )

    start_time = time.perf_counter()

    try:
        # asyncio.gather triggers and polls them concurrently on a single thread.
        # return_exceptions=False means the first error will raise immediately.
        # We don't use a background thread/process executor here because
        # the event loop allows us to invoke any async function from anywhere with any arbitrary signature.
        await asyncio.gather(*(fetch_random_delay(i) for i in range(calls)))

    except (httpx.HTTPError, TimeoutError) as ex:
        # asyncio doesn't use AggregateError natively; individual exceptions
        # Bubble up directly out of the gather execution block.
        print("Ex: ", type(ex).__name__, ex)
        return

    total_duration = time.perf_counter() - start_time

    print(f"All {calls} tasks finished successfully without hitting client timeouts! Run too {total_duration:.4f}s")
    # print(data)

if __name__ == "__main__":
    # Bootstraps the native single-threaded asyncio event loop engine
    asyncio.run(main())
