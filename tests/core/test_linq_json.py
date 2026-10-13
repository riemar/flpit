from dataclasses import dataclass
from datetime import datetime, date
import json

from flpit import FlpList
from flpit.json import JsonSerializerOptions

@dataclass(slots=True)
class Member:
    id:int
    name:str
    birth_date:date
    joined_on:datetime

    alias:str|None=None


json_bytes = b'''
[
  {
    "id": 1,
    "name": "Alice",
    "alias": null,
    "birthDate": "1990-04-12",
    "joinedOn": "2024-01-15T09:30:00+01:00"
  },
  {
    "id": 2,
    "name": "Bob",
    "alias": "Bobby",
    "birthDate": "1985-11-03",
    "joinedOn": "2024-03-10T14:45:00+01:00"
  },
  {
    "id": 3,
    "name": "Charlie",
    "birthDate": "1998-07-21",
    "joinedOn": "2024-06-20T18:00:00+02:00"
  }
]
'''

def test_roundtrip(tlog):
    data = FlpList.from_json(json_bytes, Member)

    tlog.info(data)

    serialized = data.to_json(Member)

    expected = '[{"id":1,"name":"Alice","birthDate":"1990-04-12","joinedOn":"2024-01-15T09:30:00+01:00"},{"id":2,"name":"Bob","birthDate":"1985-11-03","joinedOn":"2024-03-10T14:45:00+01:00","alias":"Bobby"},{"id":3,"name":"Charlie","birthDate":"1998-07-21","joinedOn":"2024-06-20T18:00:00+02:00"}]'

    assert serialized == expected


def test_roundtrip_filtered(tlog):
    data = FlpList.from_json(json_bytes, Member).where(lambda x: x.id > 1).to_list()

    tlog.info(data)

    serialized = data.to_json(Member)

    expected = '[{"id":2,"name":"Bob","birthDate":"1985-11-03","joinedOn":"2024-03-10T14:45:00+01:00","alias":"Bobby"},{"id":3,"name":"Charlie","birthDate":"1998-07-21","joinedOn":"2024-06-20T18:00:00+02:00"}]'

    assert serialized == expected
