from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from flpit.threading import AsyncLocal, AsyncLocalValueChangedArgs
from flpit.task import Task

def test_value_is_isolated_between_execution_contexts():
    local = AsyncLocal[str]()
    local.value = "parent"

    child_context = copy_context()

    def child():
        assert local.value == "parent"
        local.value = "child"
        return local.value

    assert child_context.run(child) == "child"
    assert local.value == "parent"


def test_value_flows_to_another_thread_with_context():
    local = AsyncLocal[str]()
    local.value = "hello"

    context = copy_context()

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            context.run,
            lambda: local.value,
        ).result(timeout=2)

    assert result == "hello"


def test_explicit_value_changes_notify_handler():
    changes = []
    local = AsyncLocal[str](changes.append)

    local.value = "first"
    local.value = "second"

    assert changes == [
        AsyncLocalValueChangedArgs(
            previous_value=None,
            current_value="first",
            thread_context_changed=False,
        ),
        AsyncLocalValueChangedArgs(
            previous_value="first",
            current_value="second",
            thread_context_changed=False,
        ),
    ]

def test_asynclocal_notifies_on_execution_context_transitions():
    changes: list[AsyncLocalValueChangedArgs[str]] = []
    value = AsyncLocal[str](changes.append, default="unset")

    value.value = "parent"

    async def work():
        assert value.value == "parent"

        value.value = "child"
        await Task.delay(0.01)

        assert value.value == "child"

    Task.run(work).result()

    transitions = [
        change
        for change in changes
        if change.thread_context_changed
    ]

    assert any(
        change.previous_value == "unset"
        and change.current_value == "parent"
        for change in transitions
    )

    assert any(
        change.previous_value == "child"
        and change.current_value == "unset"
        for change in transitions
    )

    assert value.value == "parent"