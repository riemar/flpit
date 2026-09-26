import time
import sys
import tracemalloc



ELEMENTS = 1_000_000

def measure(name: str, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = (time.perf_counter() - start) * 1000
    return result, elapsed

def measure_mem(fn):
    tracemalloc.start()
    result = fn()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, current, peak

print(f"=== FLP Performance Baseline ({ELEMENTS:,} Elements) ===\n")

# --- TEST 1: Lazy Pipeline Efficiency ---

def py_native_lazy():
    data = range(ELEMENTS)
    filtered = (x for x in data if x % 2 == 0)
    mapped = (x * 2 for x in filtered)
    return sum(mapped)

def flp_lazy():

    return (
        flp.range(0, ELEMENTS)
        .where(lambda x: x % 2 == 0)
        .select(lambda x: x * 2)
        .sum()
    )

res_py_lazy, time_py_lazy = measure("Native Generator", py_native_lazy)
res_flp_lazy, time_flp_lazy = measure("FLP LIterable", flp_lazy)

assert res_py_lazy == res_flp_lazy, "Results mismatch!"

print("[1] Lazy Pipeline Overhead")
print(f"  Native Generators : {time_py_lazy:6.2f} ms")
print(f"  FLP LIterable     : {time_flp_lazy:6.2f} ms")
print(f"  Overhead Ratio    : {time_flp_lazy / time_py_lazy:.2f}x\n")


# --- TEST 2: Memory Footprint (Eager vs Lazy) ---


def py_eager_memory():
    return sum(x * 2 for x in range(ELEMENTS) if x % 2 == 0)

    step1 = [x for x in range(ELEMENTS)]
    step2 = [x for x in step1 if x % 2 == 0]
    step3 = [x * 2 for x in step2]
    return sys.getsizeof(step1) + sys.getsizeof(step2) + sys.getsizeof(step3)

def flp_stream_memory():
    # FLP LIterable hält nur den Pipeline-State
    stream = (
        flp.range(0, ELEMENTS)
        .where(lambda x: x % 2 == 0)
        .select(lambda x: x * 2)
        .sum()
    )
    return stream
    return  sys.getsizeof(stream)

result, current, peak = measure_mem(py_eager_memory)
print(result, " - ", current, " - ", peak)
result, current, peak = measure_mem(flp_stream_memory)
print(result, " - ", current, " - ", peak)

# mem_py = py_eager_memory() / (1024 * 1024)
# mem_flp = flp_stream_memory() / 1024

# print("[2] Memory Allocation")
# print(f"  Native Comprehensions (3 Intermediate Lists) : {mem_py:6.2f} MB")
# print(f"  FLP Lazy Stream (State Overhead)             : {mem_flp:6.2f} KB\n")


# --- TEST 3: Materialization Speed (LList Creation) ---

def py_native_list():
    return list(x * 2 for x in range(ELEMENTS) if x % 2 == 0)

def flp_to_list():
    return (
        flp.range(0, ELEMENTS)
        .where(lambda x: x % 2 == 0)
        .select(lambda x: x * 2)
        .to_list()  # bzw. to_array() nach dem Rename
    )

res_py_list, time_py_list = measure("Native list()", py_native_list)
res_flp_list, time_flp_list = measure("FLP .to_list()", flp_to_list)

assert len(res_py_list) == len(res_flp_list), "Length mismatch!"

print("[3] Materialization (.to_list)")
print(f"  Native list(gen)  : {time_py_list:6.2f} ms")
print(f"  FLP .to_list()    : {time_flp_list:6.2f} ms")
print(f"  Overhead Ratio    : {time_flp_list / time_py_list:.2f}x\n")