"""[InlineData] rows shared by the migrated Except / ExceptBy / Intersect / Union / Concat theories."""
from nettests.async_linq.async_helpers import INT_MAX, INT_MIN

PAIRS = [
    ([], []), ([], [42]), ([42, 43], []), ([1], [2, 3]), ([2, 4, 8], [3, 5]), ([2, 4, 8], [2, 4, 8]),
    ([2, 4, 8], [2, 5, 8]), ([-1, 2, 5, 6, 7, 8], [INT_MIN, INT_MAX]),
]
