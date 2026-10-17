"""
Example: Native Async/Await Execution Without External Runtimes

This example demonstrates how flpit natively executes and composes standard
Python coroutines. You can call and await an async function directly from
within another async function using pure language features, completely
independent of asyncio or external loop runners.

Key Takeaways:
1. **Direct Native Await**: Use the standard, clean `await function()` syntax
   to block execution sequentially until the child coroutine finishes.
2. **Zero Loop Overhead**: This is a pure flpit execution path. Because no
   asyncio-dependent libraries are used, no background loops or runners are created.
3. **Clean Architecture**: The async/await keywords function as native syntax
   to express execution boundaries cleanly, driven entirely by flpit's runtime.
"""

from flpit.task import Task


async def get_database_value(key: str) -> str:
    """A plain, loop-free async function that returns a value."""
    print(f"Fetching configuration value for key: '{key}'...")
    return f"value_for_{key}"


async def main():
    # JUST A STRAIGHT, SIMPLE AWAIT!
    # No Task.run, no decorators, no loops. Just native execution.
    config_value = await get_database_value("max_retries")

    print(f"Successfully retrieved value: {config_value}")


if __name__ == "__main__":
    # Bootstraps the root execution tree via your main Task runner
    Task.run(main).result()
