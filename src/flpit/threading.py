"""Threading and logical execution-context primitives."""

from collections.abc import Callable
from contextvars import Context, ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AsyncLocalValueChangedArgs[T]:
    previous_value: T | None
    current_value: T | None
    thread_context_changed: bool


class AsyncLocal[T]:
    def __init__(
            self,
            value_changed_handler: (
                    Callable[[AsyncLocalValueChangedArgs[T]], None] | None
            ) = None,
            *,
            default: T | None = None,
    ) -> None:
        self._value: ContextVar[T | None] = ContextVar(
            f"flpit.AsyncLocal.{id(self):x}",
            default=default,
        )
        self._value_changed_handler = value_changed_handler

    @property
    def value(self) -> T | None:
        return self._value.get()

    @value.setter
    def value(self, value: T | None) -> None:
        previous_value = self._value.get()

        if previous_value is value:
            return

        self._value.set(value)

        if self._value_changed_handler is None:
            return

        registered = _async_local_change_notifications.get()

        if self not in registered:
            _async_local_change_notifications.set((*registered, self))

        self._notify_change(
            previous_value,
            value,
            thread_context_changed=False,
        )

    def _notify_change(
            self,
            previous_value: T | None,
            current_value: T | None,
            *,
            thread_context_changed: bool,
    ) -> None:
        if previous_value is current_value:
            return

        if self._value_changed_handler is not None:
            self._value_changed_handler(
                AsyncLocalValueChangedArgs(
                    previous_value=previous_value,
                    current_value=current_value,
                    thread_context_changed=thread_context_changed,
                )
            )


# Equivalent to .NET's per-ExecutionContext IAsyncLocal notification list.
_async_local_change_notifications: ContextVar[
    tuple[AsyncLocal[Any], ...]
] = ContextVar(
    "flpit.async_local_change_notifications",
    default=(),
)


def _merge_async_locals(
        previous: tuple[AsyncLocal[Any], ...],
        current: tuple[AsyncLocal[Any], ...],
) -> tuple[AsyncLocal[Any], ...]:
    return tuple(dict.fromkeys((*previous, *current)))


def _notify_context_transition(
        async_locals: tuple[AsyncLocal[Any], ...],
        previous_values: dict[AsyncLocal[Any], Any],
        current_values: dict[AsyncLocal[Any], Any],
) -> None:
    for local in async_locals:
        local._notify_change(
            previous_values[local],
            current_values[local],
            thread_context_changed=True,
        )


def _run_with_context[R](
        context: Context,
        callback: Callable[[], R],
) -> R:
    # Capture the currently active execution context.
    previous_locals = _async_local_change_notifications.get()

    # Obtain the notification registrations belonging to the target context.
    incoming_locals = context.run(_async_local_change_notifications.get)

    transition_locals = _merge_async_locals(
        previous_locals,
        incoming_locals,
    )

    previous_values = {
        local: local.value
        for local in transition_locals
    }

    incoming_values = {
        local: context.run(local._value.get)
        for local in transition_locals
    }

    def enter_context() -> R:
        _notify_context_transition(
            transition_locals,
            previous_values,
            incoming_values,
        )
        return callback()

    try:
        return context.run(enter_context)

    finally:
        # The target context has now exited. Inspect its final values,
        # including AsyncLocal instances registered during callback execution.
        outgoing_locals = context.run(
            _async_local_change_notifications.get
        )

        restored_locals = _async_local_change_notifications.get()

        exit_locals = _merge_async_locals(
            outgoing_locals,
            restored_locals,
        )

        outgoing_values = {
            local: context.run(local._value.get)
            for local in exit_locals
        }

        restored_values = {
            local: local.value
            for local in exit_locals
        }

        _notify_context_transition(
            exit_locals,
            outgoing_values,
            restored_values,
        )