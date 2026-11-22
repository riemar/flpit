import threading

import pytest

from flpit import AsyncFlpIt, flp
from flpit.core.linq import PredicateNoneError
from flpit.task import Task, TaskCompletionSource


def _from_flpit(items):
    return flp.it(items)


def _from_flplist(items):
    return flp.lst(items)


def _from_async(items):
    return flp.it(items).to_async_enumerable()


ALL_SOURCES = [_from_flpit, _from_flplist, _from_async]


class TestSelectAwait:
    @pytest.mark.parametrize("build", ALL_SOURCES)
    def test_awaits_the_task_a_plain_callable_returns(self, build):
        stream = build([1, 2, 3]).select_await(lambda n: Task.run(lambda: n * 10))

        assert isinstance(stream, AsyncFlpIt)
        assert stream.to_list().result() == [10, 20, 30]

    def test_async_select_alone_does_not_await_that_task(self):
        """The reason select_await exists: a lambda returning a Task is not awaited by select."""
        stream = _from_async([1, 2]).select(lambda n: Task.run(lambda: n))
        values = stream.to_list().result()

        assert all(isinstance(value, Task) for value in values)

    def test_awaits_a_coroutine(self):
        async def double(n: int) -> int:
            return n * 2

        assert flp.it([1, 2, 3]).select_await(double).to_list().result() == [2, 4, 6]

    def test_calls_the_selector_one_element_at_a_time(self):
        """.NET SelectAwait: the next element is not selected until the previous result has arrived."""
        sources = [TaskCompletionSource() for _ in range(3)]
        called: list[int] = []
        reached = [threading.Event() for _ in sources]

        def select(index: int) -> Task[int]:
            called.append(index)
            reached[index].set()
            return sources[index].task

        job = flp.it(range(3)).select_await(select).to_list()

        assert reached[0].wait(10)
        assert called == [0]
        assert not job.done()

        sources[0].set_result(0)
        assert reached[1].wait(10)
        sources[1].set_result(1)
        assert reached[2].wait(10)
        sources[2].set_result(2)

        assert job.result() == [0, 1, 2]

    @pytest.mark.parametrize("with_identity", [False, True])
    def test_after_when_each_it_yields_the_values_in_completion_order(self, with_identity):
        sources = [TaskCompletionSource() for _ in range(3)]
        completion_order = [2, 0, 1]
        sources[completion_order[0]].set_result(completion_order[0])
        tasks = flp.it(sources).select(lambda s: s.task).when_each()
        stream = tasks.select_await(lambda t: t) if with_identity else tasks.select_await()

        async def consume():
            seen = []
            async for value in stream:
                seen.append(value)
                if len(seen) < len(sources):
                    follower = completion_order[len(seen)]
                    sources[follower].set_result(follower)
            return seen

        assert Task.run(consume).result() == completion_order

    def test_a_failed_task_is_raised(self):
        def fail(_: int) -> Task[int]:
            raise_in_task = TaskCompletionSource()
            raise_in_task.set_exception(KeyError("boom"))
            return raise_in_task.task

        with pytest.raises(KeyError):
            flp.it([1]).select_await(fail).to_list().result()

    def test_a_result_that_is_not_awaitable_raises(self):
        with pytest.raises(TypeError):
            flp.it([1]).select_await(lambda n: n).to_list().result()

    @pytest.mark.parametrize("build", ALL_SOURCES)
    def test_without_a_selector_the_elements_are_awaited(self, build):
        tasks = [Task.run(lambda n=n: n * 10) for n in (1, 2, 3)]

        stream = build(tasks).select_await()

        assert isinstance(stream, AsyncFlpIt)
        assert stream.to_list().result() == [10, 20, 30]

    @pytest.mark.parametrize("build", ALL_SOURCES)
    def test_none_means_the_same_as_no_selector(self, build):
        tasks = [Task.run(lambda n=n: n) for n in (1, 2)]

        assert build(tasks).select_await(None).to_list().result() == [1, 2]

    def test_without_a_selector_a_non_awaitable_element_raises(self):
        with pytest.raises(TypeError):
            flp.it([1, 2]).select_await().to_list().result()


class TestWhereAwait:
    @pytest.mark.parametrize("build", ALL_SOURCES)
    def test_keeps_the_elements_whose_awaited_answer_is_true(self, build):
        stream = build([1, 2, 3, 4]).where_await(lambda n: Task.run(lambda: n % 2 == 0))

        assert isinstance(stream, AsyncFlpIt)
        assert stream.to_list().result() == [2, 4]

    def test_awaits_a_coroutine(self):
        async def is_big(n: int) -> bool:
            return n > 1

        assert flp.it([1, 2, 3]).where_await(is_big).to_list().result() == [2, 3]

    def test_asks_one_element_at_a_time(self):
        sources = [TaskCompletionSource() for _ in range(2)]
        asked: list[int] = []
        reached = [threading.Event() for _ in sources]

        def ask(index: int) -> Task[bool]:
            asked.append(index)
            reached[index].set()
            return sources[index].task

        job = flp.it(range(2)).where_await(ask).to_list()

        assert reached[0].wait(10)
        assert asked == [0]

        sources[0].set_result(True)
        assert reached[1].wait(10)
        sources[1].set_result(False)

        assert job.result() == [0]

    @pytest.mark.parametrize("build", ALL_SOURCES)
    def test_none_predicate_is_rejected(self, build):
        with pytest.raises(PredicateNoneError):
            build([1]).where_await(None)
