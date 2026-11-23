// Proves when an async method's body runs relative to its caller (.NET 8, 9, 10).
// No test framework, so it builds offline: each check prints PASS/FAIL, and the exit code is the number of failures.
//
//   dotnet run -f net8.0      dotnet run -f net9.0      dotnet run -f net10.0
//
// lab/task/async_start_order.py runs the same four cases with flpit (@task(inline=True), Task.run).
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.InteropServices;

static class Program
{
    static int failures;

    static void Check(bool ok, string what)
    {
        Console.WriteLine($"  {(ok ? "PASS" : "FAIL")}  {what}");
        if (!ok) failures++;
    }

    static void Spin(int ms) { var sw = Stopwatch.StartNew(); while (sw.ElapsedMilliseconds < ms) { } }

    static int Main()
    {
        // Run on a plain thread with no SynchronizationContext, like a console app or a pool worker.
        SynchronizationContext.SetSynchronizationContext(null);
        Console.WriteLine($"{RuntimeInformation.FrameworkDescription}");

        CallingAsyncMethodsRunsEachPrefixInlineInTurn().GetAwaiter().GetResult();
        AwaitingCompletedWorkDoesNotSuspend();
        ExceptionBeforeFirstAwaitIsCapturedNotThrown();
        TaskRunQueuesEvenAnAsyncLambda();

        Console.WriteLine(failures == 0 ? "ALL PASSED" : $"{failures} FAILED");
        return failures;
    }

    // var a = FooAsync(); var b = BarAsync(); await Task.WhenAll(a, b);
    static async Task CallingAsyncMethodsRunsEachPrefixInlineInTurn()
    {
        Console.WriteLine("1. var a = FooAsync(); var b = BarAsync();");
        var log = new ConcurrentQueue<(string Step, int Thread, long Ms)>();
        var clock = Stopwatch.StartNew();
        void Log(string step) => log.Enqueue((step, Environment.CurrentManagedThreadId, clock.ElapsedMilliseconds));

        async Task FooAsync()
        {
            Log("Foo: start");
            Spin(200);                        // CPU work before the first await
            Log("Foo: before first await");
            await Task.Delay(100);            // first incomplete await
            Log("Foo: after await");
        }

        async Task BarAsync()
        {
            Log("Bar: start");
            await Task.Delay(10);
            Log("Bar: after await");
        }

        Log("caller: before FooAsync()");
        var a = FooAsync();
        Log("caller: FooAsync() returned");
        var b = BarAsync();
        Log("caller: BarAsync() returned");
        await Task.WhenAll(a, b);

        var entries = log.ToArray();
        foreach (var e in entries) Console.WriteLine($"       {e.Ms,4} ms  thread {e.Thread,3}  {e.Step}");
        var steps = entries.Select(e => e.Step).ToArray();
        var prefix = new[]
        {
            "caller: before FooAsync()", "Foo: start", "Foo: before first await",
            "caller: FooAsync() returned", "Bar: start", "caller: BarAsync() returned",
        };
        Check(steps.Take(prefix.Length).SequenceEqual(prefix),
            "Foo runs to its first incomplete await before FooAsync() returns; only then does Bar start");
        int caller = entries[0].Thread;
        Check(entries.Take(prefix.Length).All(e => e.Thread == caller),
            "Foo's and Bar's parts before their first await run on the caller's thread");
        long fooReachedAwait = entries.First(e => e.Step == "Foo: before first await").Ms;
        long barStarted = entries.First(e => e.Step == "Bar: start").Ms;
        Check(barStarted >= fooReachedAwait && barStarted >= 190,
            $"Bar starts only after Foo's 200 ms of CPU work (Bar started at {barStarted} ms)");
        Check(entries.First(e => e.Step == "Bar: after await").Ms < entries.First(e => e.Step == "Foo: after await").Ms,
            "after the first await both are in flight at once (Bar's 10 ms delay finishes before Foo's 100 ms)");
    }

    static void AwaitingCompletedWorkDoesNotSuspend()
    {
        Console.WriteLine("2. awaiting already completed tasks");
        var log = new List<string>();
        async Task<int> M()
        {
            log.Add("M: start");
            await Task.CompletedTask;
            int x = await Task.FromResult(41);
            await Task.Delay(0);              // completes synchronously
            log.Add("M: end");
            return x + 1;
        }
        var t = M();
        log.Add("caller");
        Check(log.SequenceEqual(new[] { "M: start", "M: end", "caller" }) && t.IsCompletedSuccessfully && t.Result == 42,
            "an async method that only awaits completed work has finished when the call returns");
    }

    static void ExceptionBeforeFirstAwaitIsCapturedNotThrown()
    {
        Console.WriteLine("3. exception before the first await");
        async Task Boom() { await Task.CompletedTask; throw new InvalidOperationException("boom"); }
        Task? t = null;
        bool threw = false;
        try { t = Boom(); } catch { threw = true; }
        Check(!threw && t!.IsFaulted && t.Exception!.InnerException is InvalidOperationException,
            "calling does not throw; the returned task is faulted");
    }

    static void TaskRunQueuesEvenAnAsyncLambda()
    {
        Console.WriteLine("4. Task.Run(async () => ...)");
        int caller = Environment.CurrentManagedThreadId;
        int bodyThread = 0;
        using var gate = new ManualResetEventSlim(false);
        var t = Task.Run(async () =>
        {
            bodyThread = Environment.CurrentManagedThreadId;
            gate.Wait();                      // inline, this would deadlock the caller
            await Task.Yield();
        });
        bool returnedBeforeBodyFinished = !t.IsCompleted;
        gate.Set();
        t.GetAwaiter().GetResult();
        Check(returnedBeforeBodyFinished && bodyThread != caller,
            "Task.Run returns at once and runs even the async lambda's first part on the pool");
    }
}
