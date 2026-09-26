"""
Fluent LINQ for Python — flip your iterables.
"""
from __future__ import annotations
from importlib.metadata import version
__version__ = version("flpit")

import builtins
from typing import Iterable as _Iterable, TypeVar

from flpit import flp
from flpit.core.linq import (
    FlpIt,
    FlpList,
    Grouping,
    OrderedIt,
    EmptySequenceError,
    NoMatchError,
    MultipleElementsError,
    MultipleMatchesError,
    SourceNoneError,
    PredicateNoneError,
)

__all__ = [
    "FlpIt",
    "FlpList",
    "Grouping",
    "OrderedIt",
    "EmptySequenceError",
    "NoMatchError",
    "MultipleElementsError",
    "MultipleMatchesError",
    "SourceNoneError",
    "PredicateNoneError",
]

