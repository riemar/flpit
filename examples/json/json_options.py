"""JSON naming, defaults and custom types."""
# --8<-- [start:options]
from dataclasses import dataclass

from flpit.json import JsonConvert, JsonNamingPolicy, JsonSerializerOptions


@dataclass
class Person:
    first_name: str
    nick_name: str = ""


ada = Person("Ada")

# Defaults: camel case, and fields that still hold their default value are left out.
assert JsonConvert.serialize(ada, Person) == '{"firstName":"Ada"}'

snake = JsonSerializerOptions(naming_policy=JsonNamingPolicy.none)
assert JsonConvert.serialize(ada, Person, snake) == '{"first_name":"Ada"}'
# --8<-- [end:options]

# --8<-- [start:custom_type]
from flpit.json import register_type


class Money:
    def __init__(self, cents: int) -> None:
        self.cents = cents

    @classmethod
    def parse(cls, text: str) -> "Money":
        return cls(round(float(text.removeprefix("$")) * 100))

    def format(self) -> str:
        return f"${self.cents / 100:.2f}"


register_type(Money, decode=Money.parse, encode=Money.format)   # stored as one JSON string


@dataclass
class Invoice:
    total: Money


raw = JsonConvert.serialize(Invoice(Money(1250)), Invoice)
assert raw == '{"total":"$12.50"}'
assert JsonConvert.deserialize(raw, Invoice).total.cents == 1250
# --8<-- [end:custom_type]
