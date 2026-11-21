"""
Example: ConcurrentQueue, ConcurrentStack and ConcurrentBag

The three thread-safe producer/consumer collections differ in which item a take returns:

    var queue = new ConcurrentQueue<int>(new[] { 1, 2, 3 });   // TryDequeue: oldest first
    var stack = new ConcurrentStack<int>(new[] { 1, 2, 3 });   // TryPop: newest first
    var bag = new ConcurrentBag<int>(new[] { 1, 2, 3 });       // TryTake: this thread's newest,
                                                               // else another thread's oldest

The same in flpit. Key takeaways:
1. **No exceptions for empty**: `try_dequeue` / `try_pop` / `try_take` return
   `(True, item)` or `(False, None)`.
2. **Ranges**: `push_range` / `try_pop_range` move several stack items at once, kept together.
3. **Bag locality**: a thread gets its own items back first, which makes the bag cheap for
   workers that consume what they produce.
"""

from flpit.concurrent import ConcurrentBag, ConcurrentQueue, ConcurrentStack
from flpit.task import Task, TaskCreationOptions


def main() -> None:
    queue = ConcurrentQueue([1, 2, 3])
    stack = ConcurrentStack([1, 2, 3])
    bag = ConcurrentBag([1, 2, 3])

    print("queue:", queue.try_dequeue())  # (True, 1)
    print("stack:", stack.try_pop())      # (True, 3)
    print("bag:  ", bag.try_take())       # (True, 3): this thread's newest

    stolen = Task.run(bag.try_take, creation_options=TaskCreationOptions.LONG_RUNNING).result()
    print("bag from another thread:", stolen)  # (True, 1): someone else's oldest

    stack.push_range([10, 11, 12])
    popped = [0] * 2
    stack.try_pop_range(popped)

    print("popped range:", popped)  # [12, 11]

    while (item := queue.try_dequeue())[0]:
        print("drained:", item[1])

    print("empty queue:", queue.try_dequeue())  # (False, None)


if __name__ == "__main__":
    main()
