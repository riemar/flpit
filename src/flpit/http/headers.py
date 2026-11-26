"""Case-insensitive, multi-value HTTP headers."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping

class HttpHeaders(MutableMapping[str, str]):
    """Case-insensitive headers. get_all() preserves individual values."""
    def __init__(self, values: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        self._values: dict[str, tuple[str, list[str]]] = {}
        if values is not None:
            source = values.items() if isinstance(values, Mapping) else values
            for name, value in source:
                self.add(name, value)

    def __getitem__(self, name: str) -> str:
        try:
            return ", ".join(self._values[name.casefold()][1])
        except KeyError:
            raise KeyError(name) from None

    def __setitem__(self, name: str, value: str) -> None:
        self._validate(name, value)
        self._values[name.casefold()] = (name, [value])

    def __delitem__(self, name: str) -> None:
        del self._values[name.casefold()]

    def __iter__(self):
        return (name for name, _ in self._values.values())

    def __len__(self) -> int:
        return len(self._values)

    @staticmethod
    def _validate(name: str, value: str) -> None:
        if not isinstance(name, str) or not name or any(c in name for c in "\r\n:"):
            raise ValueError("Invalid HTTP header name")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError("Invalid HTTP header value")

    def add(self, name: str, value: str) -> None:
        self._validate(name, value)
        key = name.casefold()
        if key not in self._values:
            self._values[key] = (name, [value])
        else:
            self._values[key][1].append(value)

    def get_all(self, name: str) -> tuple[str, ...]:
        item = self._values.get(name.casefold())
        return tuple(item[1]) if item else ()

    def copy(self) -> HttpHeaders:
        result = HttpHeaders()
        for key, (name, values) in self._values.items():
            result._values[key] = (name, list(values))
        return result

    def set_if_absent(self, name: str, value: str) -> None:
        if name.casefold() not in self._values:
            self[name] = value

    def as_dict(self) -> dict[str, str]:
        return {name: ", ".join(values) for name, values in self._values.values()}


