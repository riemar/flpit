import pytest

import inspect
import socket

import flpit.task as task_module
import threading
import time

from flpit.task import (
    BackgroundQueueFull,
    CancellationTokenSource,
    IO,
    Task,
    AggregateError,
    OperationCanceledError,
    asyncio_task,
    twait
)

from typing import Any


@pytest.fixture(scope="module", autouse=True)
def configure_task_runtime():
    """Mirror the former unittest setUpClass configuration."""
    Task.configure(max_workers=1, max_pending_background=1)
    yield
    # Leave the test process without a live scheduler/worker pool.
    Task.shutdown(grace_timeout=0.5, worker_timeout=1.0)


def test_async_composition_and_background_callable():
    async def child() -> int:
        await Task.delay(0.01)
        return await Task.run(lambda: 40) + 2

    assert Task.run(child).result() == 42


def test_independent_and_linked_tokens():
    first = CancellationTokenSource()
    second = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(
        first.token, second.token
    )

    async def waiting(token):
        await Task.delay(5, token=token)
        return "finished"

    try:
        a = Task.run(waiting, first.token)
        b = Task.run(waiting, second.token)
        time.sleep(0.02)

        first.cancel()
        with pytest.raises(OperationCanceledError):
            a.result()

        assert not second.is_cancellation_requested
        assert not b.done()

        second.cancel()
        with pytest.raises(OperationCanceledError):
            b.result()

        assert linked.is_cancellation_requested
        assert first.token.is_cancellation_requested
    finally:
        first.dispose()
        second.dispose()
        linked.dispose()


def test_cancel_after_and_operation_token():
    source = CancellationTokenSource()
    source.cancel_after(0.02)

    async def delayed():
        await Task.delay(5, token=source.token)

    try:
        with pytest.raises(OperationCanceledError):
            Task.run(delayed).result()
    finally:
        source.dispose()


def test_socket_readiness_and_cancellation():
    reader, writer = socket.socketpair()
    reader.setblocking(False)
    writer.setblocking(False)
    source = CancellationTokenSource()

    async def wait_readable():
        await IO.wait_readable(reader, token=source.token)
        return reader.recv(1)

    try:
        task = Task.run(wait_readable)
        time.sleep(0.02)
        writer.send(b"x")
        assert task.result() == b"x"

        async def wait_forever():
            await IO.wait_readable(reader, token=source.token)

        blocked = Task.run(wait_forever)
        time.sleep(0.02)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            blocked.result()
    finally:
        source.dispose()
        reader.close()
        writer.close()


def test_background_queue_is_bounded():
    entered = threading.Event()
    release = threading.Event()

    def blocking_call(number: int) -> int:
        if number == 1:
            entered.set()
        release.wait(2)
        return number

    first = Task.run(blocking_call, 1)
    assert entered.wait(1)
    second = Task.run(blocking_call, 2)
    third = Task.run(blocking_call, 3)

    try:
        with pytest.raises(BackgroundQueueFull):
            third.result()
    finally:
        release.set()

    assert first.result() == 1
    assert second.result() == 2


def test_passed_token_allows_cooperative_worker_stop():
    source = CancellationTokenSource()
    started = threading.Event()
    exited = threading.Event()

    def cooperative_worker(*, token):
        started.set()
        try:
            while not token.is_cancellation_requested:
                time.sleep(0.005)
            token.throw_if_cancellation_requested()
        finally:
            exited.set()

    try:
        task = Task.run(cooperative_worker, token=source.token, pass_token=True)
        assert started.wait(1)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            task.result()
        assert exited.wait(1)
    finally:
        source.dispose()


def test_when_all_preserves_input_order_and_waits_for_every_task():
    later_finished = threading.Event()

    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        if value == 2:
            later_finished.set()
        return value

    first = Task.run(value_after, 1, 0.04)
    second = Task.run(value_after, 2, 0.01)
    aggregate = Task.when_all(first, second)

    assert aggregate.result() == [1, 2]
    assert later_finished.is_set()

    # Passing a single iterable is also supported by the current API.
    assert Task.when_all([Task.run(lambda: 3)]).result() == [3]
    assert Task.when_all().result() == []


def test_when_all_accepts_raw_coroutines_and_schedules_them():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    raw_fast = value_after(1, 0.01)
    raw_slow = value_after(2, 0.02)
    background = Task.run(lambda: 3)

    assert Task.when_all([raw_fast, raw_slow, background]).result() == [1, 2, 3]


def test_when_any_accepts_raw_coroutines():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    winner = Task.when_any(
        [value_after(1, 0.05), value_after(2, 0.01)]
    ).result()
    assert winner.result() == 2

    # Coroutine objects are one-shot; use fresh ones for another combinator.
    all_results = Task.when_all(
        [value_after(1, 0.02), value_after(2, 0.01)]
    ).result()
    assert all_results == [1, 2]


def test_invalid_when_all_input_closes_supplied_coroutine():
    async def value() -> int:
        return 1

    coroutine = value()
    with pytest.raises(TypeError, match="Task instances or awaitables"):
        Task.when_all([coroutine, object()])

    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


def test_when_all_waits_for_all_children_before_propagating_failure():
    other_finished = threading.Event()

    async def fail_soon() -> int:
        await Task.delay(0.01)
        raise ValueError("expected test failure")

    async def finish_later() -> int:
        await Task.delay(0.05)
        other_finished.set()
        return 7

    failed = Task.run(fail_soon)
    later = Task.run(finish_later)
    aggregate = Task.when_all(failed, later)

    with pytest.raises(ValueError, match="expected test failure"):
        aggregate.result()
    assert other_finished.is_set()


def test_when_all_exposes_multiple_failures():
    def fail(message: str):
        raise ValueError(message)

    aggregate = Task.when_all(Task.run(fail, "one"), Task.run(fail, "two"))
    with pytest.raises(AggregateError) as caught:
        aggregate.result()

    assert len(caught.value.exceptions) == 2
    assert {str(error) for error in caught.value.exceptions} == {"one", "two"}


def test_when_any_returns_first_completed_task_without_cancelling_losers():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    slow = Task.run(value_after, 1, 0.08)
    fast = Task.run(value_after, 2, 0.01)
    winner = Task.when_any(slow, fast).result()

    assert winner is fast
    assert winner.result() == 2
    assert slow.result() == 1

    with pytest.raises(ValueError):
        Task.when_any()


def test_cancelling_aggregate_does_not_cancel_child_tasks():
    async def value_after(value: int) -> int:
        await Task.delay(0.04)
        return value

    first = Task.run(value_after, 1)
    second = Task.run(value_after, 2)
    aggregate = Task.when_all(first, second)
    time.sleep(0.01)
    aggregate.cancel()

    with pytest.raises(OperationCanceledError):
        aggregate.result()
    assert first.result() == 1
    assert second.result() == 2


def test_scheduler_callback_errors_reach_exception_handler():
    seen = []
    Task.set_exception_handler(seen.append)
    try:
        runtime = task_module._get_runtime()
        runtime._post(lambda: 1 / 0)
        deadline = time.monotonic() + 1
        while not seen and time.monotonic() < deadline:
            time.sleep(0.005)

        assert seen
        assert isinstance(seen[0]["exception"], ZeroDivisionError)
    finally:
        Task.set_exception_handler(None)


def test_shutdown_runs_async_cleanup_and_reports_running_workers():
    cleaned = threading.Event()

    async def task_with_cleanup():
        try:
            await Task.delay(30)
        finally:
            await Task.delay(0.02)
            cleaned.set()

    task = Task.run(task_with_cleanup)
    time.sleep(0.02)
    report = Task.shutdown(grace_timeout=0.5, worker_timeout=0.2)

    assert report.runtime_stopped
    assert cleaned.is_set()
    with pytest.raises(OperationCanceledError):
        task.result()

    worker_started = threading.Event()
    worker_release = threading.Event()
    worker_finished = threading.Event()

    def blocking_worker():
        worker_started.set()
        try:
            worker_release.wait(2)
            return 9
        finally:
            worker_finished.set()

    running = Task.run(blocking_worker)
    assert worker_started.wait(1)
    report = Task.shutdown(grace_timeout=0.5, worker_timeout=0.01)

    assert report.runtime_stopped
    assert report.workers_still_running == 1
    assert report.timed_out

    worker_release.set()
    assert worker_finished.wait(1)
    assert Task.run(lambda: 7).result() == 7  # lazy restart works
    Task.shutdown(grace_timeout=0.5, worker_timeout=0.5)


# =========================++++++++++
# --- Cancellation specific tests ---
# =========================++++++++++

class TestTaskCancellation:
    def test_cancel_invokes_callbacks_lifo_aggregates_errors_and_is_idempotent(self):
        cts = CancellationTokenSource()
        calls = []

        def first():
            calls.append("first")

        def failing():
            calls.append("failing")
            raise ValueError("boom")

        def last():
            calls.append("last")

        cts.token.register(first)
        cts.token.register(failing)
        cts.token.register(last)

        with pytest.raises(AggregateError) as exc_info:
            cts.cancel()

        # Callbacks execute in reverse registration order.
        assert calls == ["last", "failing", "first"]

        # The callback failure is preserved.
        assert len(exc_info.value.exceptions) == 1
        assert isinstance(exc_info.value.exceptions[0], ValueError)
        assert str(exc_info.value.exceptions[0]) == "boom"

        # Aggregate message matches the agreed contract.
        assert str(exc_info.value) == "One or more errors occurred."

        # Cancellation is idempotent; callbacks are not invoked again.
        assert cts.cancel() is False
        assert calls == ["last", "failing", "first"]


    def test_register_after_cancellation_invokes_callback_immediately(self):
        cts = CancellationTokenSource()
        cts.cancel()

        calls = []

        cts.token.register(lambda: calls.append("called"))

        assert calls == ["called"]


    def test_register_after_cancellation_propagates_callback_exception(self):
        cts = CancellationTokenSource()
        cts.cancel()

        calls = []

        def callback():
            calls.append("called")
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            cts.token.register(callback)

        assert calls == ["called"]


    def test_disposed_registration_is_not_invoked_on_cancellation(self):
        cts = CancellationTokenSource()
        calls = []

        registration = cts.token.register(
            lambda: calls.append("called")
        )

        registration.dispose()
        cts.cancel()

        assert calls == []


    def test_register_during_cancellation_invokes_immediately(self):
        cts = CancellationTokenSource()
        calls = []

        def outer_callback():
            calls.append("outer-start")
            cts.token.register(lambda: calls.append("nested"))
            calls.append("outer-end")

        cts.token.register(outer_callback)
        cts.cancel()

        assert calls == ["outer-start", "nested", "outer-end"]


    def test_cancel_called_from_callback_is_idempotent(self):
        cts = CancellationTokenSource()
        calls = []

        def callback():
            calls.append("called")
            assert cts.cancel() is False

        cts.token.register(callback)

        assert cts.cancel() is True
        assert calls == ["called"]


    def test_cancel_aggregates_all_callback_exceptions(self):
        cts = CancellationTokenSource()

        def fail_one():
            raise ValueError("first")

        def fail_two():
            raise RuntimeError("second")

        cts.token.register(fail_one)
        cts.token.register(fail_two)

        with pytest.raises(AggregateError) as exc_info:
            cts.cancel()

        assert len(exc_info.value.exceptions) == 2
        assert isinstance(exc_info.value.exceptions[0], RuntimeError)
        assert isinstance(exc_info.value.exceptions[1], ValueError)


    def test_cancelling_linked_source_does_not_cancel_parents(self):
        first = CancellationTokenSource()
        second = CancellationTokenSource()

        linked = CancellationTokenSource.create_linked_token_source(
            first.token,
            second.token,
        )

        linked.cancel()

        assert linked.token.is_cancellation_requested
        assert not first.token.is_cancellation_requested
        assert not second.token.is_cancellation_requested

        linked.dispose()


# =========================++++++++++================
# ---  Test async.runner dependent (The Targets)  ---
# =========================++++++++++================

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


class TestCoroTaskDecorator:
    def test_asyncio_task_decorator_execution(self):
        """Verify that @asyncio_task executes an async function on a background thread pool."""
        # Spawning the task via the flpit engine (returns a Task instance)
        t = async_mock_worker(42, duration=0.1)

        # Resolving it synchronously using .result()
        result = t.result()

        assert result == {"id": 42, "status": "done"}


@pytest.fixture
def concurrency_pool():
    """Tear down the existing active runtime to re-configure pool capacity safely."""
    # 1. Kill the active module-level runtime context cleanly
    Task.shutdown(grace_timeout=0.1, worker_timeout=0.2)

    # 2. Broaden the gates now that the engine is stopped
    Task.configure(max_workers=100, max_pending_background=200)

    yield

    # 3. Clean up our test runtime after execution finishes
    Task.shutdown(grace_timeout=0.1, worker_timeout=0.2)

    # 4. Restore the strict module environment expected by the other tests
    Task.configure(max_workers=1, max_pending_background=1)

def test_task_concurrency_race_condition_fence(concurrency_pool, tlog):
    # Verify that writing values concurrently to distinct slots is safe
    shared_accumulator = {}

    def safe_concurrent_writer(task_id: int):
        # Emulate the lab pattern: separate keys prevent hash table collision
        shared_accumulator[task_id] = threading.get_ident()
        return task_id

    # Fire off high-velocity tasks to stress test internal queue assignment
    workers = [Task.run(safe_concurrent_writer, i) for i in range(100)]

    results = Task.when_all(workers).result()

    assert len(results) == 100
    assert len(shared_accumulator) == 100

def test_task_unhandled_exception_marshaling_chain():
    def throwing_worker():
        raise ZeroDivisionError("Simulated execution failure")

    # Fire an operation destined to explode inside your BackgroundWorkerPool
    failed_task = Task.run(throwing_worker)

    # Verify that your exception handler wraps the trace inside an AggregateError contract
    with pytest.raises(ZeroDivisionError, match="Simulated execution failure"):
        failed_task.result()


def test_Task_result_rejects_blocking_on_runtime_thread() -> None:
    async def runtime_work() -> None:
        pending = Task.delay(10)

        assert not pending.done()

        with pytest.raises(
                RuntimeError,
                match="Task.result\\(\\) would block the runtime thread",
        ):
            pending.result()

    Task.run(runtime_work).result()

def test_twait_RejectsUseInsideAsyncFunction() -> None:
    task = Task.run(lambda: 42)
    assert task.result() == 42

    async def async_caller() -> None:
        with pytest.raises(RuntimeError, match="async"):
            twait >> task

    Task.run(async_caller).result()