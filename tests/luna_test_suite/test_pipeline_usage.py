from __future__ import annotations

from dataclasses import dataclass
from flpit import flp

@dataclass(frozen=True)
class RawRecord:
    device_id: str
    timestamp: int
    temperature: float
    humidity: float


@dataclass(frozen=True)
class Measurement:
    timestamp: int
    temperature: float
    humidity: float


@dataclass(frozen=True)
class DevicePayload:
    device_id: str
    measurements: tuple[Measurement, ...]


def test_realistic_chunk_to_nested_payload_pipeline() -> None:
    chunk = [
        RawRecord("A", 1, 20.0, 40.0),
        RawRecord("A", 2, 21.0, 41.0),
        RawRecord("B", 1, 10.0, 30.0),
    ]

    payloads = (
        flp.it(chunk)
        .group_by(lambda row: row.device_id)
        .select(
            lambda group: DevicePayload(
                device_id=group.key,
                measurements=tuple(
                    group.order_by(lambda row: row.timestamp)
                    .select(lambda row: Measurement(row.timestamp, row.temperature, row.humidity))
                ),
            )
        )
        .to_list()
    )

    assert payloads == [
        DevicePayload(
            "A",
            (Measurement(1, 20.0, 40.0), Measurement(2, 21.0, 41.0)),
        ),
        DevicePayload("B", (Measurement(1, 10.0, 30.0),)),
    ]


def test_chunked_processing_is_independent_of_chunk_size() -> None:
    records = [RawRecord("A", i, float(i), float(i * 2)) for i in range(7)]

    def process(chunks):
        return tuple(
            flp.it(chunks)
            .select(lambda row: Measurement(row.timestamp, row.temperature, row.humidity))
        )

    for size in [1, 2, 3, 7, 10]:
        chunks = flp.it(records).chunk(size)
        flattened = flp.it(chunks).select_many(lambda chunk: process(chunk))
        assert tuple(flattened) == tuple(
            Measurement(r.timestamp, r.temperature, r.humidity) for r in records
        )


def test_virtual_in_memory_aggregation_is_expressible() -> None:
    values = [
        ("A", 1.0),
        ("B", 5.0),
        ("A", 2.5),
        ("B", 1.5),
    ]

    aggregates = (
        flp.it(values)
        .group_by(lambda pair: pair[0])
        .select(lambda group: (group.key, group.sum(lambda pair: pair[1])))
        .to_list()
    )

    assert aggregates == [("A", 3.5), ("B", 6.5)]


def test_mapping_like_definition_can_drive_chunk_generation() -> None:
    definitions = [
        {"device": "A", "chunk_size": 2},
        {"device": "B", "chunk_size": 1},
    ]
    records = {
        "A": [1, 2, 3],
        "B": [10, 11],
    }

    chunks = (
        flp.it(definitions)
        .select_many(
            # pyrefly: ignore [bad-argument-type, bad-index]
            lambda definition: flp.it(records[definition["device"]]).chunk(definition["chunk_size"])
        )
        .to_list()
    )

    assert [list(chunk) for chunk in chunks] == [[1, 2], [3], [10], [11]]

