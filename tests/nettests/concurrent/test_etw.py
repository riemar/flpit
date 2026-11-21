"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Event tracing tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/EtwTests.cs

flpit has no EventSource / ETW tracing: skipped.
"""
from __future__ import annotations

from nettests.common.collection_helpers import not_portable


class TestEtwTests:
    def test_TestEtw(self) -> None:
        not_portable("EventSource / ETW tracing")
