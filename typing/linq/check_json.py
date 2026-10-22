from decimal import Decimal
from io import BytesIO
from typing import assert_type

from flpit.json import JsonSerializerOptions

from flpit import FlpIt, FlpList, Grouping, OrderedIt, flp

NUMBERS: FlpIt[int] = flp.it([1, 2, 3])
NUMBER_LIST: FlpList[int] = flp.lst([1, 2, 3])
JSON_OPTIONS: JsonSerializerOptions | None = None

# ============================================================================
# JSON serialization/deserialization: FlpIt and FlpList
# ============================================================================
# Check both supported input forms (str/bytes), inferred element types from
# from_json, and the concrete return types of every JSON output API. Supplying
# the typed optional options argument also checks that the options parameter
# remains part of the public type contract.

assert_type(FlpIt.from_json("[1, 2, 3]", int), FlpIt[int])
assert_type(FlpIt.from_json(b"[1, 2, 3]", int, JSON_OPTIONS), FlpIt[int])
assert_type(NUMBERS.to_json(int), str)
assert_type(NUMBERS.to_json(int, JSON_OPTIONS), str)
assert_type(NUMBERS.to_json_bytes(int), bytes)
assert_type(NUMBERS.to_json_bytes(int, JSON_OPTIONS), bytes)
assert_type(NUMBERS.write_json(int, BytesIO()), None)
assert_type(NUMBERS.write_json(int, BytesIO(), JSON_OPTIONS), None)

assert_type(FlpList.from_json("[1, 2, 3]", int), FlpList[int])
assert_type(FlpList.from_json(b"[1, 2, 3]", int, JSON_OPTIONS), FlpList[int])
assert_type(NUMBER_LIST.to_json(int), str)
assert_type(NUMBER_LIST.to_json(int, JSON_OPTIONS), str)
assert_type(NUMBER_LIST.to_json_bytes(int), bytes)
assert_type(NUMBER_LIST.to_json_bytes(int, JSON_OPTIONS), bytes)
assert_type(NUMBER_LIST.write_json(int, BytesIO()), None)
assert_type(NUMBER_LIST.write_json(int, BytesIO(), JSON_OPTIONS), None)
