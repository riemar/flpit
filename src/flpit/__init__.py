"""
Fluent LINQ for Python — flip your iterables.
"""
from importlib.metadata import version
__version__ = version("flpit")

# noinspection protected-member
from flpit.core._zip import ZipTuple
from flpit.core._join import JoinTuple

from flpit import flp
from flpit.core.linq import (
    FlpIt,
    FlpList,
    # Grouping,
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
    FuncNoneError,
    ResultSelectorNoneError,
    InnerNoneError,
    OuterKeySelectorNoneError,
    InnerKeySelectorNoneError,
    ArgumentOutOfRangeError,
    ArgumentNonNegError,
    ArgumentOutOfBoundsError,
)

from flpit.core._grouping import Grouping

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
    "FuncNoneError",
    "ResultSelectorNoneError",
    "InnerNoneError",
    "OuterKeySelectorNoneError",
    "InnerKeySelectorNoneError",
    "ArgumentOutOfRangeError",
    "ArgumentNonNegError",
    "ArgumentOutOfBoundsError",

    "ZipTuple",
    "JoinTuple",
]

