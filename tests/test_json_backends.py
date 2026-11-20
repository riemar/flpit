"""Backend selection and running without msgspec."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import flpit.json as flpit_json

SRC = Path(flpit_json.__file__).resolve().parents[2]


def run_python(code: str, *, block_msgspec: bool = False, env: dict[str, str] | None = None) -> str:
    """Run code in a fresh interpreter; optionally make msgspec unimportable."""
    prelude = ""
    if block_msgspec:
        prelude = textwrap.dedent("""
            import sys
            class _NoMsgspec:
                def find_spec(self, name, path=None, target=None):
                    if name == "msgspec" or name.startswith("msgspec."):
                        raise ImportError("msgspec blocked for this test")
                    return None
            sys.meta_path.insert(0, _NoMsgspec())
        """)
    full_env = {k: v for k, v in os.environ.items() if k != "FLPIT_JSON_BACKEND"}
    full_env.update({"PYTHONPATH": str(SRC), **(env or {})})
    result = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        capture_output=True, text=True, env=full_env, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class TestSelection:
    def test_native_is_always_available(self) -> None:
        assert "native" in flpit_json.available_backends()

    def test_set_and_restore_backend(self) -> None:
        previous = flpit_json.get_backend()
        try:
            flpit_json.set_backend("native")
            assert flpit_json.get_backend() == "native"
            flpit_json.set_backend("auto")
            assert flpit_json.get_backend() == flpit_json.available_backends()[0]
        finally:
            flpit_json.set_backend(previous)

    def test_unknown_backend_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            flpit_json.set_backend("orjson")

    def test_environment_variable_selects_backend(self) -> None:
        out = run_python("import flpit.json as j; print(j.get_backend())",
                         env={"FLPIT_JSON_BACKEND": "native"})
        assert out == "native"


# ---------------------------------------------------------------------------
# Without msgspec
# ---------------------------------------------------------------------------

class TestWithoutMsgspec:
    def test_import_flpit_does_not_load_json_support(self) -> None:
        out = run_python("""
            import sys, flpit
            from flpit import FlpList
            assert FlpList([3, 1, 2]).order_by(lambda x: x).to_list() == [1, 2, 3]
            print("flpit.json" in sys.modules, "msgspec" in sys.modules)
        """)
        assert out == "False False"

    def test_everything_works_on_the_native_backend(self) -> None:
        out = run_python("""
            from dataclasses import dataclass
            import flpit.json as j
            from flpit import FlpList
            from flpit.csv import CsvLoader
            from flpit.task import Task

            @dataclass
            class Item:
                item_name: str
                count: int

            assert j.available_backends() == ("native",)
            assert j.get_backend() == "native"
            items = FlpList.from_json(b'[{"itemName":"a","count":1},{"itemName":"b","count":2}]', Item)
            assert items.select(lambda i: i.count).sum() == 3
            assert items.to_json(Item) == '[{"itemName":"a","count":1},{"itemName":"b","count":2}]'
            assert list(CsvLoader.load_list("item_name,count\\na,1\\n", Item)) == [Item("a", 1)]
            assert Task.run(lambda: 42).result() == 42
            try:
                j.set_backend("msgspec")
            except ImportError:
                print("ok")
        """, block_msgspec=True)
        assert out == "ok"
