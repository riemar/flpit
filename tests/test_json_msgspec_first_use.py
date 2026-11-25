"""Threads using a type with JsonConvert for the first time at once must not crash the interpreter.

msgspec 0.22 builds its information for a type on first use; on free-threaded Python, concurrent first uses
crashed with a segmentation fault in msgspec._core (see ``_ensure_type_info``). A crash takes pytest down with
it, so the load runs in a child process and the test checks how that process ended. With the GIL it never
crashed; the test runs there too.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("msgspec")

LOAD = textwrap.dedent("""
    import dataclasses, sys, threading
    from flpit.json import JsonConvert

    rounds, threads, action = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    raw = b'{"itemId": 7, "name": "echo", "tags": ["t"], "inner": {"value": 1}}'
    for r in range(rounds):
        # New types every round: every call of the burst below is a first use.
        Inner = dataclasses.make_dataclass(f"Inner{r}", [("value", int)])
        Item = dataclasses.make_dataclass(
            f"Item{r}", [("item_id", int), ("name", str), ("tags", list[str]), ("inner", Inner)])
        obj = Item(7, "echo", ["t"], Inner(1))
        start = threading.Barrier(threads)
        failures = []

        def work():
            start.wait()
            try:
                for _ in range(20):
                    if action == "deserialize":
                        assert JsonConvert.deserialize(raw, Item) == obj
                    elif action == "deserialize_list":
                        assert JsonConvert.deserialize(b"[" + raw + b"]", list[Item]) == [obj]
                    else:
                        assert JsonConvert.deserialize(JsonConvert.serialize_bytes(obj, Item), Item) == obj
            except BaseException as error:
                failures.append(repr(error))

        workers = [threading.Thread(target=work) for _ in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        assert not failures, failures[:3]
    print("ok")
""")


@pytest.mark.parametrize("action", ["deserialize", "deserialize_list", "round_trip"])
def test_concurrent_first_use_of_a_type_does_not_crash(action: str) -> None:
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", LOAD, "60", "16", action],
                          capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stderr[-3000:]}"
    assert done.stdout.strip() == "ok"
