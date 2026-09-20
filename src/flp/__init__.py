"""
Fluent LINQ for Python — flip your iterables.
"""
from __future__ import annotations

import builtins
from typing import Iterable as _Iterable, TypeVar

from flp.core.linq import Grouping, FlpList, FlpIt, OrderedIt

TItem = TypeVar("TItem")

def it(iterable: _Iterable[TItem]) -> FlpIt[TItem]:
    """shorthand to create a linq query object"""
    return FlpIt(iterable)

def lst(iterable: _Iterable[TItem]) -> FlpList[TItem]:
    """shorthand to create a linq list object"""
    return FlpList(iterable)

# noinspection shadowing-builtins
def range(start: int, count: int) -> FlpIt[int]:
    """Generates a lazy sequence of integral numbers within a specified range."""
    return FlpIt(builtins.range(start, start + count))

def repeat(element: TItem, count: int) -> FlpIt[TItem]:
    """Generates a lazy sequence that contains one repeated value."""
    return FlpIt(element for _ in builtins.range(count))

Iterable = it
List = lst

__all__ = [
    "FlpIt",
    "OrderedIt",
    "Grouping",
    "FlpList",
    "it",
    "lst",
    "Iterable",
    "List",
    "range",
    "repeat",
]
