from typing import NamedTuple

class ZipTuple[TFirst, TSecond](NamedTuple):
    first: TFirst
    second: TSecond

    @property
    def item1(self) -> TFirst:
        return self.first

    @property
    def item2(self) -> TSecond:
        return self.second