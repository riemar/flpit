"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Prioritized unbounded channel tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading.Channels/tests/PriorityUnboundedChannelTests.cs

``TestUnboundedPrioritizedChannelTests`` also runs the shared ``ChannelTestBase`` and
``UnboundedChannelTests`` suites.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import override

from flpit.channels import Channel, UnboundedPrioritizedChannelOptions
from flpit.task import Task

from nettests.channels.test_unbounded_channel import UnboundedChannelTests


@dataclass(frozen=True, order=True)
class Person:
    """Upstream ``struct Person : IComparable<Person>`` ordered by ``Age``."""

    age: int


class TestUnboundedPrioritizedChannelTests(UnboundedChannelTests):
    @override
    def create_channel(self) -> Channel[int]:
        return Channel.create_unbounded_prioritized(UnboundedPrioritizedChannelOptions(
            allow_synchronous_continuations=self.allow_synchronous_continuations,
        ))

    def test_ItemsReadInExpectedOrder_NoComparer(self) -> None:
        c: Channel[Person] = Channel.create_unbounded_prioritized(UnboundedPrioritizedChannelOptions(
            allow_synchronous_continuations=self.allow_synchronous_continuations,
        ))

        for _ in range(2):
            assert c.writer.write_async(Person(20)).status == Task.SUCCEEDED
            assert 1 == c.reader.count

            assert c.writer.write_async(Person(21)).status == Task.SUCCEEDED
            assert 2 == c.reader.count

            assert c.writer.write_async(Person(19)).status == Task.SUCCEEDED
            assert 3 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 19 == p.age
            assert 2 == c.reader.count

            assert c.writer.write_async(Person(18)).status == Task.SUCCEEDED
            assert 3 == c.reader.count

            assert c.writer.write_async(Person(22)).status == Task.SUCCEEDED
            assert 4 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 18 == p.age
            assert 3 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 20 == p.age
            assert 2 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 21 == p.age
            assert 1 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 22 == p.age
            assert 0 == c.reader.count

    def test_ItemsReadInExpectedOrder_Comparer(self) -> None:
        c: Channel[Person] = Channel.create_unbounded_prioritized(UnboundedPrioritizedChannelOptions(
            comparer=lambda p1, p2: (p2.age > p1.age) - (p2.age < p1.age),
        ))

        for _ in range(2):
            assert c.writer.write_async(Person(20)).status == Task.SUCCEEDED
            assert 1 == c.reader.count

            assert c.writer.write_async(Person(21)).status == Task.SUCCEEDED
            assert 2 == c.reader.count

            assert c.writer.write_async(Person(19)).status == Task.SUCCEEDED
            assert 3 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 21 == p.age
            assert 2 == c.reader.count

            assert c.writer.write_async(Person(18)).status == Task.SUCCEEDED
            assert 3 == c.reader.count

            assert c.writer.write_async(Person(22)).status == Task.SUCCEEDED
            assert 4 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 22 == p.age
            assert 3 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 20 == p.age
            assert 2 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 19 == p.age
            assert 1 == c.reader.count

            ok, p = c.reader.try_read()
            assert ok and p is not None
            assert 18 == p.age
            assert 0 == c.reader.count
