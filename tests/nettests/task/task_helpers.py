"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Helpers shared by the Task tests ported from dotnet/runtime.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from flpit.core.linq import InvalidOperationError
from flpit.task import (
    AggregateError,
    CancellationToken,
    Task,
    TaskCanceledError,
    TaskCompletionSource,
    TaskContinuationOptions,
)


class ColdTask:
    """Stand-in for an unstarted .NET task: ``new Task(action[, token])`` ... ``t.Start()``.

    FlpIt has no unstarted tasks, by design. Upstream tests create them so that
    continuations are attached before the antecedent can run. ``task`` provides that:
    it stays pending until ``start()``, which runs ``action`` with ``Task.run`` and gives
    ``task`` the same outcome (result, exception or cancellation). Like an unstarted
    .NET task created with a token, it is canceled as soon as that token is cancelled.
    ``task`` is backed by a TaskCompletionSource, so a pending one occupies no worker.
    """

    def __init__(self, action: Callable[[], Any], token: CancellationToken | None = None) -> None:
        self._source: TaskCompletionSource[Any] = TaskCompletionSource()
        self.task: Task[Any] = self._source.task
        self._action = action
        if token is not None:
            token.register(lambda: self._source.try_set_canceled(token))

    def start(self) -> None:
        if self.task.done():
            # .NET: "Start may not be called on a task that has completed."
            raise InvalidOperationError("Start may not be called on a task that has completed.")
        # Not EXECUTE_SYNCHRONOUSLY: if the action already finished, that would complete
        # ``task`` (and run its synchronous continuations) on the thread calling start(),
        # which .NET's Task.Start never does. The pool completes it instead.
        Task.run(self._action).continue_with(self._source.try_set_from_task)


def EnsureTaskCanceledExceptionThrown(action: Callable[[], Any], message: str) -> None:
    """Ensures that the specified action throws an AggregateException wrapping a TaskCanceledException."""
    exception: Exception | None = None
    try:
        action()
    except Exception as ex:
        exception = ex
    EnsureExceptionIsAEofTCE(exception, message)


def EnsureExceptionIsAEofTCE(exception: Exception | None, message: str) -> None:
    """Ensures that the specified exception is an AggregateException wrapping a TaskCanceledException."""
    if exception is None:
        pytest.fail(message + " (no exception thrown)")
    elif type(exception) is not AggregateError:
        pytest.fail(message + " (didn't throw aggregate exception)")
    elif type(exception.exceptions[0]) is not TaskCanceledError:
        pytest.fail(message + f" (threw {type(exception.exceptions[0]).__name__} instead of TaskCanceledException)")
