import pytest

import inspect
import socket
import threading
import time


import flpit.task as task_module
from flpit.task import (
    AggregateError,
    BackgroundQueueFull,
    CancellationTokenSource,
    IO,
    OperationCanceledError,
    Task,
)


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

    assert Task.run(child).result(2) == 42


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
            a.result(1)

        assert not second.is_cancellation_requested
        assert not b.done()

        second.cancel()
        with pytest.raises(OperationCanceledError):
            b.result(1)

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
            Task.run(delayed).result(1)
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
        assert task.result(1) == b"x"

        async def wait_forever():
            await IO.wait_readable(reader, token=source.token)

        blocked = Task.run(wait_forever)
        time.sleep(0.02)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            blocked.result(1)
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
            third.result(1)
    finally:
        release.set()

    assert first.result(2) == 1
    assert second.result(2) == 2


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
            task.result(1)
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

    assert aggregate.result(1) == [1, 2]
    assert later_finished.is_set()

    # Passing a single iterable is also supported by the current API.
    assert Task.when_all([Task.run(lambda: 3)]).result(1) == [3]
    assert Task.when_all().result(1) == []


def test_when_all_accepts_raw_coroutines_and_schedules_them():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    raw_fast = value_after(1, 0.01)
    raw_slow = value_after(2, 0.02)
    background = Task.run(lambda: 3)

    assert Task.when_all([raw_fast, raw_slow, background]).result(1) == [1, 2, 3]


def test_when_any_accepts_raw_coroutines():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    winner = Task.when_any(
        [value_after(1, 0.05), value_after(2, 0.01)]
    ).result(1)
    assert winner.result(1) == 2

    # Coroutine objects are one-shot; use fresh ones for another combinator.
    all_results = Task.when_all(
        [value_after(1, 0.02), value_after(2, 0.01)]
    ).result(1)
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
        aggregate.result(1)
    assert other_finished.is_set()


def test_when_all_exposes_multiple_failures():
    def fail(message: str):
        raise ValueError(message)

    aggregate = Task.when_all(Task.run(fail, "one"), Task.run(fail, "two"))
    with pytest.raises(AggregateError) as caught:
        aggregate.result(1)

    assert len(caught.value.exceptions) == 2
    assert {str(error) for error in caught.value.exceptions} == {"one", "two"}


def test_when_any_returns_first_completed_task_without_cancelling_losers():
    async def value_after(value: int, delay: float) -> int:
        await Task.delay(delay)
        return value

    slow = Task.run(value_after, 1, 0.08)
    fast = Task.run(value_after, 2, 0.01)
    winner = Task.when_any(slow, fast).result(1)

    assert winner is fast
    assert winner.result(1) == 2
    assert slow.result(1) == 1

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
        aggregate.result(1)
    assert first.result(1) == 1
    assert second.result(1) == 2


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
        task.result(1)

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
    assert Task.run(lambda: 7).result(1) == 7  # lazy restart works
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