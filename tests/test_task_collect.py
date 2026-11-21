import pytest
import pytest

from flpit import AsyncFlpIt
from flpit.task import (
    Task,
    asyncio_task
)

from typing import Any

@pytest.fixture
def isolate_worker_pool():
    """Tear down the existing active runtime to re-configure pool capacity safely."""
    # 1. Kill the active module-level runtime context cleanly
    Task.shutdown(grace_timeout=0.1, worker_timeout=0.2)

    # 2. Broaden the gates now that the engine is stopped
    Task.configure(max_workers=4)

    yield

    # 3. Clean up our test runtime after execution finishes
    Task.shutdown(grace_timeout=0.1, worker_timeout=0.2)

    # 4. Restore the strict module environment expected by the other tests
    Task.configure(max_workers=1)


@asyncio_task
async def async_mock_worker(task_id: int, duration: float) -> dict[str, Any]:
    """An asyncio-dependent coroutine wrapped as a thread task."""
    # Simulating a light non-blocking context inside the sandboxed loop
    import asyncio
    await asyncio.sleep(duration)
    return {"id": task_id, "status": "done"}


@asyncio_task
async def async_exploding_worker(task_id: int) -> None:
    """An async coroutine designed to fail inside its local runner."""
    raise ValueError(f"Crash simulated on task #{task_id}")

# =========================++++++++++================
# ---  Test Task.collect  ---
# =========================++++++++++================

class TestTaskCollect():
    def test_task_collect_streaming_order(self, isolate_worker_pool):
        """Verify Task.collect streams tasks in order of their completion, not submission."""
        # Launch three tasks where the second task finishes first
        t1 = async_mock_worker(1, duration=0.3)
        t2 = async_mock_worker(2, duration=0.05)  # Finished first
        t3 = async_mock_worker(3, duration=0.2)

        tasks = [t1, t2, t3]

        # Internal runner wrapper to consume the async generator inside the test execution
        async def run_collection():
            collected_ids = []
            async for completed_task in Task.collect(tasks):
                res = completed_task.result()
                collected_ids.append(res["id"])
            return collected_ids

        # Execute the collection via the flpit Task tree
        execution_order = Task.run(run_collection).result()

        # Assert that task 2 was yielded first because its duration was the shortest
        assert execution_order == [2, 3, 1]


    def test_task_collect_accepts_loose_positionals_and_lists(self, isolate_worker_pool):
        """Verify Task.collect handles both a raw list container and loose *args parameters."""
        t1 = async_mock_worker(1, duration=0.01)
        t2 = async_mock_worker(2, duration=0.01)

        async def run_with_list():
            return [t async for t in Task.collect([t1, t2])]

        async def run_with_positionals():
            return [t async for t in Task.collect(t1, t2)]

        list_results = Task.run(run_with_list).result()
        positional_results = Task.run(run_with_positionals).result()

        assert len(list_results) == 2
        assert len(positional_results) == 2

    def test_task_collect_returns_async_flpit(self, isolate_worker_pool):
        """Task.collect returns an AsyncFlpIt (not a bare async generator) in both call forms."""
        t1 = async_mock_worker(1, duration=0.01)
        t2 = async_mock_worker(2, duration=0.01)

        assert isinstance(Task.collect([t1, t2]), AsyncFlpIt)
        assert isinstance(Task.collect(t1, t2), AsyncFlpIt)

    def test_task_collect_supports_fluent_queries_in_completion_order(self, isolate_worker_pool):
        """AsyncFlpIt operators work on collect: a bare async generator has no .select/.where."""
        t1 = async_mock_worker(1, duration=0.3)
        t2 = async_mock_worker(2, duration=0.05)  # finishes first
        t3 = async_mock_worker(3, duration=0.2)

        async def run_query():
            return await (
                Task.collect(t1, t2, t3)
                .select(lambda finished: finished.result()["id"])
                .where(lambda task_id: task_id != 3)
                .to_list()
            )

        assert list(Task.run(run_query).result()) == [2, 1]

    def test_task_collect_result_can_be_enumerated_again(self, isolate_worker_pool):
        """The AsyncFlpIt is cold: a second enumeration re-yields the (now completed) tasks."""
        t1 = async_mock_worker(1, duration=0.01)
        t2 = async_mock_worker(2, duration=0.01)
        stream = Task.collect(t1, t2)

        async def run_twice():
            return await stream.count(), await stream.count()

        assert Task.run(run_twice).result() == (2, 2)
