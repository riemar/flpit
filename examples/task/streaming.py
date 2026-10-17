"""
Example: Native Async Streaming (True IAsyncEnumerable Pattern)

This example shows how to stream data lazily using asynchronous generators.
Unlike launching a huge batch of tasks at once, this pattern processes data
in a memory-efficient pipeline, item by item.
"""

import time
from flpit.task import Task


async def async_data_stream():
    """A true lazy data producer. It streams data on demand."""
    for i in range(1, 6):
        # In a real app, this would be reading a line from a huge file
        # or fetching the next page from a database chunk by chunk.
        print(f"Producer: Fetching item {i}...")

        # We simulate a small async step inside the pipeline
        await Task.run(time.sleep, 0.5)

        yield f"Item {i} Payload"  # Yield control and data back to the consumer


async def main():
    print("Main: Starting data stream consumption...\n")

    # This is the real, native Python equivalent to C#'s await foreach
    # Memory consumption remains near zero because elements are processed lazily.
    async for data_item in async_data_stream():
        print(f"Main: Consumed -> {data_item}")

    print("\nMain: Stream finished cleanly!")


if __name__ == "__main__":
    Task.run(main).result()
