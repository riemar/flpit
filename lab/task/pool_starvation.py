import time
from flpit.task import task, Task

# Limit the pipeline artificially to force the bottleneck
MAX_WORKERS = 4
SABOTEUR_TASKS = 10
Task.configure(max_workers=MAX_WORKERS, max_pending_background=128)

@task
def blocking_saboteur(task_id: int):
    """Simulates the 'completely safe... until it isn't' legacy blocking behavior."""
    # Instead of relying on print's automatic trailing newline:
    print(f"[Saboteur #{task_id}] Holding a native OS thread hostage...\n", end="")
    time.sleep(3.0)  # Intentionally occupying the worker thread
    print(f"[Saboteur #{task_id}] Thread released.\n", end="")
    return True

@task
def innocent_victim():
    """An ultra-light task that will starve in the queue due to pool saturation."""
    print("[Victim] Finally executed!")
    return "Survived"

async def main():
    print(f"=== STARTING THREAD POOL EXHAUSTION TEST (Max Workers: {MAX_WORKERS}) ===")

    # 1. Saturate the entire pool immediately via eager execution
    print(f"Spawning {MAX_WORKERS} saboteurs to completely fill the pool...")
    for i in range(SABOTEUR_TASKS):
        _ = blocking_saboteur(i)

    # give the tasks a chance to strat
    await Task.delay(0)

    # 2. Dispatch the victim task. It will sit in the queue because the pool is full.
    print("Spawn innocent victim (should freeze until a saboteur finishes)...")
    start_time = time.perf_counter()

    victim_task = innocent_victim()

    # 3. Measure the starvation latency induced by the synchronous sleep
    result = await victim_task
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"=== TEST COMPLETE ===")
    print(f"Victim task resolved after {duration:.4f} seconds with result: '{result}'")

    if duration > 2.5:
        print("-> SUCCESS: Thread Pool Starvation successfully demonstrated!")
    else:
        print("-> FAILURE: Pool was not completely exhausted.")

if __name__ == "__main__":
    Task.run(main).result()
