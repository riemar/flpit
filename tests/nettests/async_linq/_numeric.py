"""
.NET numeric projections used by the migrated Sum / Average / Min / Max theories.

Python has one int (int, long), one binary float (float, double) and decimal.Decimal; the nullable
variants (int?, ...) are the same types plus None. Each entry is (label, projection).
"""
from datetime import timedelta
from decimal import Decimal

NON_NULLABLE = [
    ("int", int),
    ("long", int),
    ("float", float),
    ("double", float),
    ("decimal", Decimal),
]
NULLABLE = [(f"{label}?", projection) for label, projection in NON_NULLABLE]
TIMESPAN = ("TimeSpan", lambda i: timedelta(seconds=i))
