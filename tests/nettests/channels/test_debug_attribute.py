"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Debugger attribute tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/DebugAttributeTests.cs

``DebuggerDisplay`` / ``DebuggerTypeProxy`` do not exist in Python: skipped.
"""
from __future__ import annotations

from nettests.channels.channel_helpers import not_portable


class TestDebugAttributeTests:
    def test_TestDebuggerDisplaysAndTypeProxies(self) -> None:
        not_portable("debugger display attributes")

    def test_TestDequeueClass(self) -> None:
        not_portable("debugger display attributes")
