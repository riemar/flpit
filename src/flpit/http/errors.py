"""HTTP-specific exception hierarchy."""
from __future__ import annotations

class HttpRequestException(Exception):
    def __init__(self, message: str, *, status_code: int | None = None,
                 inner_exception: BaseException | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.inner_exception = inner_exception
        if inner_exception is not None:
            self.__cause__ = inner_exception


class HttpRequestTimeoutError(HttpRequestException):
    """The HTTP request exceeded its configured timeout."""


