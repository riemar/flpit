"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

[InlineData] rows shared by the migrated Except / ExceptBy / Intersect / Union / Concat theories.

Taken from the VariousValues_MatchesEnumerable rows, which are the same in ExceptTests.cs, ExceptByTests.cs,
IntersectTests.cs, UnionTests.cs and ConcatTests.cs:
https://github.com/dotnet/runtime/tree/main/src/libraries/System.Linq.AsyncEnumerable/tests
"""
from nettests.async_linq.async_helpers import INT_MAX, INT_MIN

PAIRS = [
    ([], []), ([], [42]), ([42, 43], []), ([1], [2, 3]), ([2, 4, 8], [3, 5]), ([2, 4, 8], [2, 4, 8]),
    ([2, 4, 8], [2, 5, 8]), ([-1, 2, 5, 6, 7, 8], [INT_MIN, INT_MAX]),
]
