"""Pytest contract tests for JsonConvert's dataclass-only public API.

All successful serialization/deserialization tests operate on dataclass models.
Primitive, collection, enum, union, literal, and temporal values are exercised as
fields of those models. The dynamic msgspec.Struct representation is treated as
an implementation detail.

Assumptions to align with the implementation:
* The module is importable as ``json_convert``.
* JsonSerializerOptions accepts ``naming_policy``, ``default_handling`` and
  ``unknown_field_handling`` keyword arguments.
* ``JsonConvert.serialize`` is an instance method, as declared in the prompt.
* The expectations around JIgnore/JInclude and default omission are proposed
  public-contract behavior and should be adjusted if your intended contract
  differs.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Literal, get_args, get_origin, Annotated

A = Annotated

import pytest

import flpit
from flpit.json import (
    JIgnore,
    JInclude,
    JProp,
    JsonConvert,
    JsonDefaultHandling,
    JsonNamingPolicy,
    JsonSerializerOptions,
    JsonUnknownFieldHandling, JsonDeserializationError, JsonSerializationError,
)


# ---------------------------------------------------------------------------
# Test models: all supported values are fields on dataclasses
# ---------------------------------------------------------------------------


class Color(str, Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


@dataclass
class PrimitiveModel:
    name: str
    count: int
    enabled: bool
    ratio: float


@dataclass
class PrimitiveValuesModel:
    enabled: bool
    count: int
    ratio: float
    text: str
    payload: bytes
    arbitrary: Any


@dataclass
class NullableModel:
    integer: int | None
    text: str | None


@dataclass
class CollectionModel:
    integers: list[int]
    fixed_tuple: tuple[int, str, bool]
    variadic_tuple: tuple[int, ...]
    mapping: dict[str, int]
    nested_lists: list[list[int]]
    mapping_of_lists: dict[str, list[int]]
    unique_values: set[int]
    frozen_values: frozenset[int]


@dataclass
class AnyValueModel:
    value: Any


@dataclass
class UnionLiteralEnumModel:
    union_value: int | str
    literal_value: Literal["red", "blue"]
    color: Color


@dataclass
class NestedModel:
    label: str
    values: list[int]


@dataclass
class EnvelopeModel:
    child: NestedModel


@dataclass
class RequiredModel:
    value: int
    name: str


@dataclass
class DefaultsModel:
    nullable: str | None = None
    count: int = 0
    enabled: bool = False
    ratio: float = 0.0
    text: str = ""
    items: list[int] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class AnnotationModel:
    display_name: A[str, JProp("displayName")]
    secret: A[str, JIgnore] = ""
    always_emit: A[int, JInclude] = 0


@dataclass
class IgnoreOnlyModel:
    visible: str
    hidden: A[str, JIgnore] = ""


@dataclass
class IncludeOnlyModel:
    count: JInclude[int] = 0
    enabled: JInclude[bool] = False
    text: JInclude[str] = ""
    nullable: JInclude[str | None] = None


@dataclass
class ModelWithAliasedOptional:
    nickname: Annotated[str | None, JProp("nickName")]


@dataclass
class ModelWithAliasedSpecialNotation:
    nickname: JProp[str | None].nickName


@dataclass
class NamingModel:
    firstName: str
    LastName: str


@dataclass
class NamingEdgeModel:
    URLValue: str
    XMLParser: str
    first_name: str
    already_kebab: str


@dataclass
class TemporalModel:
    day: date
    moment: datetime
    clock: time


@dataclass
class DateBox:
    value: date


@dataclass
class DateTimeBox:
    value: datetime


@dataclass
class TimeBox:
    value: time


@dataclass
class RecursiveModel:
    value: int
    child: RecursiveModel | None = None


@dataclass
class ModelWithEnum:
    color: Color


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_options(**kwargs: Any) -> JsonSerializerOptions:
    return JsonSerializerOptions(**kwargs)

# make the calls a bit shorter
deserialize = JsonConvert.deserialize
serialize = JsonConvert.serialize

def assert_same_temporal_value(
        actual: date | datetime | time,
        expected: date | datetime | time,
) -> None:
    """Compare temporal values and explicitly check awareness and UTC offset."""
    assert type(actual) is type(expected)
    assert actual == expected
    if isinstance(expected, (datetime, time)):
        assert actual.utcoffset() == expected.utcoffset()
        assert (actual.tzinfo is None) == (expected.tzinfo is None)
        if expected.tzinfo is not None:
            assert actual.utcoffset() is not None


def _primitive_model_json(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "name": "Ada",
        "count": 3,
        "enabled": True,
        "ratio": 1.5,
    }
    data.update(overrides)
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Dataclass-only API boundary
# ---------------------------------------------------------------------------


class TestDataclassOnlyContract:
    @pytest.mark.parametrize("target", [int, str, bool, float, list[int], dict[str, int], Any])
    def test_deserialization_rejects_non_dataclass_targets(self, target: Any) -> None:
        with pytest.raises((TypeError, ValueError)):
            deserialize("{}", target)

    def test_serialization_rejects_non_dataclass_source(self) -> None:
        with pytest.raises((TypeError, ValueError, AttributeError)):
            serialize({"name": "Ada"}, dict[str, str])

    def test_serialization_rejects_non_dataclass_target(self) -> None:
        value = PrimitiveModel("Ada", 3, True, 1.5)
        with pytest.raises((TypeError, ValueError, AttributeError)):
            serialize(value, dict[str, Any])


# ---------------------------------------------------------------------------
# Primitive and arbitrary JSON values as dataclass fields
# ---------------------------------------------------------------------------


class TestPrimitiveFields:
    def test_deserialize_primitive_fields(self) -> None:
        raw = json.dumps(
            {
                "enabled": True,
                "count": 123456789012345678901234567890,
                "ratio": 1.25e3,
                "text": 'Unicode: café / 東京; quote: " and newline:\n',
                # msgspec's JSON byte representation is base64 text.
                "payload": "aGVsbG8=",
                "arbitrary": {"items": [1, True, None, "x"], "nested": {"n": 2.5}},
            }
        )
        result = deserialize(raw, PrimitiveValuesModel)
        assert result.enabled is True
        assert result.count == 123456789012345678901234567890
        assert result.ratio == 1250.0
        assert result.text == 'Unicode: café / 東京; quote: " and newline:\n'
        assert result.payload == b"hello"
        assert result.arbitrary == {
            "items": [1, True, None, "x"],
            "nested": {"n": 2.5},
        }

    def test_serialize_primitive_fields(self) -> None:
        expected = '{"enabled":false,"count":-42,"ratio":3.125,"text":"olá 世界","payload":"aGVsbG8=","arbitrary":[null,true,4,"x"]}'

        value = PrimitiveValuesModel(
            enabled=False,
            count=-42,
            ratio=3.125,
            text="olá 世界",
            payload=b"hello",
            arbitrary=[None, True, 4, "x"],
        )
        output = serialize(value, PrimitiveValuesModel)
        assert output == expected

    def test_primitive_fields_round_trip(self) -> None:
        value = PrimitiveValuesModel(
            enabled=True,
            count=0,
            ratio=-12.5,
            text='quote=" slash=\\ newline=\n emoji=🧪',
            payload=b"binary payload",
            arbitrary={"n": [1, 2.5, False]},
        )
        result = deserialize(serialize(value, PrimitiveValuesModel), PrimitiveValuesModel)
        assert result == value

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("name", 123),
            ("count", "many"),
            ("enabled", 1),
            ("ratio", "not-a-number"),
        ],
    )
    def test_wrong_primitive_field_type_raises(self, field: str, bad_value: Any) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(_primitive_model_json(**{field: bad_value}), PrimitiveModel)

    def test_nullable_fields_distinguish_null_from_missing(self) -> None:
        result = deserialize('{"integer":null,"text":"hello"}', NullableModel)
        assert result == NullableModel(integer=None, text="hello")

    def test_missing_nullable_field_defaults_to_none(self) -> None:
        data: NullableModel = deserialize('{"integer":42}', NullableModel)

        assert data.integer == 42
        assert data.text is None


    def test_invalid_null_for_non_optional_field_raises(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(_primitive_model_json(name=None), PrimitiveModel)

    def test_utf8_bytes_and_string_json_inputs_are_equivalent(self) -> None:
        raw = '{"name":"Zoë","count":4,"enabled":false,"ratio":0.25}'
        assert deserialize(raw, PrimitiveModel) == deserialize(raw.encode("utf-8"), PrimitiveModel)

    def test_invalid_utf8_json_bytes_raise(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(b"\xff\xfe\xfa", PrimitiveModel)

    @pytest.mark.parametrize("raw", ["", " ", "{", "[1,", '"unterminated', "tru", "nul"])
    def test_malformed_json_raises(self, raw: str) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, PrimitiveModel)

    def test_non_finite_floats_serialize_as_null(self, tlog) -> None:
        for value in (math.nan, math.inf, -math.inf):
            model = PrimitiveModel("x", 1, True, value)
            assert serialize(model, PrimitiveModel) == '{"name":"x","count":1,"enabled":true,"ratio":null}'

# ---------------------------------------------------------------------------
# Collections, nested models, unions, literals, enums, and Any
# ---------------------------------------------------------------------------

class TestCollectionsAndCompoundFields:
    def test_deserialize_collections(self) -> None:
        raw = '''{
  "integers": [1, 2, 3],
  "fixed_tuple": [1, "two", true],
  "variadic_tuple": [4, 5, 6],
  "mapping": {
    "a": 1,
    "b": 2
  },
  "nested_lists": [[1, 2], [3]],
  "mapping_of_lists": {
    "a": [1, 2],
    "b": []
  },
  "unique_values": [3, 1, 2],
  "frozen_values": [4, 2]
}'''
        result = deserialize(raw, CollectionModel, jso=JsonSerializerOptions(naming_policy=JsonNamingPolicy.none))
        assert result.integers == [1, 2, 3]
        assert result.fixed_tuple == (1, "two", True)
        assert result.variadic_tuple == (4, 5, 6)
        assert result.mapping == {"a": 1, "b": 2}
        assert result.nested_lists == [[1, 2], [3]]
        assert result.mapping_of_lists == {"a": [1, 2], "b": []}
        assert result.unique_values == {1, 2, 3}
        assert result.frozen_values == frozenset({2, 4})

    def test_serialize_collections(self) -> None:
        expected = '{"integers":[1,2,3],"fixedTuple":[1,"two",true],"variadicTuple":[4,5],"mapping":{"a":1,"b":2},"nestedLists":[[1,2],[3]],"mappingOfLists":{"a":[1,2]},"uniqueValues":[1,2,3],"frozenValues":[2,4]}'
        value = CollectionModel(
            integers=[1, 2, 3],
            fixed_tuple=(1, "two", True),
            variadic_tuple=(4, 5),
            mapping={"a": 1, "b": 2},
            nested_lists=[[1, 2], [3]],
            mapping_of_lists={"a": [1, 2]},
            unique_values={3, 1, 2},
            frozen_values=frozenset({4, 2}),
        )
        actual = serialize(value, CollectionModel)
        assert actual == expected


    def test_nested_dataclass_round_trip(self) -> None:
        value = EnvelopeModel(child=NestedModel(label="batch", values=[2, 4, 6]))
        assert deserialize(serialize(value, EnvelopeModel), EnvelopeModel) == value

    def test_recursive_dataclass_round_trip(self) -> None:
        value = RecursiveModel(1, RecursiveModel(2, RecursiveModel(3)))
        assert deserialize(serialize(value, RecursiveModel), RecursiveModel) == value

    def test_union_literal_and_enum_fields(self) -> None:
        expected = '{"unionValue":"hello","literalValue":"red","color":"green"}'
        value = UnionLiteralEnumModel(union_value="hello", literal_value="red", color=Color.GREEN)
        raw = serialize(value, UnionLiteralEnumModel)
        assert raw == expected
        assert deserialize(raw, UnionLiteralEnumModel) == value

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('{"value":42}', 42),
            ('{"value":"hello"}', "hello"),
            ('{"value":[1,true,null,"x"]}', [1, True, None, "x"]),
            ('{"value":{"nested":{"n":2.5}}}', {"nested": {"n": 2.5}}),
        ],
    )
    def test_any_field_preserves_json_shape(self, raw: str, expected: Any) -> None:
        result = deserialize(raw, AnyValueModel)
        assert result.value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            '{"integers":[1,"bad"],"fixed_tuple":[1,"x",true],"variadic_tuple":[],"mapping":{},"nested_lists":[],"mapping_of_lists":{},"unique_values":[],"frozen_values":[]}',
            '{"integers":[],"fixed_tuple":[1,"x"],"variadic_tuple":[],"mapping":{},"nested_lists":[],"mapping_of_lists":{},"unique_values":[],"frozen_values":[]}',
            '{"integers":[],"fixed_tuple":[1,"x",true],"variadic_tuple":[],"mapping":{"a":"bad"},"nested_lists":[],"mapping_of_lists":{},"unique_values":[],"frozen_values":[]}',
        ],
    )
    def test_invalid_collection_field_values_raise(self, raw: str) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, CollectionModel)

    def test_invalid_enum_and_literal_fields_raise(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize('{"union_value":1,"literal_value":"green","color":"green"}', UnionLiteralEnumModel)
        with pytest.raises(JsonDeserializationError):
            deserialize('{"union_value":1,"literal_value":"red","color":"yellow"}', UnionLiteralEnumModel)


# ---------------------------------------------------------------------------
# Dataclass model validation
# ---------------------------------------------------------------------------


class TestDataclassModels:
    def test_deserialize_dataclass(self) -> None:
        raw = '{"name":"Ada","count":3,"enabled":true,"ratio":1.5}'
        assert deserialize(raw, PrimitiveModel) == PrimitiveModel("Ada", 3, True, 1.5)

    def test_serialize_dataclass(self) -> None:
        expected = '{"name":"Ada","count":3,"enabled":true,"ratio":1.5}'

        value = PrimitiveModel("Ada", 3, True, 1.5)
        assert serialize(value, type(value)) == expected

    def test_missing_required_model_field_raises(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize('{"value":1}', RequiredModel)

    def test_model_root_must_be_object(self) -> None:
        for raw in ("[]", '"string"', "123", "null"):
            with pytest.raises(JsonDeserializationError):
                deserialize(raw, PrimitiveModel)

    def test_enum_in_model(self) -> None:
        model = ModelWithEnum(Color.GREEN)
        raw = serialize(model, ModelWithEnum)
        assert raw == '{"color":"green"}'
        assert deserialize(raw, ModelWithEnum) == model

    def test_nested_model_type_mismatch_raises(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize('{"child":{"label":123,"values":[1]}}', EnvelopeModel)


# ---------------------------------------------------------------------------
# Annotation metadata: shorthand aliases only in declarations
# ---------------------------------------------------------------------------


class TestAnnotations:
    def test_short_hands_produce_annotated_metadata(self) -> None:
        from typing import get_type_hints

        hints = get_type_hints(AnnotationModel, include_extras=True)
        for field_name in ("display_name", "secret", "always_emit"):
            assert get_origin(hints[field_name]) is not None
            assert get_origin(hints[field_name]).__name__ == "Annotated"

        display_metadata = get_args(hints["display_name"])[1:]
        secret_metadata = get_args(hints["secret"])[1:]
        include_metadata = get_args(hints["always_emit"])[1:]
        assert len(display_metadata) == 1
        assert getattr(display_metadata[0], "json_name", None) == "displayName"
        assert len(secret_metadata) == 1
        assert getattr(secret_metadata[0], "__name__", None) == "JIgnore"
        assert len(include_metadata) == 1
        assert getattr(include_metadata[0], "__name__", None) == "JInclude"

    def test_jprop_renames_field_on_serialization(self) -> None:
        value = AnnotationModel(display_name="Ada", secret="private", always_emit=8)
        result = serialize(value, AnnotationModel)
        assert result == '{"displayName":"Ada","alwaysEmit":8}'

    def test_jprop_renames_field_on_deserialization(self) -> None:
        result = deserialize(
            '{"displayName":"Ada","secret":"from-json","alwaysEmit":7}',
            AnnotationModel,
        )
        assert result == AnnotationModel(display_name="Ada", always_emit=7)


    def test_jprop_renames_field_but_no_fallback(self) -> None:
        result = deserialize(
            '{"displayName":"Ada","secret":"from-json","always_emit":7}',
            AnnotationModel,
        )
        assert result.display_name == "Ada"
        assert result.secret == ""
        assert result.always_emit == 0 # camel selected, not fallback to native name

    def test_jignore_omits_field_from_serialization(self) -> None:
        value = IgnoreOnlyModel(visible="public", hidden="private")
        assert serialize(value, IgnoreOnlyModel) == '{"visible":"public"}'

    def test_jignore_input_field_is_ignored(self) -> None:
        result = deserialize('{"visible":"public","hidden":"attacker"}', IgnoreOnlyModel)
        assert result.visible == "public"
        assert result.hidden in ("", None)

    def test_jinclude_keeps_default_values_when_excluding_defaults(self, tlog) -> None:
        value = IncludeOnlyModel()
        opts = make_options(default_handling=JsonDefaultHandling.exclude)
        jstr = serialize(value, IncludeOnlyModel, jso=opts)
        tlog.info(jstr)
        assert jstr == "{}"

    def test_jprop_applies_to_optional_fields_default(self) -> None:
        value = ModelWithAliasedOptional(nickname=None)
        raw = serialize(value, ModelWithAliasedOptional)
        assert raw == '{}'
        assert deserialize(raw, ModelWithAliasedOptional) == value

    def test_jprop_applies_to_optional_fields(self) -> None:
        value = ModelWithAliasedOptional(nickname="Nicks' the name")
        raw = serialize(value, ModelWithAliasedOptional)
        assert raw == '{"nickName":"Nicks\' the name"}'
        assert deserialize(raw, ModelWithAliasedOptional) == value

    def test_jprop_applies_to_optional_fields_special(self) -> None:
        value = ModelWithAliasedSpecialNotation(nickname="Nicks' the name")
        raw = serialize(value, ModelWithAliasedSpecialNotation)
        assert raw == '{"nickName":"Nicks\' the name"}'
        assert deserialize(raw, ModelWithAliasedSpecialNotation) == value

    def test_ignored_field_does_not_cause_strict_unknown_field_failure(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.disallow)
        with pytest.raises(flpit.json.JsonDeserializationError):
            deserialize('{"visible":"v","hidden":"h"}', IgnoreOnlyModel, opts)



# ---------------------------------------------------------------------------
# Naming policies
# ---------------------------------------------------------------------------


class TestNamingPolicies:
    @pytest.mark.parametrize(
        ("policy", "expected"),
        [
            (JsonNamingPolicy.none, '{"firstName":"Ada","LastName":"Lovelace"}'),
            (JsonNamingPolicy.lower, '{"firstname":"Ada","lastname":"Lovelace"}'),
            (JsonNamingPolicy.upper, '{"FIRSTNAME":"Ada","LASTNAME":"Lovelace"}'),
            (JsonNamingPolicy.camel, '{"firstName":"Ada","lastName":"Lovelace"}'),
            (JsonNamingPolicy.pascal, '{"FirstName":"Ada","LastName":"Lovelace"}'),
            (JsonNamingPolicy.kebap, '{"first-name":"Ada","last-name":"Lovelace"}'),
        ],
    )
    def test_serialization_uses_naming_policy(
            self, policy: JsonNamingPolicy, expected: str
    ) -> None:
        value = NamingModel(firstName="Ada", LastName="Lovelace")
        opts = make_options(naming_policy=policy)
        assert serialize(value, NamingModel, jso=opts) == expected

    @pytest.mark.parametrize(
        ("policy", "raw"),
        [
            (JsonNamingPolicy.none, '{"firstName":"Ada","LastName":"Lovelace"}'),
            (JsonNamingPolicy.lower, '{"firstname":"Ada","lastname":"Lovelace"}'),
            (JsonNamingPolicy.upper, '{"FIRSTNAME":"Ada","LASTNAME":"Lovelace"}'),
            (JsonNamingPolicy.camel, '{"firstName":"Ada","lastName":"Lovelace"}'),
            (JsonNamingPolicy.pascal, '{"FirstName":"Ada","LastName":"Lovelace"}'),
            (JsonNamingPolicy.kebap, '{"first-name":"Ada","last-name":"Lovelace"}'),
        ],
    )
    def test_deserialization_uses_naming_policy(self, policy: JsonNamingPolicy, raw: str) -> None:
        result = deserialize(raw, NamingModel, make_options(naming_policy=policy))
        assert result.firstName == "Ada"
        assert result.LastName == "Lovelace"

    def test_explicit_jprop_name_precedence_over_global_policy(self) -> None:
        value = AnnotationModel(display_name="Ada", secret="private", always_emit=1)
        opts = make_options(naming_policy=JsonNamingPolicy.upper)
        output = serialize(value, AnnotationModel, jso=opts)
        assert "displayName" in output
        assert "DISPLAYNAME" not in output

    def test_naming_policy_applies_recursively(self) -> None:
        value = EnvelopeModel(NestedModel(label="batch", values=[2, 4, 6]))
        opts = make_options(naming_policy=JsonNamingPolicy.kebap)
        assert serialize(value, EnvelopeModel, jso=opts) == '{"child":{"label":"batch","values":[2,4,6]}}'

    def test_naming_policy_edge_cases(self) -> None:
        value = NamingEdgeModel(
            URLValue="url",
            XMLParser="xml",
            first_name="snake",
            already_kebab="kebab",
        )
        # Exact acronym/separator transformations are implementation-specific;
        # this locks in the expected current policy contract for these examples.
        output = serialize(value, NamingEdgeModel, jso=make_options(naming_policy=JsonNamingPolicy.kebap))
        assert output == '{"url-value":"url","xml-parser":"xml","first-name":"snake","already-kebab":"kebab"}'


# ---------------------------------------------------------------------------
# Default value handling
# ---------------------------------------------------------------------------


class TestDefaultHandling:
    def test_include_policy_keeps_all_default_values(self) -> None:
        result = serialize(DefaultsModel(), DefaultsModel, jso=make_options(default_handling=JsonDefaultHandling.include))
        assert result == '{"nullable":null,"count":0,"enabled":false,"ratio":0.0,"text":"","items":[],"attributes":{}}'

    def test_exclude_policy_omits_default_values(self) -> None:
        # Proposed contract: exclude removes null, zero, false, empty text,
        # and empty collections.
        result = serialize(DefaultsModel(), DefaultsModel, jso=make_options(default_handling=JsonDefaultHandling.exclude))
        assert result == '{}'

    def test_exclude_policy_retains_non_default_values(self) -> None:
        value = DefaultsModel(
            nullable="present",
            count=1,
            enabled=True,
            ratio=0.5,
            text="x",
            items=[1],
            attributes={"k": "v"},
        )
        result = serialize(value, DefaultsModel, jso=make_options(default_handling=JsonDefaultHandling.exclude))
        assert result == '{"nullable":"present","count":1,"enabled":true,"ratio":0.5,"text":"x","items":[1],"attributes":{"k":"v"}}'

    def test_default_handling_does_not_change_deserialization(self) -> None:
        opts = make_options(default_handling=JsonDefaultHandling.exclude)
        result = deserialize(
            '{"nullable":null,"count":0,"enabled":false,"ratio":0.0,"text":""}',
            DefaultsModel,
            opts,
        )
        assert result.nullable is None
        assert result.count == 0
        assert result.enabled is False
        assert result.ratio == 0.0
        assert result.text == ""
        assert result.items == []
        assert result.attributes == {}


# ---------------------------------------------------------------------------
# Unknown-field handling
# ---------------------------------------------------------------------------


class TestUnknownFieldHandling:
    def test_allow_accepts_unknown_top_level_field(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.allow)
        result = deserialize('{"value":1,"name":"ok","extra":"ignored"}', RequiredModel, opts)
        assert result == RequiredModel(value=1, name="ok")

    def test_disallow_rejects_unknown_top_level_field(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.disallow)
        with pytest.raises(JsonDeserializationError):
            deserialize('{"value":1,"name":"ok","extra":"bad"}', RequiredModel, opts)

    def test_allow_accepts_multiple_unknown_fields(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.allow)
        result = deserialize(
            '{"value":1,"name":"ok","extra1":1,"extra2":2}', RequiredModel, opts
        )
        assert result == RequiredModel(value=1, name="ok")

    def test_disallow_rejects_unknown_nested_field(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.disallow)
        raw = '{"child":{"label":"x","values":[1],"unexpected":true}}'
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, EnvelopeModel, opts)

    def test_known_field_wrong_type_is_not_treated_as_unknown(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.allow)
        with pytest.raises(JsonDeserializationError):
            deserialize('{"value":"not-an-int","name":"ok"}', RequiredModel, opts)

    def test_unknown_field_check_uses_transformed_names(self) -> None:
        opts = make_options(
            naming_policy=JsonNamingPolicy.camel,
            unknown_field_handling=JsonUnknownFieldHandling.disallow,
        )
        result = deserialize('{"firstName":"Ada","lastName":"Lovelace"}', NamingModel, opts)
        assert result.firstName == "Ada"
        assert result.LastName == "Lovelace"

    def test_case_mismatch_is_unknown_in_strict_mode(self) -> None:
        opts = make_options(unknown_field_handling=JsonUnknownFieldHandling.disallow)
        with pytest.raises(JsonDeserializationError):
            deserialize('{"VALUE":1,"name":"x"}', RequiredModel, opts)


# ---------------------------------------------------------------------------
# date, datetime, and time: naive and offset-aware
# ---------------------------------------------------------------------------


class TestDateTimeTypes:
    @pytest.mark.parametrize(
        ("raw", "target", "expected"),
        [
            ('{"value":"2025-06-15"}', DateBox, date(2025, 6, 15)),
            ('{"value":"2024-02-29"}', DateBox, date(2024, 2, 29)),
            ('{"value":"2025-12-31"}', DateBox, date(2025, 12, 31)),
            ('{"value":"2025-06-15T12:30:45"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45)),
            ('{"value":"2025-06-15T12:30:45.123456"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, 123456)),
            ('{"value":"2025-06-15T12:30:45Z"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)),
            ('{"value":"2025-06-15T12:30:45+00:00"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)),
            ('{"value":"2025-06-15T12:30:45+05:30"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            ('{"value":"2025-06-15T12:30:45-07:00"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))),
            ('{"value":"2025-06-15T12:30:45+05:45"}', DateTimeBox, datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=45)))),
            ('{"value":"12:30:45"}', TimeBox, time(12, 30, 45)),
            ('{"value":"00:00:00"}', TimeBox, time(0, 0, 0)),
            ('{"value":"12:30:45.123456"}', TimeBox, time(12, 30, 45, 123456)),
            ('{"value":"12:30:45+00:00"}', TimeBox, time(12, 30, 45, tzinfo=timezone.utc)),
            ('{"value":"12:30:45+05:30"}', TimeBox, time(12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            ('{"value":"12:30:45-07:00"}', TimeBox, time(12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))),
            ('{"value":"12:30:45+05:45"}', TimeBox, time(12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=45)))),
        ],
    )
    def test_deserialize_temporal_field(self, raw: str, target: type[Any], expected: Any) -> None:
        actual = deserialize(raw, target).value
        assert_same_temporal_value(actual, expected)

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (DateBox(date(2025, 6, 15)), date(2025, 6, 15)),
            (DateTimeBox(datetime(2025, 6, 15, 12, 30, 45)), datetime(2025, 6, 15, 12, 30, 45)),
            (DateTimeBox(datetime(2025, 6, 15, 12, 30, 45, 123456)), datetime(2025, 6, 15, 12, 30, 45, 123456)),
            (DateTimeBox(datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)), datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)),
            (DateTimeBox(datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))), datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
            (DateTimeBox(datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))), datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))),
            (TimeBox(time(12, 30, 45)), time(12, 30, 45)),
            (TimeBox(time(12, 30, 45, 123456)), time(12, 30, 45, 123456)),
            (TimeBox(time(12, 30, 45, tzinfo=timezone.utc)), time(12, 30, 45, tzinfo=timezone.utc)),
            (TimeBox(time(12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=45)))), time(12, 30, 45, tzinfo=timezone(timedelta(hours=5, minutes=45)))),
            (TimeBox(time(12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))), time(12, 30, 45, tzinfo=timezone(timedelta(hours=-7)))),
        ],
    )
    def test_serialize_temporal_dataclass_field(self, model: Any, expected: Any) -> None:
        raw = serialize(model, type(model))
        restored = deserialize(raw, type(model)).value
        assert_same_temporal_value(restored, expected)

    @pytest.mark.parametrize(
        ("raw", "target"),
        [
            ('{"value":"2023-02-29"}', DateBox),
            ('{"value":"15/06/2025"}', DateBox),
            ('{"value":"2025-13-01"}', DateBox),
            ('{"value":"2025-06-15T25:30:00"}', DateTimeBox),
            ('{"value":"2025-06-15T12:30:45+25:00"}', DateTimeBox),
            ('{"value":"2025-06-15T12:30:45+99:99"}', DateTimeBox),
            ('{"value":"25:61:00"}', TimeBox),
            ('{"value":"12:30:45+25:00"}', TimeBox),
            ('{"value":"not-a-time"}', TimeBox),
        ],
    )
    def test_invalid_temporal_field_raises(self, raw: str, target: type[Any]) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, target)

    def test_temporal_values_round_trip_inside_model(self) -> None:
        original = TemporalModel(
            day=date(2024, 2, 29),
            moment=datetime(
                2025, 6, 15, 12, 30, 45, 123456,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
            clock=time(8, 15, 30, tzinfo=timezone(timedelta(hours=-7))),
        )
        result = deserialize(serialize(original, TemporalModel), TemporalModel)
        assert result.day == original.day
        assert_same_temporal_value(result.moment, original.moment)
        assert_same_temporal_value(result.clock, original.clock)

    def test_naive_temporals_stay_naive(self) -> None:
        for model_type, model in (
                (DateTimeBox, DateTimeBox(datetime(2025, 1, 2, 3, 4, 5))),
                (TimeBox, TimeBox(time(3, 4, 5))),
        ):
            result = deserialize(serialize(model, model_type), model_type).value
            assert result.tzinfo is None
            assert result.utcoffset() is None


# ---------------------------------------------------------------------------
# Round trips and feature interactions
# ---------------------------------------------------------------------------


class TestRoundTrips:
    @pytest.mark.parametrize(
        "value",
        [
            PrimitiveModel("Ada", 3, True, 1.5),
            NullableModel(None, "x"),
            NestedModel("numbers", [1, 3, 5]),
            EnvelopeModel(NestedModel("nested", [8, 13])),
            UnionLiteralEnumModel(123, "blue", Color.BLUE),
            CollectionModel([1, 2], (3, "x", False), (4, 5), {"a": 1}, [[2]], {"b": [3]}, {1, 2}, frozenset({4, 5})),
            NullableModel(10, None),
            TemporalModel(date(2024, 2, 29), datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc), time(8, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
        ],
    )
    def test_dataclass_round_trip(self, value: Any) -> None:
        raw = serialize(value, type(value))
        json.loads(raw)  # Must be syntactically valid JSON.
        result = deserialize(raw, type(value))
        if isinstance(value, TemporalModel):
            assert result.day == value.day
            assert_same_temporal_value(result.moment, value.moment)
            assert_same_temporal_value(result.clock, value.clock)
        else:
            assert result == value

    def test_deserialize_string_and_utf8_bytes_are_equivalent(self) -> None:
        raw = '{"name":"Ada","count":4,"enabled":false,"ratio":0.25}'
        assert deserialize(raw, PrimitiveModel) == deserialize(raw.encode("utf-8"), PrimitiveModel)

    def test_options_combine_without_corrupting_values(self) -> None:
        @dataclass
        class ConfigModel:
            firstName: str
            count: int = 0

        options = make_options(
            naming_policy=JsonNamingPolicy.kebap,
            default_handling=JsonDefaultHandling.exclude,
            unknown_field_handling=JsonUnknownFieldHandling.disallow,
        )
        original = ConfigModel(firstName="Ada", count=0)
        raw = serialize(original, ConfigModel, jso=options)
        assert raw == '{"first-name":"Ada"}'
        assert deserialize(raw, ConfigModel, options) == original


# ---------------------------------------------------------------------------
# Errors and JSON edge cases
# ---------------------------------------------------------------------------


class TestErrorsAndEdgeCases:
    @pytest.mark.parametrize("raw", ["{}", "[]", '"abc"', "123", "null"])
    def test_incompatible_root_json_type_raises(self, raw: str) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, PrimitiveModel)

    def test_missing_json_input_raises(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(None, PrimitiveModel)  # type: ignore[arg-type]

    def test_duplicate_json_object_keys_have_defined_result(self) -> None:
        # Proposed contract: standard JSON object parsing keeps the last value.
        result = deserialize('{"value":1,"value":2,"name":"x"}', RequiredModel)
        assert result.value == 2

    def test_serializing_circular_dataclass_reference_raises(self) -> None:
        circular = RecursiveModel(value=1)
        circular.child = circular
        with pytest.raises(RecursionError):
            serialize(circular, RecursiveModel)

    def test_extra_input_does_not_change_known_fields_when_allowed(self) -> None:
        options = make_options(unknown_field_handling=JsonUnknownFieldHandling.allow)
        result = deserialize(
            '{"name":"Ada","count":3,"enabled":true,"ratio":1.5,"extra":{"x":1}}',
            PrimitiveModel,
            options,
        )
        assert result == PrimitiveModel("Ada", 3, True, 1.5)

    def test_duplicate_or_conflicting_annotation_names_are_handled(self) -> None:
        # Define the collision behavior explicitly for JProp collisions.
        @dataclass
        class CollidingNamesModel:
            first: JProp[str, "same"]
            second: JProp[str, "same"]

        value = CollidingNamesModel(first="a", second="b")
        with pytest.raises((TypeError, ValueError)):
            serialize(value)

class TestApplyNamingPolicy:

    @pytest.mark.parametrize(
        ("name", "policy", "expected"),
        [
            # None: preserve the original name
            ("firstName", JsonNamingPolicy.none, "firstName"),
            ("XMLParser", JsonNamingPolicy.none, "XMLParser"),
            ("_privateField", JsonNamingPolicy.none, "_privateField"),

            # Lower and upper
            ("firstName", JsonNamingPolicy.lower, "firstname"),
            ("XMLParser", JsonNamingPolicy.lower, "xmlparser"),
            ("firstName", JsonNamingPolicy.upper, "FIRSTNAME"),
            ("XMLParser", JsonNamingPolicy.upper, "XMLPARSER"),
            ("_privateField", JsonNamingPolicy.upper, "_PRIVATEFIELD"),

            # Camel case
            ("first_name", JsonNamingPolicy.camel, "firstName"),
            ("FirstName", JsonNamingPolicy.camel, "firstName"),
            ("XMLParser", JsonNamingPolicy.camel, "xmlParser"),
            ("myHTTPServer", JsonNamingPolicy.camel, "myHttpServer"),
            ("_privateField", JsonNamingPolicy.camel, "_privateField"),

            # Pascal case
            ("first_name", JsonNamingPolicy.pascal, "FirstName"),
            ("firstName", JsonNamingPolicy.pascal, "FirstName"),
            ("XMLParser", JsonNamingPolicy.pascal, "XmlParser"),
            ("myHTTPServer", JsonNamingPolicy.pascal, "MyHttpServer"),
            ("_privateField", JsonNamingPolicy.pascal, "_PrivateField"),

            # Kebab case
            ("firstName", JsonNamingPolicy.kebap, "first-name"),
            ("FirstName", JsonNamingPolicy.kebap, "first-name"),
            ("first_name", JsonNamingPolicy.kebap, "first-name"),
            ("XMLParser", JsonNamingPolicy.kebap, "xml-parser"),
            ("myHTTPServer", JsonNamingPolicy.kebap, "my-http-server"),
            ("already-kebab", JsonNamingPolicy.kebap, "already-kebab"),
            ("_privateField", JsonNamingPolicy.kebap, "_private-field"),
        ],
    )
    def test_apply_naming_policy(
            self,
            name: str,
            policy: JsonNamingPolicy,
            expected: str,
    ) -> None:
        assert flpit.json._apply_naming_policy(name, policy) == expected