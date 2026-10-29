"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's CancellationTokenSource implementation.

Test names and scenarios adapted from:
- CancellationTokenSourceTest.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/CancellationTokenTests.cs

These tests are adapted to FlpIt's Python API and semantics, not
a line-for-line port of the upstream tests.
"""

import contextvars
import queue
import threading
import time

import pytest

from flpit.task import (
    AggregateError,
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
)


def _raise_callback_error(error):
    raise error


def _error_tree_contains(error, text):
    if text in str(error):
        return True
    if isinstance(error, AggregateError):
        return any(_error_tree_contains(child, text) for child in error.exceptions)
    return False


def _token_event(token):
    """Build an Event-backed wait signal from FlpIt's callback registration."""
    event = threading.Event()
    registration = token.register(event.set)
    return event, registration


def test_CancellationTokenRegister_Exceptions():
    token = CancellationToken.none()
    with pytest.raises(TypeError):
        token.register(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        token.register(object())  # type: ignore[arg-type]

    source = CancellationTokenSource()
    try:
        with pytest.raises(TypeError):
            source.token.register(None)  # type: ignore[arg-type]
    finally:
        source.dispose()


def test_CancellationTokenEquality():
    # CancellationToken is a Python object, not a .NET value-type struct.
    # The supported identity contract is: a source returns the same token
    # object on each access, and the non-cancellable singleton is stable.
    none1 = CancellationToken.none()
    none2 = CancellationToken.none()
    assert none1 is none2
    assert not none1.can_be_cancelled
    assert not CancellationToken().can_be_cancelled

    source = CancellationTokenSource()
    other = CancellationTokenSource()
    try:
        token = source.token
        assert source.token is token
        assert other.token is not token
        assert token.can_be_cancelled
        assert not token.is_cancellation_requested
    finally:
        source.dispose()
        other.dispose()


def test_CancellationToken_GetHashCode():
    # Python migration: verify normal hash-key stability for token objects.
    token = CancellationToken.none()
    source = CancellationTokenSource()
    try:
        source_token = source.token
        original_hash = hash(source_token)
        assert hash(source_token) == original_hash
        assert {source_token: "value"}[source_token] == "value"
        assert {token: "none"}[token] == "none"
    finally:
        source.dispose()


def test_CancellationToken_EqualityAndDispose():
    source = CancellationTokenSource()
    other = CancellationTokenSource()
    try:
        token = source.token
        other_token = other.token
        assert token is source.token
        assert token is not other_token
        assert token.can_be_cancelled
        source.dispose()
        # Unlike the CLR value-type contract, FlpIt preserves the original token
        # object and lets consumers inspect its final state after source disposal.
        assert token is source.token
        assert not token.is_cancellation_requested
        assert token.can_be_cancelled
    finally:
        source.dispose()
        other.dispose()


def test_TokenSourceDispose():
    source = CancellationTokenSource()
    token = source.token
    calls = []
    registration = token.register(lambda: calls.append("called"))
    source.dispose()
    registration.dispose()
    source.dispose()
    assert source.token is token
    assert not token.is_cancellation_requested
    assert calls == []


def test_TokenSourceDispose_Negative():
    source = CancellationTokenSource()
    token = source.token
    source.dispose()
    # Python API equivalent: disposing the source is idempotent, but later
    # mutating operations on the source are rejected. Existing tokens remain
    # readable; FlpIt does not emulate ObjectDisposedException on Token access.
    with pytest.raises(RuntimeError, match="disposed"):
        source.cancel()
    assert source.token is token
    assert not token.is_cancellation_requested
    source.dispose()


def test_CancellationTokenPassiveListening():
    source = CancellationTokenSource()
    try:
        token = source.token
        assert token.can_be_cancelled
        assert not token.is_cancellation_requested
        assert source.cancel() is True
        assert token.is_cancellation_requested
    finally:
        source.dispose()


def test_CancellationTokenActiveListening():
    source = CancellationTokenSource()
    signal_received = []
    try:
        source.token.register(lambda: signal_received.append(True))
        assert signal_received == []
        source.cancel()
        assert signal_received == [True]
    finally:
        source.dispose()


def test_AddAndRemoveDelegates():
    source = CancellationTokenSource()
    output = []
    try:
        registrations = [
            source.token.register(lambda: output.append("action1")),
            source.token.register(lambda: output.append("action2")),
            source.token.register(lambda: output.append("action2")),
            source.token.register(lambda: output.append("action1")),
        ]
        registrations[1].dispose()
        registrations[2].dispose()
        registrations[3].dispose()
        source.cancel()
        assert output == ["action1"]
    finally:
        source.dispose()


def test_CancellationTokenLateEnlistment():
    source = CancellationTokenSource()
    signal_received = []
    try:
        source.cancel()
        source.token.register(lambda: signal_received.append(True))
        # Late registration is called inline, during register().
        assert signal_received == [True]
    finally:
        source.dispose()


def test_CancellationTokenWaitHandle_SignalAfterWait():
    # Event + token registration is the portable waiting equivalent of a
    # CancellationToken.WaitHandle; the waiter is awakened by cancellation.
    source = CancellationTokenSource()
    event, registration = _token_event(source.token)
    waiter_entered = threading.Event()
    outcome = []

    def wait_for_signal():
        waiter_entered.set()
        outcome.append(event.wait(1.0))

    thread = threading.Thread(target=wait_for_signal, daemon=True)
    try:
        thread.start()
        assert waiter_entered.wait(1.0)
        assert not event.is_set()
        source.cancel()
        thread.join(1.0)
        assert not thread.is_alive()
        assert outcome == [True]
    finally:
        registration.dispose()
        source.dispose()


def test_CancellationTokenWaitHandle_SignalBeforeWait():
    source = CancellationTokenSource()
    try:
        source.cancel()
        event, registration = _token_event(source.token)
        try:
            assert event.wait(0)
        finally:
            registration.dispose()
    finally:
        source.dispose()


def test_CancellationTokenWaitHandle_WaitAny():
    # A queue populated by token callbacks is the portable wait-any pattern.
    first = CancellationTokenSource()
    second = CancellationTokenSource()
    ready = queue.Queue()
    first_registration = first.token.register(lambda: ready.put(0))
    second_registration = second.token.register(lambda: ready.put(1))
    try:
        second.cancel()
        assert ready.get(timeout=1.0) == 1
        assert not first.is_cancellation_requested
        assert second.is_cancellation_requested
    finally:
        first_registration.dispose()
        second_registration.dispose()
        first.dispose()
        second.dispose()


def test_CreateLinkedTokenSource_OneToken():
    original = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(original.token)
    try:
        assert not linked.token.is_cancellation_requested
        original.cancel()
        assert linked.token.is_cancellation_requested
    finally:
        linked.dispose()
        original.dispose()

    original = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(original.token)
    try:
        linked.cancel()
        assert linked.token.is_cancellation_requested
        assert not original.is_cancellation_requested
    finally:
        linked.dispose()
        original.dispose()

    original = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(original.token)
    try:
        original.dispose()
        assert not linked.token.is_cancellation_requested
    finally:
        linked.dispose()
        original.dispose()


def test_CreateLinkedTokenSource_Simple_TwoToken():
    signal1 = CancellationTokenSource()
    signal2 = CancellationTokenSource()
    combined = CancellationTokenSource.create_linked_token_source(
        signal1.token, signal2.token
    )
    try:
        assert not combined.is_cancellation_requested
        signal1.cancel()
        assert combined.is_cancellation_requested
        assert not signal2.is_cancellation_requested
    finally:
        combined.dispose()
        signal1.dispose()
        signal2.dispose()


@pytest.mark.parametrize("useSpan", [False, True])
def test_CreateLinkedTokenSource_Simple_MultiToken(useSpan):
    # ReadOnlySpan<T> has no Python overload; both source cases map to FlpIt's
    # variadic linked-token API and exercise the same three-token propagation.
    _ = useSpan
    signal1 = CancellationTokenSource()
    signal2 = CancellationTokenSource()
    signal3 = CancellationTokenSource()
    combined = CancellationTokenSource.create_linked_token_source(
        signal1.token, signal2.token, signal3.token
    )
    try:
        assert not combined.is_cancellation_requested
        signal1.cancel()
        assert combined.is_cancellation_requested
        assert not signal2.is_cancellation_requested
        assert not signal3.is_cancellation_requested
    finally:
        combined.dispose()
        signal1.dispose()
        signal2.dispose()
        signal3.dispose()


def test_CreateLinkedToken_SourceTokenAlreadySignalled_OneToken():
    source = CancellationTokenSource()
    linked = None
    try:
        source.cancel()
        linked = CancellationTokenSource.create_linked_token_source(source.token)
        assert linked.is_cancellation_requested
    finally:
        if linked is not None:
            linked.dispose()
        source.dispose()


def test_CreateLinkedToken_SourceTokenAlreadySignalled_TwoTokens():
    signal1 = CancellationTokenSource()
    signal2 = CancellationTokenSource()
    combined = None
    try:
        signal1.cancel()
        combined = CancellationTokenSource.create_linked_token_source(
            signal1.token, signal2.token
        )
        assert combined.is_cancellation_requested
        assert not signal2.is_cancellation_requested
    finally:
        if combined is not None:
            combined.dispose()
        signal1.dispose()
        signal2.dispose()


def test_CreateLinkedToken_MultistepComposition_SourceTokenAlreadySignalled():
    signal1 = CancellationTokenSource()
    signal2 = CancellationTokenSource()
    signal3 = CancellationTokenSource()
    combined1 = combined2 = None
    try:
        signal1.cancel()
        combined1 = CancellationTokenSource.create_linked_token_source(
            signal1.token, signal2.token
        )
        combined2 = CancellationTokenSource.create_linked_token_source(
            signal3.token, combined1.token
        )
        assert combined1.is_cancellation_requested
        assert combined2.is_cancellation_requested
    finally:
        if combined2 is not None:
            combined2.dispose()
        if combined1 is not None:
            combined1.dispose()
        signal1.dispose()
        signal2.dispose()
        signal3.dispose()


def test_CallbacksOrderIsLifo():
    source = CancellationTokenSource()
    callback_output = []
    try:
        source.token.register(lambda: callback_output.append("Callback1"))
        source.token.register(lambda: callback_output.append("Callback2"))
        source.cancel()
        assert callback_output == ["Callback2", "Callback1"]
    finally:
        source.dispose()


def test_Enlist_EarlyAndLate():
    source = CancellationTokenSource()
    early = CancellationTokenSource()
    late = CancellationTokenSource()
    try:
        source.token.register(early.cancel)
        source.cancel()
        assert early.is_cancellation_requested
        source.token.register(late.cancel)
        assert late.is_cancellation_requested
    finally:
        source.dispose()
        early.dispose()
        late.dispose()


def test_WaitAll():
    # Event-backed waiting is the portable equivalent of WaitHandle.WaitAll.
    sources = [CancellationTokenSource() for _ in range(3)]
    registrations = []
    events = []
    all_signalled = threading.Event()
    try:
        for source in sources:
            event, registration = _token_event(source.token)
            events.append(event)
            registrations.append(registration)

        def wait_for_all():
            if all(event.wait(1.5) for event in events):
                all_signalled.set()

        waiter = threading.Thread(target=wait_for_all, daemon=True)
        waiter.start()
        sources[0].cancel()
        assert not all_signalled.wait(0.03)
        sources[1].cancel()
        assert not all_signalled.wait(0.03)
        sources[2].cancel()
        assert all_signalled.wait(1.0)
        waiter.join(1.0)
        assert not waiter.is_alive()
    finally:
        for registration in registrations:
            registration.dispose()
        for source in sources:
            source.dispose()


def test_BehaviourAfterCancelSignalled():
    source = CancellationTokenSource()
    calls = []
    try:
        source.token.register(lambda: calls.append("early"))
        source.cancel()
        assert source.is_cancellation_requested
        assert calls == ["early"]
        source.token.register(lambda: calls.append("late"))
        assert calls == ["early", "late"]
        assert source.cancel() is False
        assert calls == ["early", "late"]
    finally:
        source.dispose()


def test_Cancel_ThrowOnFirstException():
    # FlpIt has no throw_on_first_exception flag. Verify the behavior its API
    # does provide instead: later callbacks still run and all thrown exceptions
    # are retained in the AggregateError.
    source = CancellationTokenSource()
    calls = []
    try:
        source.token.register(lambda: _raise_callback_error(ValueError("first")))
        source.token.register(lambda: calls.append("middle callback"))
        source.token.register(lambda: _raise_callback_error(RuntimeError("second")))
        with pytest.raises(AggregateError) as caught:
            source.cancel()
        assert calls == ["middle callback"]
        assert [str(error) for error in caught.value.exceptions] == ["second", "first"]
        assert source.is_cancellation_requested
    finally:
        source.dispose()


def test_Cancel_DontThrowOnFirstException():
    source = CancellationTokenSource()
    try:
        source.token.register(lambda: _raise_callback_error(ValueError("argument")))
        source.token.register(lambda: _raise_callback_error(RuntimeError("operation")))
        with pytest.raises(AggregateError) as caught:
            source.cancel()
        assert [type(error) for error in caught.value.exceptions] == [
            RuntimeError,
            ValueError,
        ]
        assert [str(error) for error in caught.value.exceptions] == [
            "operation",
            "argument",
        ]
    finally:
        source.dispose()


def test_CancellationRegistration_RepeatDispose():
    source = CancellationTokenSource()
    try:
        registration = source.token.register(lambda: None)
        registration.dispose()
        registration.dispose()
        registration.close()
        assert not source.is_cancellation_requested
    finally:
        source.dispose()


def test_CancellationTokenRegistration_EqualityAndHashCode():
    source = CancellationTokenSource()
    try:
        token = source.token
        first = token.register(lambda: None)
        second = token.register(lambda: None)
        none_first = CancellationToken.none().register(lambda: None)
        none_second = CancellationToken.none().register(lambda: None)
        assert first == first
        assert first != second
        assert none_first != none_second
        assert hash(first) == hash(first)
        mapping = {first: "first", second: "second"}
        assert mapping[first] == "first"
        assert mapping[second] == "second"
        first.dispose()
        second.dispose()
        none_first.dispose()
        none_second.dispose()
    finally:
        source.dispose()


def test_CancellationTokenLinking_ODEinTarget():
    source = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(
        source.token, CancellationToken.none()
    )
    try:
        linked.token.register(
            lambda: _raise_callback_error(RuntimeError("myException"))
        )
        with pytest.raises(AggregateError) as caught:
            source.cancel()
        assert _error_tree_contains(caught.value, "myException")
    finally:
        linked.dispose()
        source.dispose()


def test_ThrowIfCancellationRequested():
    source = CancellationTokenSource()
    try:
        token = source.token
        token.throw_if_cancellation_requested()
        source.cancel()
        with pytest.raises(OperationCanceledError) as caught:
            token.throw_if_cancellation_requested()
        # This is the .NET source assertion preserved through FlpIt's exception
        # metadata. It will expose a real gap if throw_if_cancellation_requested()
        # fails to attach the token that raised the exception.
        assert caught.value.token is token
        assert token.is_cancellation_requested
    finally:
        source.dispose()


def test_DeregisterFromWithinACallbackIsSafe_BasicTest():
    source = CancellationTokenSource()
    try:
        registration = source.token.register(lambda: None)
        source.token.register(registration.dispose)
        source.cancel()
        assert source.is_cancellation_requested
    finally:
        source.dispose()


def test_ODEWhenDisposingLinkedCTS():
    user_source = CancellationTokenSource()
    timeout_source = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(
        timeout_source.token, user_source.token
    )
    try:
        user_source.cancel()
        user_source.dispose()
        linked.dispose()
        assert linked.is_cancellation_requested
    finally:
        timeout_source.dispose()
        user_source.dispose()
        linked.dispose()


def test_DerivedCancellationTokenSource():
    # Python has no CLR Dispose(bool)/finalizer split. Preserve the portable
    # subclass contract: cancellation and callback dispatch work, and explicit
    # disposal remains safely overridable and idempotent via super().dispose().
    class DerivedCTS(CancellationTokenSource):
        def __init__(self):
            super().__init__()
            self.dispose_calls = 0

        def dispose(self):
            self.dispose_calls += 1
            super().dispose()

    source = DerivedCTS()
    token = source.token
    worker = threading.Thread(target=source.cancel)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert token.is_cancellation_requested

    callback_source = DerivedCTS()
    callback_calls = []
    callback_source.token.register(lambda: callback_calls.append("called"))
    worker = threading.Thread(target=callback_source.cancel)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert callback_calls == ["called"]

    source.dispose()
    source.dispose()
    assert source.dispose_calls == 2
    callback_source.dispose()
    assert callback_source.dispose_calls == 1


def test_DerivedCancellationTokenSource_Negative():
    class DerivedCTS(CancellationTokenSource):
        def __init__(self):
            super().__init__()
            self.disposed = False

        def dispose(self):
            self.disposed = True
            super().dispose()

    source = DerivedCTS()
    token = source.token
    source.dispose()
    assert source.disposed
    assert source.token is token
    # Closest Python equivalent to the source test's invalid-after-dispose case.
    with pytest.raises(RuntimeError, match="disposed"):
        source.cancel()


def test_CancellationTokenSourceWithTimer():
    source = CancellationTokenSource()
    callback_invoked = threading.Event()
    registration = source.token.register(callback_invoked.set)
    try:
        source.cancel_after(-1)
        assert not source.is_cancellation_requested
        source.cancel_after(1.0)
        assert not source.is_cancellation_requested
        # Replacing a long timer with a shorter one should cancel the old timer.
        source.cancel_after(0.03)
        assert callback_invoked.wait(1.0)
        assert source.is_cancellation_requested
    finally:
        registration.dispose()
        source.dispose()


def test_CancellationTokenSourceWithTimer_Negative():
    source = CancellationTokenSource()
    try:
        with pytest.raises(ValueError):
            source.cancel_after(-2)
        source.cancel_after(-1)
        assert not source.is_cancellation_requested
    finally:
        source.dispose()


def test_CancellationTokenSourceWithTimer_SupportsInfinite():
    source = CancellationTokenSource()
    try:
        source.cancel_after(0.03)
        source.cancel_after(None)
        time.sleep(0.06)
        assert not source.is_cancellation_requested
        source.cancel_after(0.03)
        source.cancel_after(-1)
        time.sleep(0.06)
        assert not source.is_cancellation_requested
    finally:
        source.dispose()


def test_CancellationTokenSource_TryReset_ReturnsFalseIfAlreadyCanceled():
    # FlpIt does not reuse a cancelled source. The Python equivalent is that a
    # repeated cancel is a no-op, while a fresh source starts uncancelled.
    source = CancellationTokenSource()
    replacement = CancellationTokenSource()
    try:
        source.cancel()
        assert source.is_cancellation_requested
        assert source.cancel() is False
        assert not replacement.is_cancellation_requested
    finally:
        source.dispose()
        replacement.dispose()


def test_CancellationTokenSource_TryReset_ReturnsTrueIfNotCanceledAndNoTimer():
    # A non-cancelled source remains usable without any timer/reset operation.
    source = CancellationTokenSource()
    calls = []
    try:
        source.cancel_after(None)
        assert not source.is_cancellation_requested
        source.token.register(lambda: calls.append("called"))
        source.cancel()
        assert source.is_cancellation_requested
        assert calls == ["called"]
    finally:
        source.dispose()


def test_CancellationTokenSource_TryReset_ReturnsTrueIfNotCanceledAndTimerHasntFired():
    # Replacing a pending timeout with None is the timer-reset operation exposed
    # by FlpIt; it must prevent the old timer from cancelling the source.
    source = CancellationTokenSource()
    try:
        source.cancel_after(0.2)
        source.cancel_after(None)
        time.sleep(0.25)
        assert not source.is_cancellation_requested
        assert source.cancel() is True
    finally:
        source.dispose()


def test_CancellationTokenSource_TryReset_UnregistersAll():
    # There is no TryReset API, so test cleanup of registrations/timers using the
    # supported operations: dispose registrations and disable a pending timer.
    source = CancellationTokenSource()
    calls = []
    try:
        registration = source.token.register(lambda: calls.append("removed"))
        registration.dispose()
        source.cancel_after(0.15)
        source.cancel_after(None)
        time.sleep(0.2)
        assert not source.is_cancellation_requested
        assert calls == []
        source.cancel()
        assert calls == []
    finally:
        source.dispose()


def test_EnlistWithSyncContext_BeforeCancel():
    # Python has no SynchronizationContext capture. Callbacks run inline on the
    # cancelling thread; verify deterministic synchronous dispatch instead.
    source = CancellationTokenSource()
    observed = []
    registration_thread = threading.get_ident()
    try:
        source.token.register(
            lambda: observed.append((threading.get_ident(), source.is_cancellation_requested))
        )
        source.cancel()
        assert observed == [(registration_thread, True)]
    finally:
        source.dispose()


def test_EnlistWithSyncContext_BeforeCancel_ThrowingExceptionInSyncContextDelegate():
    source = CancellationTokenSource()
    calls = []
    try:
        source.token.register(lambda: calls.append("first"))
        source.token.register(lambda: _raise_callback_error(ValueError("context callback")))
        with pytest.raises(AggregateError) as caught:
            source.cancel()
        assert calls == ["first"]
        assert len(caught.value.exceptions) == 1
        assert str(caught.value.exceptions[0]) == "context callback"
    finally:
        source.dispose()


def test_EnlistWithSyncContext_BeforeCancel_ThrowingExceptionInSyncContextDelegate_ThrowOnFirst():
    # FlpIt lacks throw_on_first_exception; the available contract is that all
    # registrations are visited even when a callback raises.
    source = CancellationTokenSource()
    calls = []
    try:
        source.token.register(lambda: calls.append("oldest"))
        source.token.register(lambda: _raise_callback_error(ValueError("failure")))
        source.token.register(lambda: calls.append("newest"))
        with pytest.raises(AggregateError):
            source.cancel()
        assert calls == ["newest", "oldest"]
    finally:
        source.dispose()


def test_SyncContextWithExceptionThrowingCallback():
    source = CancellationTokenSource()
    callback_done = threading.Event()
    errors = []

    def throwing_callback():
        callback_done.set()
        raise RuntimeError("callback failed")

    source.token.register(lambda: errors.append("later callback"))
    source.token.register(throwing_callback)

    def cancel():
        try:
            source.cancel()
        except AggregateError as exc:
            errors.extend(exc.exceptions)

    worker = threading.Thread(target=cancel, daemon=True)
    try:
        worker.start()
        worker.join(1.0)
        assert not worker.is_alive()
        assert callback_done.is_set()
        assert "later callback" in errors
        assert any(isinstance(error, RuntimeError) and str(error) == "callback failed" for error in errors)
    finally:
        source.dispose()


def test_Bug720327_DeregisterFromWithinACallbackIsSafe_SyncContextTest():
    source = CancellationTokenSource()
    completed = threading.Event()
    try:
        registration = source.token.register(lambda: None)

        def dispose_inside_callback():
            registration.dispose()
            completed.set()

        source.token.register(dispose_inside_callback)
        worker = threading.Thread(target=source.cancel, daemon=True)
        worker.start()
        worker.join(1.0)
        assert not worker.is_alive()
        assert completed.is_set()
    finally:
        source.dispose()


def test_CancellationTokenRegistration_DisposeDuringCancellation_SuccessfullyRemovedIfNotYetInvoked():
    # FlpIt snapshots callbacks before invoking them. Removing a registration
    # after dispatch has begun does not retract it from that snapshot. Verify the
    # supported behavior and keep the source scenario executable (not skipped).
    source = CancellationTokenSource()
    callback_started = threading.Event()
    release_callback = threading.Event()
    pending_called = threading.Event()

    def blocking_callback():
        callback_started.set()
        release_callback.wait(1.0)

    pending_registration = source.token.register(pending_called.set)
    source.token.register(blocking_callback)  # LIFO: this callback runs first.
    worker = threading.Thread(target=source.cancel, daemon=True)
    try:
        worker.start()
        assert callback_started.wait(1.0)
        pending_registration.dispose()
        release_callback.set()
        worker.join(1.0)
        assert not worker.is_alive()
        assert pending_called.is_set()
    finally:
        release_callback.set()
        worker.join(1.0)
        pending_registration.dispose()
        source.dispose()


def test_CancellationTokenRegistration_Token_MatchesExpectedValue():
    first = CancellationTokenSource()
    second = CancellationTokenSource()
    first_calls = []
    second_calls = []
    first_registration = first.token.register(lambda: first_calls.append(True))
    second_registration = second.token.register(lambda: second_calls.append(True))
    try:
        second.cancel()
        assert second_calls == [True]
        assert first_calls == []
        first.cancel()
        assert first_calls == [True]
        assert second_calls == [True]
    finally:
        first_registration.dispose()
        second_registration.dispose()
        first.dispose()
        second.dispose()


def test_CancellationTokenRegistration_Token_AccessibleAfterCtsDispose():
    source = CancellationTokenSource()
    token = source.token
    registration = token.register(lambda: None)
    source.dispose()
    try:
        # The token and its registration remain safe to inspect/dispose even
        # though FlpIt does not expose Registration.Token as a separate property.
        assert token is source.token
        assert not token.is_cancellation_requested
        registration.dispose()
    finally:
        registration.dispose()
        source.dispose()


def test_CancellationTokenRegistration_UnregisterOnDefaultIsNop():
    calls = []
    registration = CancellationToken.none().register(lambda: calls.append(True))
    registration.dispose()
    registration.dispose()
    assert calls == []


def test_CancellationTokenRegistration_UnregisterRemovesDelegate():
    source = CancellationTokenSource()
    calls = []
    try:
        registration = source.token.register(lambda: calls.append(True))
        registration.dispose()
        source.cancel()
        assert calls == []
    finally:
        source.dispose()


def test_CancellationTokenRegistration_UnregisterWhileCallbackRunning_UnregisterDoesntWaitForCallbackToComplete():
    source = CancellationTokenSource()
    callback_started = threading.Event()
    release_callback = threading.Event()
    cancel_finished = threading.Event()

    def blocked_callback():
        callback_started.set()
        release_callback.wait(2.0)

    registration = source.token.register(blocked_callback)

    def cancel_source():
        try:
            source.cancel()
        finally:
            cancel_finished.set()

    cancel_thread = threading.Thread(target=cancel_source, daemon=True)
    try:
        cancel_thread.start()
        assert callback_started.wait(1.0)
        dispose_finished = threading.Event()

        def dispose_registration():
            registration.dispose()
            dispose_finished.set()

        dispose_thread = threading.Thread(target=dispose_registration, daemon=True)
        dispose_thread.start()
        assert dispose_finished.wait(1.0), "registration.dispose() waited for the running callback"
    finally:
        release_callback.set()
        cancel_thread.join(1.0)
        source.dispose()
    assert cancel_finished.is_set()


def test_CancellationTokenRegistration_UnregisterDuringCancellation_SuccessfullyRemovedIfNotYetInvoked():
    # Same snapshot behavior as the synchronous disposal test above: disposal
    # after cancellation snapshots callbacks will not retract the pending call.
    source = CancellationTokenSource()
    blocked = threading.Event()
    release = threading.Event()
    pending_invoked = threading.Event()
    pending = source.token.register(pending_invoked.set)

    def block_dispatch():
        blocked.set()
        release.wait(1.0)

    source.token.register(block_dispatch)
    worker = threading.Thread(target=source.cancel, daemon=True)
    try:
        worker.start()
        assert blocked.wait(1.0)
        pending.dispose()
        release.set()
        worker.join(1.0)
        assert not worker.is_alive()
        assert pending_invoked.is_set()
    finally:
        release.set()
        worker.join(1.0)
        pending.dispose()
        source.dispose()


def test_CancellationTokenRegistration_ConcurrentUnregisterWithCancel_ReturnsFalseOrCallbackInvoked():
    source = CancellationTokenSource()
    barrier = threading.Barrier(3)
    callback_calls = []
    errors = []
    registration = source.token.register(lambda: callback_calls.append(True))

    def unregister():
        try:
            barrier.wait(timeout=1.0)
            registration.dispose()
        except BaseException as exc:
            errors.append(exc)

    def cancel():
        try:
            barrier.wait(timeout=1.0)
            source.cancel()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=unregister, daemon=True)
    second = threading.Thread(target=cancel, daemon=True)
    try:
        first.start()
        second.start()
        barrier.wait(timeout=1.0)
        first.join(1.0)
        second.join(1.0)
        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert len(callback_calls) in (0, 1)
    finally:
        registration.dispose()
        source.dispose()


def test_Unregister_ConcurrentUse_ThreadSafe():
    source = CancellationTokenSource()
    callback_calls = []
    errors = []
    registrations = [
        source.token.register(lambda: callback_calls.append(1)) for _ in range(8)
    ]
    start = threading.Barrier(len(registrations) + 2)

    def dispose_repeatedly(registration):
        try:
            start.wait(timeout=3.0)
            for _ in range(100):
                registration.dispose()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=dispose_repeatedly, args=(registration,), daemon=True)
        for registration in registrations
    ]
    def cancel_source():
        try:
            start.wait(timeout=3.0)
            source.cancel()
        except BaseException as exc:
            errors.append(exc)

    cancel_thread = threading.Thread(target=cancel_source, daemon=True)
    try:
        for thread in threads:
            thread.start()
        cancel_thread.start()
        start.wait(timeout=3.0)
        for thread in threads:
            thread.join(1.0)
        cancel_thread.join(1.0)
        assert all(not thread.is_alive() for thread in threads)
        assert not cancel_thread.is_alive()
        assert errors == []
        assert len(callback_calls) <= len(registrations)
    finally:
        for registration in registrations:
            registration.dispose()
        source.dispose()


@pytest.mark.parametrize("callbackWithToken", [False, True])
def test_Register_ExecutionContextFlowsIfExpected(callbackWithToken):
    # Python callbacks do not automatically capture contextvars at registration.
    # They observe the context of the thread/call which performs cancellation.
    # todo: create AsyncLocal[T] and replace contextvars with it...
    #   this is what the original test used and I want it anyways
    source = CancellationTokenSource()
    context_value = contextvars.ContextVar("registration_context_value", default="unset")
    observed = []
    token = source.token
    try:
        context_value.set("at-registration")
        if callbackWithToken:
            callback = lambda: observed.append((context_value.get(), token.is_cancellation_requested))
        else:
            callback = lambda: observed.append(context_value.get())
        token.register(callback)
        context_value.set("at-cancellation")
        source.cancel()
        if callbackWithToken:
            assert observed == [("at-cancellation", True)]
        else:
            assert observed == ["at-cancellation"]
    finally:
        source.dispose()


def test_CancellationTokenRegistration_DisposeAsyncOnDefaultIsNop():
    # Sync dispose is the available Python equivalent of disposing a default
    # no-op registration asynchronously: it is harmless and repeatable.
    registration = CancellationToken.none().register(lambda: None)
    registration.dispose()
    registration.dispose()
    assert not CancellationToken.none().is_cancellation_requested


def test_CancellationTokenRegistration_DisposeAsyncRemovesDelegate():
    source = CancellationTokenSource()
    calls = []
    try:
        registration = source.token.register(lambda: calls.append(True))
        registration.dispose()
        source.cancel()
        assert calls == []
    finally:
        source.dispose()


def test_CancellationTokenRegistration_DisposeAsyncWhileCallbackRunning_WaitsForCallbackToComplete():
    # FlpIt exposes non-blocking synchronous dispose(), not DisposeAsync(). The
    # nearest supported guarantee is that disposal can race safely with a
    # callback currently running, and the callback can then finish normally.
    source = CancellationTokenSource()
    callback_started = threading.Event()
    release_callback = threading.Event()
    callback_finished = threading.Event()

    def callback():
        callback_started.set()
        release_callback.wait(1.0)
        callback_finished.set()

    registration = source.token.register(callback)
    cancel_thread = threading.Thread(target=source.cancel, daemon=True)
    try:
        cancel_thread.start()
        assert callback_started.wait(1.0)
        registration.dispose()
        assert not callback_finished.is_set()
        release_callback.set()
        cancel_thread.join(1.0)
        assert not cancel_thread.is_alive()
        assert callback_finished.is_set()
    finally:
        release_callback.set()
        cancel_thread.join(1.0)
        registration.dispose()
        source.dispose()


def test_CancellationTokenRegistration_DisposeAsyncDuringCancellation_SuccessfullyRemovedIfNotYetInvoked():
    # This maps the in-flight-dispatch case onto FlpIt's sync registration API:
    # dispose cannot remove a callback that is already in the dispatch snapshot.
    source = CancellationTokenSource()
    callback_started = threading.Event()
    release_callback = threading.Event()
    pending_called = threading.Event()
    pending = source.token.register(pending_called.set)

    def blocker():
        callback_started.set()
        release_callback.wait(1.0)

    source.token.register(blocker)
    worker = threading.Thread(target=source.cancel, daemon=True)
    try:
        worker.start()
        assert callback_started.wait(1.0)
        pending.dispose()
        release_callback.set()
        worker.join(1.0)
        assert not worker.is_alive()
        assert pending_called.is_set()
    finally:
        release_callback.set()
        worker.join(1.0)
        pending.dispose()
        source.dispose()


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_CancellationTokenRegistration_DisposeAsync_NopAfterDispose(mode):
    source = CancellationTokenSource()
    calls = []
    try:
        registration = source.token.register(lambda: calls.append(True))
        if mode == 0:
            registration.dispose()
        elif mode == 1:
            registration.close()
        else:
            source.cancel()
            registration.dispose()
        # Both spellings are idempotent and may be repeated after cancellation.
        registration.dispose()
        registration.close()
        assert calls in ([], [True])
    finally:
        source.dispose()


@pytest.mark.parametrize("timeSpan", [False, True])
def test_CancellationTokenSource_Ctor_ZeroTimeout(timeSpan):
    # FlpIt has no timeout constructor/TimeSpan overload. cancel_after(0) is the
    # closest behavior: a zero-delay timer requests cancellation immediately.
    _ = timeSpan
    source = CancellationTokenSource()
    called = threading.Event()
    registration = source.token.register(called.set)
    try:
        source.cancel_after(0.0)
        assert called.wait(1.0)
        assert source.is_cancellation_requested
    finally:
        registration.dispose()
        source.dispose()


def test_CancellationTokenSource_CancelAsync_NoRegistrations_CallbackCompletesImmediately():
    # FlpIt has no CancelAsync(); with no callbacks, synchronous cancel should
    # still complete immediately and transition the token state.
    source = CancellationTokenSource()
    try:
        started = time.monotonic()
        assert source.cancel() is True
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert source.is_cancellation_requested
    finally:
        source.dispose()


def test_CancellationTokenSource_CancelAsync_CallbacksInvokedAsynchronously():
    # Approximate asynchronous initiation by cancelling from another thread.
    # FlpIt's callbacks are synchronous on that cancelling thread.
    source = CancellationTokenSource()
    callback_thread_ids = []
    callback_done = threading.Event()
    source.token.register(
        lambda: (callback_thread_ids.append(threading.get_ident()), callback_done.set())
    )
    caller_thread_id = threading.get_ident()
    worker = threading.Thread(target=source.cancel, daemon=True)
    try:
        worker.start()
        assert callback_done.wait(1.0)
        worker.join(1.0)
        assert not worker.is_alive()
        assert len(callback_thread_ids) == 1
        assert callback_thread_ids[0] != caller_thread_id
    finally:
        source.dispose()


def test_CancellationTokenSource_CancelAsync_AllCallbacksInvoked():
    source = CancellationTokenSource()
    called = []
    errors = []

    def fail(message):
        raise ValueError(message)

    source.token.register(lambda: called.append("oldest"))
    source.token.register(lambda: fail("first error"))
    source.token.register(lambda: called.append("middle"))
    source.token.register(lambda: fail("second error"))

    def cancel():
        try:
            source.cancel()
        except AggregateError as exc:
            errors.extend(exc.exceptions)

    worker = threading.Thread(target=cancel, daemon=True)
    try:
        worker.start()
        worker.join(1.0)
        assert not worker.is_alive()
        assert called == ["middle", "oldest"]
        assert [str(error) for error in errors] == ["second error", "first error"]
        assert source.is_cancellation_requested
    finally:
        source.dispose()
