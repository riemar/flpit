"""
Fluent LINQ for Python — flip your iterables.
"""
from __future__ import annotations
from importlib.metadata import version
__version__ = version("flpit")

from flpit import flp
from flpit.core.linq import (
    FlpIt,
    FlpList,
    Grouping,
    OrderedIt,

    #====================
    # InvalidOperationException
    #====================
    InvalidOperationError,
    EmptySequenceError,
    NoMatchError,
    MultipleElementsError,
    MultipleMatchesError,

    #====================
    # ArgumentExceptions
    #====================
    ArgumentError,
    ArgumentNullError,
    SourceNoneError,
    PredicateNoneError,
    CollectionNoneError,
    SelectorNoneError,
    SecondNoneError,
    ArgumentOutOfRangeError,
    ArgumentNonNegError,
    ArgumentOutOfBoundsError
)

__all__ = [
    "flp",
    "FlpIt",
    "FlpList",
    "Grouping",
    "OrderedIt",

    "InvalidOperationError",
    "EmptySequenceError",
    "NoMatchError",
    "MultipleElementsError",
    "MultipleMatchesError",

    "ArgumentError",
    "ArgumentNullError",
    "SourceNoneError",
    "PredicateNoneError",
    "CollectionNoneError",
    "SelectorNoneError",
    "SecondNoneError",
    "ArgumentOutOfRangeError",
    "ArgumentNonNegError",
    "ArgumentOutOfBoundsError",
]

