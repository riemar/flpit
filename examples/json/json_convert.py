"""Typed JSON with JsonConvert."""
# --8<-- [start:json]
from dataclasses import dataclass
from typing import Annotated

from flpit import FlpList
from flpit.json import JIgnore, JProp, JsonConvert


@dataclass
class Person:
    first_name: str
    internal_id: Annotated[str, JProp("id")]
    password: Annotated[str, JIgnore] = ""


person = Person("Ada", "usr-42", "secret")
raw = JsonConvert.serialize(person, Person)
assert raw == '{"firstName":"Ada","id":"usr-42"}'

people_json = """
[
    {"firstName": "Ada", "id": "usr-42"},
    {"firstName": "Grace", "id": "usr-43"}
]
"""
people: FlpList[Person] = FlpList.from_json(people_json, Person)
assert people.select(lambda p: p.first_name).to_list() == ["Ada", "Grace"]
# --8<-- [end:json]
