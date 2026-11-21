"""Benchmark-only area.

Everything under ``benchmarks/`` is marked ``benchmark`` automatically, so it is
excluded from the default test run (see ``addopts`` in pyproject.toml) and CI's
regular test job. Run it explicitly with:

    pytest benchmarks -m benchmark
"""
from __future__ import annotations

import logging

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "benchmarks" in item.path.parts:
            item.add_marker(pytest.mark.benchmark)


@pytest.fixture(params=["FlpIt", "FlpList"])
def flp_type(request: pytest.FixtureRequest):
    from flpit import FlpIt, FlpList

    return {"FlpIt": FlpIt, "FlpList": FlpList}[request.param]


@pytest.fixture
def tlog() -> logging.Logger:

    return logging.getLogger("")
