"""Every example under ``examples/`` is real code that the docs include.

The docs pull snippets out of these files (see ``mkdocs.yml``), so running
them here is what keeps the documentation honest: if an example breaks, CI breaks.
"""
import runpy
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# Examples that need the outside world are shown in the docs but not run in CI.
NEEDS_NETWORK = {"coro.py"}


def _scripts(folder: str) -> list[Path]:
    return sorted(
        p for p in (EXAMPLES / folder).glob("*.py") if not p.name.startswith("_")
    )


def _run(script: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mirrors `python examples/<folder>/<script>.py`: the script's folder is on sys.path.
    monkeypatch.syspath_prepend(str(script.parent))
    sys.modules.pop("_support", None)  # each folder has its own helper module
    runpy.run_path(str(script), run_name="__main__")


@pytest.mark.parametrize(
    "script",
    _scripts("linq") + _scripts("json") + _scripts("channels") + _scripts("concurrent") + _scripts("threading"),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_example_runs(script: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(script, monkeypatch)


@pytest.mark.task_examples
@pytest.mark.parametrize("script", _scripts("task"), ids=lambda p: p.name)
def test_task_example_runs(script: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if script.name in NEEDS_NETWORK:
        pytest.skip("needs network access")
    _run(script, monkeypatch)
