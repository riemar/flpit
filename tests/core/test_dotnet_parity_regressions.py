"""
Regressions found while migrating the .NET System.Linq.AsyncEnumerable tests; both apply to the
sync operators too and are checked against .NET's documented System.Linq behaviour.
"""
from decimal import Decimal

from flpit import flp


def test_decimal_average_rounds_like_dotnet_instead_of_raising_inexact():
    # .NET: new[] { 2m, 4m, 8m }.Average() == 4.6666666666666666666666666667m
    assert flp.it([Decimal(2), Decimal(4), Decimal(8)]).average() == Decimal("4.6666666666666666666666666667")
    assert flp.lst([Decimal(1), Decimal(2)]).average() == Decimal("1.5")


def test_full_join_unmatched_inner_elements_are_grouped_by_key():
    # .NET FullJoin walks its inner Lookup: unmatched inner rows come grouped by key, in order of
    # first key appearance (None keys preserved as their own group, never matching).
    outer = ["a"]
    inner = ["x1", None, "y", "x2", None]

    def key(s):
        return None if s is None else s[0]

    expected = [("a", None), (None, "x1"), (None, "x2"), (None, None), (None, None), (None, "y")]
    assert [tuple(t) for t in flp.it(outer).full_join(inner, key, key)] == expected

