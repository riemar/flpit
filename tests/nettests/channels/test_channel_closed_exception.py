"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ChannelClosedError tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/ChannelClosedExceptionTests.cs
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/ChannelClosedExceptionTests.netcoreapp.cs

``BinaryFormatter`` serialization maps to ``pickle``.
"""
from __future__ import annotations

import pickle

from flpit.channels import ChannelClosedError
from flpit.core.linq import InvalidOperationError

from nettests.channels.channel_helpers import FormatError


class TestChannelClosedExceptionTests:
    def test_Ctors(self) -> None:
        e = ChannelClosedError()
        assert str(e)
        assert e.inner_exception is None

        e = ChannelClosedError("hello")
        assert "hello" == str(e)
        assert e.inner_exception is None

        inner = FormatError()
        e = ChannelClosedError("hello", inner)
        assert "hello" == str(e)
        assert e.inner_exception is inner

    def test_Serialization_Roundtrip(self) -> None:
        inner = InvalidOperationError("inner")
        outer = ChannelClosedError("outer", inner)

        new_outer = pickle.loads(pickle.dumps(outer))
        assert isinstance(new_outer, ChannelClosedError)
        assert new_outer is not outer
        assert str(outer) == str(new_outer)

        assert new_outer.inner_exception is not None
        assert new_outer.inner_exception is not inner
        assert str(inner) == str(new_outer.inner_exception)
