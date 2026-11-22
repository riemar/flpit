import pytest
import pytest

from flpit import AsyncFlpIt, flp
from flpit.task import (
    Task,
    TaskCompletionSource,
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


# =========================++++++++++================
# ---  Test when_each (Task, FlpIt, FlpList)  ---
# =========================++++++++++================

def _from_task(sources):
    return Task.when_each([s.task for s in sources])


def _from_flpit(sources):
    return flp.it(sources).select(lambda s: s.task).when_each()


def _from_flplist(sources):
    return flp.lst(sources).select(lambda s: s.task).to_list().when_each()


class TestWhenEach:
    def test_collect_is_an_alias_of_when_each(self):
        assert Task.collect is Task.when_each

    @pytest.mark.parametrize("build", [_from_task, _from_flpit, _from_flplist])
    def test_yields_tasks_in_completion_order(self, build):
        """Completion is driven by the consumer, so the order is exact and does not depend on timing."""
        sources = [TaskCompletionSource() for _ in range(3)]
        completion_order = [2, 0, 1]
        sources[completion_order[0]].set_result(completion_order[0])
        stream = build(sources)

        async def consume():
            seen = []
            async for done in stream:
                seen.append(await done)
                if len(seen) < len(sources):
                    follower = completion_order[len(seen)]
                    sources[follower].set_result(follower)
            return seen

        assert Task.run(consume).result() == completion_order

    @pytest.mark.parametrize("build", [_from_flpit, _from_flplist])
    def test_returns_async_flpit_that_can_be_queried(self, build):
        sources = [TaskCompletionSource() for _ in range(2)]
        for source in sources:
            source.set_result(5)
        stream = build(sources)
        assert isinstance(stream, AsyncFlpIt)
        assert Task.run(lambda: stream.count()).result() == 2

    def test_flpit_starts_every_task_before_the_first_is_awaited(self):
        started: list[int] = []

        def start(n: int) -> Task[int]:
            started.append(n)
            return Task.run(lambda: n)

        stream = flp.it(range(4)).select(start).when_each()

        async def first_only():
            async for _ in stream:
                return list(started)

        assert Task.run(first_only).result() == [0, 1, 2, 3]


# =========================++++++++++================
# ---  Test when_all / when_any as query operators  ---
# =========================++++++++++================

def _tasks_as_flpit(sources):
    return flp.it(sources).select(lambda s: s.task)


def _tasks_as_flplist(sources):
    return flp.lst(sources).select(lambda s: s.task).to_list()


class TestWhenAllOperator:
    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_results_follow_query_order_not_completion_order(self, build):
        sources = [TaskCompletionSource() for _ in range(3)]
        combined = build(sources).when_all()

        for index in (2, 0, 1):
            sources[index].set_result(index * 10)

        assert combined.result() == [0, 10, 20]

    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_completes_only_after_the_last_task(self, build):
        sources = [TaskCompletionSource() for _ in range(3)]
        combined = build(sources).when_all()

        sources[0].set_result(0)
        sources[1].set_result(1)
        assert not combined.done()

        sources[2].set_result(2)
        assert combined.result() == [0, 1, 2]

    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_a_failed_task_is_raised(self, build):
        sources = [TaskCompletionSource() for _ in range(2)]
        combined = build(sources).when_all()

        sources[0].set_result(1)
        sources[1].set_exception(KeyError("boom"))

        with pytest.raises(KeyError):
            combined.result()

    def test_empty_query_gives_an_empty_list(self):
        assert flp.it([]).select(lambda n: Task.run(lambda: n)).when_all().result() == []

    def test_flpit_starts_every_task_before_waiting(self):
        started: list[int] = []

        def start(n: int) -> Task[int]:
            started.append(n)
            return Task.run(lambda: n)

        combined = flp.it(range(4)).select(start).when_all()

        assert started == [0, 1, 2, 3]
        assert combined.result() == [0, 1, 2, 3]

    def test_accepts_coroutines(self):
        async def double(n: int) -> int:
            return n * 2

        assert flp.it(range(3)).select(double).when_all().result() == [0, 2, 4]

    def test_matches_the_static_method(self):
        sources = [TaskCompletionSource() for _ in range(2)]
        for source in sources:
            source.set_result(7)

        assert _tasks_as_flpit(sources).when_all().result() == Task.when_all([s.task for s in sources]).result()


class TestWhenAnyOperator:
    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_returns_the_first_task_to_complete(self, build):
        sources = [TaskCompletionSource() for _ in range(3)]
        first = build(sources).when_any()

        assert not first.done()
        sources[1].set_result("middle")

        winner = first.result()
        assert winner is sources[1].task
        assert winner.result() == "middle"

    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_a_failed_winner_is_returned_not_raised(self, build):
        sources = [TaskCompletionSource() for _ in range(2)]
        first = build(sources).when_any()

        sources[0].set_exception(KeyError("boom"))

        winner = first.result()
        assert winner is sources[0].task
        with pytest.raises(KeyError):
            winner.result()

    @pytest.mark.parametrize("build", [_tasks_as_flpit, _tasks_as_flplist])
    def test_other_tasks_keep_running(self, build):
        sources = [TaskCompletionSource() for _ in range(2)]
        first = build(sources).when_any()

        sources[0].set_result("a")
        first.result()

        assert not sources[1].task.done()
        sources[1].set_result("b")
        assert sources[1].task.result() == "b"

    def test_input_order_breaks_a_tie(self):
        sources = [TaskCompletionSource() for _ in range(3)]
        for source in sources:
            source.set_result(0)

        assert _tasks_as_flpit(sources).when_any().result() is sources[0].task

    def test_empty_query_is_invalid(self):
        with pytest.raises(ValueError):
            flp.it([]).select(lambda n: Task.run(lambda: n)).when_any()

    def test_flpit_starts_every_task_before_waiting(self):
        started: list[int] = []

        def start(n: int) -> Task[int]:
            started.append(n)
            return Task.run(lambda: n)

        first = flp.it(range(4)).select(start).when_any()

        assert started == [0, 1, 2, 3]
        first.result()
