from flpit.json import JsonDefaultHandling
import msgspec
from typing import Optional
from dataclasses import dataclass

from flpit.json import (
    JsonSerializerOptions,
    JsonNamingPolicy,
    JIgnore,
    JInclude,
    JProp,
    JsonConvert,
)


@dataclass
class ChildModel:
    child_id: int
    child_name: str


@dataclass
class ComplexTestModel:
    # Shorthand JProp renaming returning Annotated[int, JsonProperty("id")]
    internal_id: JProp[int, "id"]

    # Shorthand ignored field returning Annotated[str, JsonIgnore]
    secret_token: JIgnore[str] = "hidden"

    # Standard field applying naming policy (camelCase)
    first_name: str = "John"

    @property
    def full_name(self) -> JInclude[str]:
        return f"{self.first_name} Doe"

    # Included property with shorthand JProp naming
    @property
    def computed_value(self) -> JProp[str, "customComputed"]:
        return "computed"

    # Underscored internal field explicitly included
    # _private_tracked: JInclude[str] = "tracked_state"
    _private_tracked: JInclude[str] = "tracked_state"

    # Nested dataclass
    child: Optional[ChildModel] = None


def test_encode_with_jprop_and_jignore(tlog):
    model = ComplexTestModel(
        internal_id=42,
        secret_token="should_not_appear",
        first_name="Jane",
        child=ChildModel(child_id=1, child_name="ChildOne")
    )

    options = JsonSerializerOptions(naming_policy=JsonNamingPolicy.camel, default_handling=JsonDefaultHandling.include)
    encoded = JsonConvert.serialize(model, ComplexTestModel, options)

    tlog.info(encoded)

    decoded_json = msgspec.json.decode(encoded)

    tlog.info(decoded_json)
    assert decoded_json["id"] == 42
    assert "secretToken" not in decoded_json
    assert decoded_json["firstName"] == "Jane"
    assert decoded_json["fullName"] == "Jane Doe"
    assert decoded_json["customComputed"] == "computed"
    assert decoded_json["_privateTracked"] == "tracked_state"
    assert decoded_json["child"]["childId"] == 1
    assert decoded_json["child"]["childName"] == "ChildOne"


def test_JsonConvert_deserialize():
    raw_json = b"""
    {
        "id": 100,
        "firstName": "Alice",
        "fullName": "Alice Doe",
        "customComputed": "value",
        "privateTracked": "state",
        "child": {
            "childId": 5,
            "childName": "SubChild"
        }
    }
    """

    options = JsonSerializerOptions(naming_policy=JsonNamingPolicy.camel)
    instance = JsonConvert.deserialize(raw_json, ComplexTestModel, options)

    assert isinstance(instance, ComplexTestModel)
    assert instance.internal_id == 100
    assert instance.first_name == "Alice"
    assert instance.child.child_id == 5
    assert instance.child.child_name == "SubChild"


def test_native_mode(tlog):
    @dataclass
    class NativeTestModel:
        name: JProp[str, "fullName"]

    options = JsonSerializerOptions(native=True)
    raw_json = b'{"fullName": "Test Native"}'

    native_struct = JsonConvert.deserialize(raw_json, NativeTestModel, options)

    # native pretends to be the real thing
    fq_name = f"{native_struct.__class__.__module__}.{native_struct.__class__.__name__}"
    assert fq_name == "tests.test_json.NativeTestModel"

    assert str(type(native_struct)) == "<class 'flpit.json._generated.tests.test_json.NativeTestModel'>"

    assert isinstance(native_struct, NativeTestModel)
    assert native_struct.name == "Test Native"


def test_init_false_field_is_serialized_but_not_passed_to_init(tlog):
    from dataclasses import dataclass

    @dataclass
    class Example:
        _value_ding: JInclude[int]

        # computed: int = field(init=False, default=42)
        _some_backing_filed: JInclude[int] = 11
        @property
        def ValueProp(self) -> JProp[int, "aLiAs"]:
            return self._some_backing_filed

        @ValueProp.setter
        def ValueProp(self, val) -> int:
            self._some_backing_filed = val / 2

    obj = Example(_value_ding=1)

    jso = JsonSerializerOptions(naming_policy=JsonNamingPolicy.camel)

    jstr = JsonConvert.serialize(obj, Example, jso)
    de_str = jstr.replace("11", "22")
    tlog.info(de_str)
    de = JsonConvert.deserialize(de_str, Example, jso)
    print(dir(de))
    de.ValueProp = 44
    from dataclasses import replace
    nde = JsonConvert.deserialize(jstr.replace("11", "33"), Example, replace(jso, native=True))
    print(dir(nde))
    nde.ValueProp = 44

    tlog.info(f"json: {jstr}")
    # tlog.info(obj)
    tlog.info(de.ValueProp)
    tlog.info(nde.ValueProp)
