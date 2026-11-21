import sys, time, threading, sysconfig
from flpit.task import Task, TaskCompletionSource
N=int(sys.argv[1]) if len(sys.argv)>1 else 2000
async def noop(v=1): return v
async def yielder(k):
    for _ in range(k): await Task.yield_now()
async def chain(d):
    if d==0: return 0
    return 1+await Task.run(chain, d-1)
async def cpu(n):
    s=0
    for i in range(n): s+=i*i
    await Task.yield_now()
    for i in range(n): s+=i*i
    return s
def t(label, fn, reps=3):
    best=1e9
    for _ in range(reps):
        a=time.perf_counter(); fn(); best=min(best,time.perf_counter()-a)
    print(f"{label:38s} {best*1000:9.1f} ms")
async def spawn_all(n):
    return await Task.when_all([Task.run(noop,i) for i in range(n)])
async def yields(n,k):
    await Task.when_all([Task.run(yielder,k) for _ in range(n)])
async def delays(n):
    await Task.when_all([Task.delay(0.01) for _ in range(n)])
async def cpus(n,w):
    await Task.when_all([Task.run(cpu,w) for _ in range(n)])
async def tcs_ping(n):
    for _ in range(n):
        s=TaskCompletionSource(); s.set_result(1); await s.task
def sync(x): return x
async def bg(n):
    for i in range(0,n,64):
        await Task.when_all([Task.run(sync,j) for j in range(64)])
print(sys.version.split()[0], "GIL" if getattr(sys,'_is_gil_enabled',lambda:True)() else "nogil")
try: Task.configure(max_workers=8, max_pending_background=4096)
except Exception: pass
t(f"spawn+when_all {N}", lambda: Task.run(spawn_all,N).result())
t(f"yield {N//10}x50", lambda: Task.run(yields,N//10,50).result())
t(f"chain depth 300", lambda: Task.run(chain,300).result())
t(f"delay {N}", lambda: Task.run(delays,N).result())
t(f"cpu 16 x 200k", lambda: Task.run(cpus,16,200000).result())
t(f"tcs ping {N}", lambda: Task.run(tcs_ping,N).result())
t(f"sync bg {N}", lambda: Task.run(bg,N).result())
t(f"ext run().result() {N//4}", lambda: [Task.run(noop,i).result() for i in range(N//4)])

async def mixed(k, n):
    s=0
    for _ in range(k):
        for i in range(n): s+=i
        await Task.yield_now()
    return s
async def mixed_all(t,k,n):
    await Task.when_all([Task.run(mixed,k,n) for _ in range(t)])
t("cpu slices 16 x 300 awaits", lambda: Task.run(mixed_all,16,300,2000).result())
async def pipeline(n):
    # producer/consumer hand-offs through completion sources
    for _ in range(n):
        s=TaskCompletionSource()
        c=Task.run(lambda s=s: s.set_result(1))
        await s.task; await c
t("tcs handoff via pool 1000", lambda: Task.run(pipeline,1000).result())
