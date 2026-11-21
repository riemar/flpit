"""Typed CSV loading."""
# --8<-- [start:csv]
from dataclasses import dataclass
from typing import Annotated

from flpit.csv import CsvCol, CsvLoader, CsvOptions


@dataclass
class Person:
    name: str
    age: int
    city: Annotated[str, CsvCol("Home Town")]   # the column header differs from the field name


text = "name,age,Home Town\nAda,36,London\nGrace,45,New York\n"

people = CsvLoader.load_list(text, Person)      # eager: a FlpList[Person]
assert people.select(lambda p: p.city).to_list() == ["London", "New York"]

# Lazy: rows are converted one by one as the query is enumerated.
over_forty = CsvLoader.load_it(text, Person).where(lambda p: p.age > 40).select(lambda p: p.name)
assert over_forty.to_list() == ["Grace"]

# Other dialects: pass options.
semicolons = CsvLoader.load_list("name;age;Home Town\nAda;36;London\n", Person, CsvOptions(delimiter=";"))
assert semicolons[0].age == 36
# --8<-- [end:csv]
