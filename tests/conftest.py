from typing import Iterable, Any, Generic, TypeVar, Iterator

import pytest

T = TypeVar("T")


def pytest_configure(config):
    config.option.log_cli = True
    config.option.log_cli_level = "INFO"


class RunOnceEnumerable(Generic[T], Iterable[T]):
    """Wrapper that raises RuntimeError if __iter__ is called more than once."""
    def __init__(self, source: Iterable[T]) -> None:
        self._source = list(source)
        self._accessed = False

    def __iter__(self) -> Iterator[T]:
        if self._accessed:
            pytest.fail("Sequence was enumerated more than once!")
        self._accessed = True
        return iter(self._source)


@pytest.fixture
def run_once():
    """Fixture factory providing single-access iterables."""
    def _create(source: Iterable[Any]) -> RunOnceEnumerable:
        return RunOnceEnumerable(source)
    return _create

class ExecutionTracker:
    """Tracks invocation counts for predicates, selectors, and keys."""
    def __init__(self) -> None:
        self.call_count = 0

    def track(self, func):
        def wrapper(*args, **kwargs):
            self.call_count += 1
            return func(*args, **kwargs)
        return wrapper

@pytest.fixture
def tracker():
    return ExecutionTracker()


class NonCollectionIterable(Generic[T], Iterable[T]):
    """Bare-bones iterable stripping list/collection optimizations."""
    def __init__(self, source: Iterable[T]) -> None:
        self._source = list(source)

    def __iter__(self) -> Iterator[T]:
        for item in self._source:
            yield item

@pytest.fixture
def non_collection():
    """Fixture providing bare-bones non-collection iterables."""
    def _create(source: Iterable[Any]) -> NonCollectionIterable:
        return NonCollectionIterable(source)
    return _create