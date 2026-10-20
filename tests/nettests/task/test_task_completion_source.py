"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral pytest port of current dotnet/runtime TaskCompletionSource tests.

Upstream source (current .NET runtime; no Mono sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskCompletionSourceTests.cs

Original PascalCase test names are retained with the ``test_`` prefix.
FlpIt exposes Pythonic snake_case members and does not implement .NET
TaskCreationOptions; the constructor validation test therefore verifies that
unknown .NET-only options are rejected instead of silently ignored.


"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from flpit.task import (
    AggregateError,
    CancellationTokenSource,
    InvalidStateError,
    OperationCanceledError,
    Task,
    TaskCompletionSource,
)


def _assert_completed_tcs_fails_to_complete_again(tcs: TaskCompletionSource[Any]) -> None:
    """Equivalent of .NET's AssertCompletedTcsFailsToCompleteAgain helper."""
    assert tcs.task.done()
    assert not tcs.try_set_result("second result")
    with pytest.raises(InvalidStateError):
        tcs.set_result("second result")

    assert not tcs.try_set_exception(ValueError("second error"))
    with pytest.raises(InvalidStateError):
        tcs.set_exception(ValueError("second error"))

    assert not tcs.try_set_exception([ValueError("a"), TypeError("b")])
    with pytest.raises(InvalidStateError):
        tcs.set_exception([ValueError("a"), TypeError("b")])

    assert not tcs.try_set_canceled()
    with pytest.raises(InvalidStateError):
        tcs.set_canceled()


def _completed_task(value: Any = None) -> Task[Any]:
    task = Task.run(lambda: value)
    task.result()
    return task


def test_Ctor_ArgumentsRoundtrip() -> None:
    tcs = TaskCompletionSource()
    assert tcs.task is not None
    assert tcs.task is tcs.task
    assert tcs.task.status == Task.PENDING
    assert tcs.task.async_state is None

    state = object()
    with_state = TaskCompletionSource(state)
    assert with_state.task is with_state.task
    assert with_state.task.status == Task.PENDING
    assert with_state.task.async_state is state

    # Promise tasks are completed here so this test leaves no pending work.
    assert tcs.try_set_result()
    assert with_state.try_set_result()


def test_Ctor_InvalidArguments_Throws() -> None:
    # The .NET source validates TaskCreationOptions bit combinations. FlpIt has
    # no TaskCreationOptions concept; reject that unsupported keyword explicitly.
    with pytest.raises(TypeError):
        TaskCompletionSource(creation_options=object())  # type: ignore[call-arg]


@pytest.mark.parametrize("try_method", [False, True])
def test_SetResult_CompletesSuccessfully(try_method: bool) -> None:  # type: ignore[no-redef]
    tcs: TaskCompletionSource[None] = TaskCompletionSource()
    assert tcs.task.status == Task.PENDING

    if try_method:
        assert tcs.try_set_result()
    else:
        tcs.set_result()

    assert tcs.task.status == Task.SUCCEEDED
    assert tcs.task.done()
    assert not tcs.task.cancelled()
    assert tcs.task.result() is None
    _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetCanceled_CompletesSuccessfully(try_method: bool) -> None:
    tcs: TaskCompletionSource[None] = TaskCompletionSource()
    assert tcs.task.status == Task.PENDING

    if try_method:
        assert tcs.try_set_canceled()
    else:
        tcs.set_canceled()

    assert tcs.task.status == Task.CANCELLED
    assert tcs.task.done()
    assert tcs.task.cancelled()
    with pytest.raises(OperationCanceledError) as caught:
        tcs.task.result()
    assert caught.value.token is None
    _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetCanceled_Token_CompletesSuccessfully(try_method: bool) -> None:
    with CancellationTokenSource() as cts:
        tcs: TaskCompletionSource[None] = TaskCompletionSource()
        assert tcs.task.status == Task.PENDING

        if try_method:
            assert tcs.try_set_canceled(cts.token)
        else:
            tcs.set_canceled(cts.token)

        assert tcs.task.status == Task.CANCELLED
        with pytest.raises(OperationCanceledError) as caught:
            tcs.task.result()
        assert caught.value.token is cts.token
        _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetException_Exception_CompletesSuccessfully(try_method: bool) -> None:
    error = ValueError("expected exception")
    tcs: TaskCompletionSource[None] = TaskCompletionSource()
    assert tcs.task.status == Task.PENDING

    if try_method:
        assert tcs.try_set_exception(error)
    else:
        tcs.set_exception(error)

    assert tcs.task.status == Task.FAILED
    assert tcs.task.done()

    with pytest.raises(ValueError, match="expected exception") as caught:
        tcs.task.result()

    assert caught.value is error
    _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetException_Enumerable_CompletesSuccessfully(try_method: bool) -> None:
    errors = [ValueError("first"), TypeError("second"), RuntimeError("third")]
    tcs: TaskCompletionSource[None] = TaskCompletionSource()

    if try_method:
        assert tcs.try_set_exception(errors)
    else:
        tcs.set_exception(iter(errors))

    assert tcs.task.status == Task.FAILED

    with pytest.raises(AggregateError) as result_error:
        tcs.task.result()

    assert result_error.value.exceptions == tuple(errors)
    _assert_completed_tcs_fails_to_complete_again(tcs)


def test_SetFromTask_InvalidArgument_Throws() -> None:
    tcs = TaskCompletionSource()
    incomplete_source = TaskCompletionSource()

    with pytest.raises(TypeError, match="must not be None"):
        tcs.set_from_task(None)
    with pytest.raises(ValueError, match="already be completed"):
        tcs.set_from_task(incomplete_source.task)
    assert not tcs.task.done()

    tcs.set_result()
    assert tcs.task.status == Task.SUCCEEDED

    # Input validation still takes precedence after the destination is complete.
    with pytest.raises(TypeError):
        tcs.set_from_task(None)
    with pytest.raises(ValueError):
        tcs.set_from_task(incomplete_source.task)
    assert tcs.task.status == Task.SUCCEEDED
    assert incomplete_source.try_set_canceled()


def test_SetFromTask_AlreadyCompleted_ReturnsFalseOrThrows() -> None:
    destination = TaskCompletionSource()
    destination.set_result()

    success = _completed_task()
    failure_source = TaskCompletionSource()
    failure_source.set_exception(ValueError("source failed"))
    cancellation_source = TaskCompletionSource()
    cancellation_source.set_canceled()

    for source in (success, failure_source.task, cancellation_source.task):
        assert not destination.try_set_from_task(source)
        with pytest.raises(InvalidStateError):
            destination.set_from_task(source)

    assert destination.task.status == Task.SUCCEEDED


@pytest.mark.parametrize("try_method", [False, True])
def test_SetFromTask_CompletedSuccessfully(try_method: bool) -> None:
    source = _completed_task()
    tcs = TaskCompletionSource()

    if try_method:
        assert tcs.try_set_from_task(source)
    else:
        tcs.set_from_task(source)

    assert tcs.task.status == Task.SUCCEEDED
    assert tcs.task.result() is None
    _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetFromTask_Faulted(try_method: bool) -> None:
    errors = [ValueError("format"), ZeroDivisionError("divide")]
    source = TaskCompletionSource()
    source.set_exception(errors)
    tcs = TaskCompletionSource()

    if try_method:
        assert tcs.try_set_from_task(source.task)
    else:
        tcs.set_from_task(source.task)

    assert tcs.task.status == Task.FAILED

    _assert_completed_tcs_fails_to_complete_again(tcs)


@pytest.mark.parametrize("try_method", [False, True])
def test_SetFromTask_Canceled(try_method: bool) -> None:
    with CancellationTokenSource() as cts:
        source = TaskCompletionSource()
        source.set_canceled(cts.token)
        tcs = TaskCompletionSource()

        if try_method:
            assert tcs.try_set_from_task(source.task)
        else:
            tcs.set_from_task(source.task)

        assert tcs.task.status == Task.CANCELLED
        with pytest.raises(OperationCanceledError) as caught:
            tcs.task.result()
        assert caught.value.token is cts.token
        _assert_completed_tcs_fails_to_complete_again(tcs)


def test_TaskCompletionSource_GenericResult() -> None:
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    tcs.set_result(42)
    assert tcs.task.result() == 42


def test_TaskCompletionSource_ExternalThreadCompletionResumesAwaiter() -> None:
    tcs: TaskCompletionSource[str] = TaskCompletionSource()

    async def consumer() -> str:
        return await tcs.task

    consumer_task = Task.run(consumer)
    ready = threading.Event()
    errors: list[BaseException] = []

    def complete() -> None:
        ready.set()
        try:
            tcs.set_result("from thread")
        except BaseException as error:  # capture thread failures for assertion
            errors.append(error)

    worker = threading.Thread(target=complete)
    worker.start()
    assert ready.wait(1)
    worker.join(2)
    assert not worker.is_alive()
    assert not errors
    assert consumer_task.result() == "from thread"


def test_TaskCompletionSource_OnlyOneConcurrentTrySetWins() -> None:
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    worker_count = 12
    barrier = threading.Barrier(worker_count)
    outcomes: list[tuple[int, bool]] = []
    outcomes_lock = threading.Lock()

    def contender(value: int) -> None:
        barrier.wait()
        won = tcs.try_set_result(value)
        with outcomes_lock:
            outcomes.append((value, won))

    workers = [threading.Thread(target=contender, args=(n,)) for n in range(worker_count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(3)
        assert not worker.is_alive()

    winners = [value for value, won in outcomes if won]
    assert len(winners) == 1
    assert sum(won for _, won in outcomes) == 1
    assert tcs.task.result() == winners[0]


def test_TaskCompletionSource_RejectsEmptyOrInvalidExceptionCollections() -> None:
    tcs = TaskCompletionSource()
    with pytest.raises(ValueError, match="must not be empty"):
        tcs.set_exception([])
    with pytest.raises(TypeError, match="only Exception"):
        tcs.set_exception([ValueError("valid"), object()])  # type: ignore[list-item]
    assert not tcs.task.done()
    tcs.set_result()


def test_FlpIt_TaskCompletionSource_BroadcastsCompletionToMultipleAwaiters() -> None:
    """A single promise task can safely resume multiple independent awaiters."""
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    consumer_count = 4
    started_count = 0
    started_lock = threading.Lock()
    all_started = threading.Event()

    async def consumer() -> int:
        nonlocal started_count
        with started_lock:
            started_count += 1
            if started_count == consumer_count:
                all_started.set()
        return await tcs.task

    consumers = [Task.run(consumer) for _ in range(consumer_count)]
    # Wait until the scheduler has advanced every coroutine to the promise wait.
    assert all_started.wait()
    assert tcs.try_set_result(8675309)
    assert [task.result() for task in consumers] == [8675309] * consumer_count


def test_FlpIt_TaskCompletionSource_CompetingCompletionKindsHaveSingleWinner() -> None:
    """Result, exception and cancellation contend for one terminal transition."""
    tcs: TaskCompletionSource[int] = TaskCompletionSource()
    contender_count = 3
    barrier = threading.Barrier(contender_count)
    outcomes: list[tuple[str, bool]] = []
    lock = threading.Lock()

    def compete(kind: str) -> None:
        barrier.wait()
        if kind == "result":
            won = tcs.try_set_result(123)
        elif kind == "exception":
            won = tcs.try_set_exception(ValueError("competing failure"))
        else:
            won = tcs.try_set_canceled()
        with lock:
            outcomes.append((kind, won))

    threads = [
        threading.Thread(target=compete, args=(kind,))
        for kind in ("result", "exception", "cancel")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
        assert not thread.is_alive()

    winners = [kind for kind, won in outcomes if won]
    assert len(winners) == 1
    assert sum(won for _, won in outcomes) == 1
    assert tcs.task.done()
    if winners[0] == "result":
        assert tcs.task.result() == 123
    elif winners[0] == "exception":
        assert isinstance(tcs.task.exception(), ValueError)
    else:
        assert tcs.task.cancelled()
        with pytest.raises(OperationCanceledError):
            tcs.task.result()
