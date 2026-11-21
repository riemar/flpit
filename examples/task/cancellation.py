"""Cooperative cancellation, in short."""
import time

# --8<-- [start:cooperative]
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task


def work(token: CancellationToken) -> None:
    while True:
        token.throw_if_cancellation_requested()   # the cooperative check
        time.sleep(0.01)


cts = CancellationTokenSource()
running = Task.run(work, cts.token)

cts.cancel()                                      # or cts.cancel_after(seconds) for a timeout
try:
    running.result()
except OperationCanceledError:
    pass

assert running.status == "cancelled"
# --8<-- [end:cooperative]

# --8<-- [start:callback]
log: list[str] = []

cts = CancellationTokenSource()
registration = cts.token.register(lambda: log.append("cleanup"))   # runs when cancelled

cts.cancel()
assert log == ["cleanup"]
# --8<-- [end:callback]

# --8<-- [start:linked]
user = CancellationTokenSource()
timeout = CancellationTokenSource()
either = CancellationTokenSource.create_linked_token_source(user.token, timeout.token)

timeout.cancel()
assert either.token.is_cancellation_requested     # cancelled by whichever fires first
# --8<-- [end:linked]
