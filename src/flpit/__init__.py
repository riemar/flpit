"""
Fluent LINQ for Python — flip your iterables.
"""
from importlib.metadata import version
__version__ = version("flpit")

# noinspection protected-member
from flpit.core._zip import ZipTuple
from flpit.core._join import JoinTuple
from flpit.core._index import IndexTuple

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
    ElementSelectorNoneError,
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
from flpit.core._lookup import Lookup
from flpit.core.async_linq import AsyncEnumerator, AsyncFlpIt, OrderedAsyncIt, async_flpit

__all__ = [
    "flp",
    "FlpIt",
    "FlpList",
    "Grouping",
    "Lookup",
    "OrderedIt",
    "AsyncEnumerator",
    "AsyncFlpIt",
    "OrderedAsyncIt",
    "async_flpit",

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
    "ElementSelectorNoneError",
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
    "IndexTuple",
]

