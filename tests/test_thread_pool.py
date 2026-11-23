"""ThreadPool.queue / queue_user_work_item: plain work items, no Task.

.NET reference: ``ThreadPool.UnsafeQueueUserWorkItem`` runs the callback on a pool thread
with the default (empty) ExecutionContext and resets the thread's context after each item;
``QueueUserWorkItem`` flows the caller's ExecutionContext. Items queued from one thread
to the global queue start in FIFO order. These expectations come from the .NET
documentation; the .NET oracle itself was not run for them.
"""
from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Any

import pytest

import flpit.task as task_module
from flpit.core.linq import ArgumentNullError
from flpit.task import RuntimeShutdownError, Task
from flpit.threading import AsyncLocal, ThreadPool

TIMEOUT = 5.0


@pytest.fixture(scope="module", autouse=True)
def default_sized_pool() -> Any:
    """Several workers, whatever an earlier module configured: a work item blocked in a test
    must not stall the others."""
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(min_workers=8, max_workers=64)
    yield
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


@pytest.fixture
def pool():
    """A runtime of its own with the worker limits the test asks for."""
    previous = dict(task_module._runtime_config)
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)

    def configure(**limits: int) -> None:
        Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
        Task.configure(**limits)

    yield configure
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    Task.configure(**previous)


def run_items(queue: Any, *callbacks: Any) -> None:
    """Queue each callback and wait until all of them ran."""
    done = threading.Semaphore(0)

    def wrap(callback: Any) -> Any:
        def item() -> None:
            try:
                callback()
            finally:
                done.release()
        return item

    for callback in callbacks:
        assert queue(wrap(callback)) is True
    for _ in callbacks:
        assert done.acquire(timeout=TIMEOUT)


@pytest.mark.parametrize("queue", [ThreadPool.queue, ThreadPool.queue_user_work_item])
def test_runs_on_a_pool_worker_from_an_outside_thread(queue: Any) -> None:
    seen: list[threading.Thread] = []
    run_items(queue, lambda: seen.append(threading.current_thread()))
    assert seen[0] is not threading.current_thread()
    assert seen[0].name.startswith("Task-worker-")


@pytest.mark.parametrize("queue", [ThreadPool.queue, ThreadPool.queue_user_work_item])
def test_state_is_passed_only_when_given(queue: Any) -> None:
    got: list[Any] = []
    finished = threading.Event()

    def with_state(state: Any) -> None:
        got.append(state)
        if len(got) == 2:
            finished.set()

    queue(with_state, None)  # None is a state like any other
    queue(with_state, "s")
    assert finished.wait(TIMEOUT)
    assert sorted(got, key=repr) == sorted([None, "s"], key=repr)

    called: list[str] = []
    run_items(queue, lambda: called.append("no state"))
    assert called == ["no state"]


def test_items_from_one_thread_start_in_fifo_order(pool: Any) -> None:
    pool(max_workers=1)
    order: list[int] = []
    run_items(ThreadPool.queue, *[(lambda i=i: order.append(i)) for i in range(50)])
    assert order == list(range(50))


def test_queue_runs_in_an_empty_context_and_leaks_nothing_to_the_next_item(pool: Any) -> None:
    pool(max_workers=1)  # both items run on the same worker
    local: AsyncLocal[str] = AsyncLocal()
    variable: ContextVar[str] = ContextVar("variable", default="default")
    local.value = "caller"
    seen: list[Any] = []

    def first() -> None:
        seen.append((threading.current_thread(), local.value, variable.get()))
        local.value = "first"
        variable.set("first")

    def second() -> None:
        seen.append((threading.current_thread(), local.value, variable.get()))

    run_items(ThreadPool.queue, first, second)
    (thread1, local1, var1), (thread2, local2, var2) = seen
    assert thread1 is thread2
    assert (local1, var1) == (None, "default")
    assert (local2, var2) == (None, "default")
    assert local.value == "caller"


def test_safe_flows_the_callers_context_and_changes_do_not_flow_back() -> None:
    local: AsyncLocal[str] = AsyncLocal()
    local.value = "caller"
    seen: list[Any] = []

    def item() -> None:
        seen.append(local.value)
        local.value = "inside"
        seen.append(local.value)

    run_items(ThreadPool.queue_user_work_item, item)
    assert seen == ["caller", "inside"]
    assert local.value == "caller"


def test_a_work_item_queued_from_a_task_is_not_part_of_that_task() -> None:
    seen: list[Any] = []

    def item() -> None:
        seen.append(task_module._current_task.value)

    async def queue_from_task() -> None:
        run_items(ThreadPool.queue_user_work_item, item)
        run_items(ThreadPool.queue, item)

    Task.run(queue_from_task).result()
    assert seen == [None, None]


@pytest.mark.parametrize("queue", [ThreadPool.queue, ThreadPool.queue_user_work_item])
def test_exceptions_go_to_the_exception_handler(queue: Any) -> None:
    reports: list[dict[str, Any]] = []
    reported = threading.Event()

    def handler(context: dict[str, Any]) -> None:
        reports.append(context)
        reported.set()

    def failing() -> None:
        raise ValueError("work item failed")

    Task.set_exception_handler(handler)
    try:
        queue(failing)
        assert reported.wait(TIMEOUT)
    finally:
        Task.set_exception_handler(None)
    assert isinstance(reports[0]["exception"], ValueError)
    assert reports[0]["callback"] is failing
    assert "work item" in reports[0]["message"]
    # The worker survived and keeps taking items.
    run_items(queue, lambda: None)


@pytest.mark.parametrize("queue", [ThreadPool.queue, ThreadPool.queue_user_work_item])
def test_invalid_callbacks_are_rejected(queue: Any) -> None:
    with pytest.raises(ArgumentNullError):
        queue(None)
    with pytest.raises(TypeError):
        queue(42)


def test_no_task_is_created() -> None:
    runtime = task_module._get_runtime()
    release = threading.Event()
    started = threading.Event()

    def item() -> None:
        started.set()
        release.wait(TIMEOUT)

    before = len(runtime._snapshot_tasks())
    ThreadPool.queue(item)
    assert started.wait(TIMEOUT)
    try:
        assert len(runtime._snapshot_tasks()) == before
    finally:
        release.set()


def test_rejected_while_the_runtime_shuts_down(pool: Any) -> None:
    attempt: dict[str, Any] = {}
    parked = threading.Event()

    async def waits_for_shutdown() -> None:
        try:
            parked.set()
            await Task.delay(60)
        except BaseException:
            try:
                ThreadPool.queue(lambda: None)
            except RuntimeShutdownError as error:
                attempt["error"] = error
            raise

    Task.run(waits_for_shutdown)
    assert parked.wait(TIMEOUT)
    time.sleep(0.01)
    Task.shutdown(grace_timeout=1.0, worker_timeout=1.0)
    assert isinstance(attempt.get("error"), RuntimeShutdownError)


def test_the_pool_starts_lazily_after_a_shutdown(pool: Any) -> None:
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)
    seen: list[str] = []
    run_items(ThreadPool.queue, lambda: seen.append("ran"))
    assert seen == ["ran"]
