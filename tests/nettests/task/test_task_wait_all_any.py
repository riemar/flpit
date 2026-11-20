"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's Task.wait_all / Task.wait_any.

Test names and scenarios ported from:
- TaskWaitAllAnyTest.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskWaitAllAnyTest.cs

Every upstream test keeps its name with a ``test_`` prefix; the harness keeps its
upstream names. The 59 generated ``TaskWaitAllAnyN`` cases were translated
mechanically, line by line, from the upstream file. Mapping to FlpIt's Python API:

- timeouts are float seconds (upstream milliseconds / 1000; ``-1`` stays infinite),
  ``new TimeSpan(0, 0, 0, 0, ms)`` is ``timedelta(milliseconds=ms)``;
- ``AggregateException`` is ``AggregateError``; a canceled task is reported as a
  ``TaskCanceledError`` whose ``task`` is that task, as in .NET;
- ``Task.Factory.StartNew(action, state, token, AttachedToParent, TaskScheduler.Current)``
  is ``Task.run(action, token=token, creation_options=ATTACHED_TO_PARENT)``. FlpIt has no
  parent/child tasks; at the top level, where these tests create them, the option has
  no effect in .NET either;
- ``TPLTestException.FromTaskId == task.Id`` (``Task.CurrentId``) becomes a reference to
  the ``TaskInfo`` that raised it: FlpIt exposes no task ids, and the check is the same
  ("this exception came from this task");
- ``task.Exception.InnerException`` is ``task.exception()`` (FlpIt stores the original
  exception, not a wrapping AggregateException).
"""
from __future__ import annotations

import time
from datetime import timedelta
from enum import Enum
from typing import Callable

import pytest

from flpit.core.linq import ArgumentError, ArgumentNullError
from flpit.task import (
    AggregateError,
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskCanceledError,
    TaskCompletionSource,
    TaskCreationOptions,
)


# =============================================================================
# Helper Classes / Methods
# =============================================================================

class API(Enum):
    WaitAll = "WaitAll"
    WaitAny = "WaitAny"


class WaitBy(Enum):
    None_ = "None"  # WaitBy.None: ``None`` is a Python keyword
    TimeSpan = "TimeSpan"
    Millisecond = "Millisecond"


class WorkloadType(Enum):
    Exceptional = -2
    Cancelled = -1
    VeryLight = 100  # the number is the N input to the ZetaSequence workload
    Light = 200
    Medium = 400
    Heavy = 800
    VeryHeavy = 1600


class TPLTestException(Exception):
    """Upstream records ``Task.CurrentId``; FlpIt records the raising TaskInfo instead."""

    def __init__(self, from_task_info: TaskInfo) -> None:
        super().__init__("TPLTestException")
        self.FromTaskInfo = from_task_info


class TestParameters_WaitAllAny:
    __test__ = False  # not a pytest test class

    def __init__(self, api: API, waitTime: int, waitBy: WaitBy, allTasks: list[TaskInfo]) -> None:
        self.Api = api
        self.WaitBy = waitBy
        self.WaitTime = waitTime
        self.AllTaskInfos = allTasks


class TaskInfo:
    s_UNINITIALED_RESULT = -1.0

    def __init__(self, workType: WorkloadType) -> None:
        self.CancellationTokenSource = CancellationTokenSource()
        self.CancellationToken = self.CancellationTokenSource.token
        self.Result = TaskInfo.s_UNINITIALED_RESULT
        self.WorkType = workType
        self.Task: Task[None] | None = None

    def RunWorkload(self) -> None:
        if self.WorkType == WorkloadType.Exceptional:
            self.ThrowException()
        elif self.WorkType == WorkloadType.Cancelled:
            TaskInfo.CancelSelf(self.CancellationTokenSource, self.CancellationToken)
        else:
            if self.Result == TaskInfo.s_UNINITIALED_RESULT:
                self.Result = TaskInfo.ZetaSequence(self.WorkType.value, self.CancellationToken)
            else:  # task re-entry, mark it failed
                self.Result = TaskInfo.s_UNINITIALED_RESULT

    @staticmethod
    def ZetaSequence(n: int, token: CancellationToken) -> float:
        result = 0.0
        for i in range(1, n):
            if token.is_cancellation_requested:
                return TaskInfo.s_UNINITIALED_RESULT
            result += 1.0 / (float(i) * float(i))
        return result

    @staticmethod
    def CancelSelf(cts: CancellationTokenSource, ct: CancellationToken) -> None:
        cts.cancel()
        raise OperationCanceledError(token=ct)

    def ThrowException(self) -> None:
        raise TPLTestException(self)


class TaskWaitAllAnyTest:
    __test__ = False  # not a pytest test class

    MAX_DELAY_TIMEOUT = 10

    def __init__(self, parameters: TestParameters_WaitAllAny) -> None:
        self._api = parameters.Api
        self._waitBy = parameters.WaitBy
        self._waitTimeout = parameters.WaitTime
        self._taskInfos = parameters.AllTaskInfos
        self._tasks: list[Task[None]] = []
        self._taskWaitAllReturn = False  # result to record the WaitAll(timeout) return value
        self._taskWaitAnyReturn = 0  # result to record the WaitAny(timeout) return value
        self._caughtException: AggregateError | None = None  # exception thrown during wait

    def _seconds(self) -> float:
        return -1 if self._waitTimeout == -1 else self._waitTimeout / 1000

    def RealRun(self) -> None:
        self.CreateTask()

        sw = time.monotonic()
        try:
            if self._api == API.WaitAll:
                if self._waitBy == WaitBy.None_:
                    Task.wait_all(self._tasks)
                    self._taskWaitAllReturn = True
                elif self._waitBy == WaitBy.Millisecond:
                    self._taskWaitAllReturn = Task.wait_all(self._tasks, timeout=self._seconds())
                elif self._waitBy == WaitBy.TimeSpan:
                    self._taskWaitAllReturn = Task.wait_all(
                        self._tasks, timeout=timedelta(milliseconds=self._waitTimeout))
            elif self._api == API.WaitAny:
                if self._waitBy == WaitBy.None_:
                    self._taskWaitAnyReturn = Task.wait_any(self._tasks)
                elif self._waitBy == WaitBy.Millisecond:
                    self._taskWaitAnyReturn = Task.wait_any(self._tasks, timeout=self._seconds())
                elif self._waitBy == WaitBy.TimeSpan:
                    self._taskWaitAnyReturn = Task.wait_any(
                        self._tasks, timeout=timedelta(milliseconds=self._waitTimeout))
        except AggregateError as exp:
            self._caughtException = exp
        finally:
            elapsed_ms = (time.monotonic() - sw) * 1000

        # Upstream only logs (Debug.WriteLine) when the wait took much longer than requested.
        maxTimeout = self._waitTimeout + TaskWaitAllAnyTest.MAX_DELAY_TIMEOUT
        if self._waitTimeout != -1 and elapsed_ms > maxTimeout:
            print(f"ElapsedMilliseconds way more than requested Timeout. "
                  f"Max Timeout: {self._waitTimeout}ms + {TaskWaitAllAnyTest.MAX_DELAY_TIMEOUT}ms, "
                  f"Actual Time: {elapsed_ms:.0f}ms")

        self.Verify()
        self.CleanUpTasks()

    def CleanUpTasks(self) -> None:
        for taskInfo in self._taskInfos:
            assert taskInfo.Task is not None
            if not taskInfo.Task.done():  # TaskStatus.Running
                taskInfo.CancellationTokenSource.cancel()
                try:
                    taskInfo.Task.result()  # GetAwaiter().GetResult()
                except OperationCanceledError:
                    pass

    def CreateTask(self) -> None:
        for i, info in enumerate(self._taskInfos):
            task = Task.run(
                info.RunWorkload,
                token=info.CancellationTokenSource.token,
                creation_options=TaskCreationOptions.ATTACHED_TO_PARENT,
            )
            task.async_state = f"Task_{i}"  # the StartNew state argument
            info.Task = task
            self._tasks.append(task)

    def Verify(self) -> None:
        allShouldFinish = self._api == API.WaitAll and self._taskWaitAllReturn
        thisShouldFinish = (
            self._taskInfos[self._taskWaitAnyReturn].Task
            if self._api == API.WaitAny and self._taskWaitAnyReturn != -1
            else None
        )
        faultyTasks: dict[int, Task[None]] = {}
        expCaught = False

        for i, ti in enumerate(self._taskInfos):
            task = ti.Task
            assert task is not None
            if allShouldFinish and not task.done():
                pytest.fail(f"WaitAll contract is broken -- Task at Index = {i} does not finish")
            if thisShouldFinish is task and not task.done():
                pytest.fail(f"WaitAny contract is broken -- Task at Index = {i} does not finish")

            workType = ti.WorkType
            if workType == WorkloadType.Exceptional:
                expCaught = self.VerifyException(
                    lambda ex, ti=ti: isinstance(ex, TPLTestException) and ex.FromTaskInfo is ti)

                if self._api == API.WaitAll:
                    if not expCaught:
                        pytest.fail(f"excepted TPLTestException in Task at Index = {i}  NOT caught")
                else:  # must be API_WaitAllAny.WaitAny
                    if expCaught:
                        pytest.fail(f"Unexpected TPLTestException in Task at Index = {i} caught")
                    faultyTasks[i] = task
            elif workType == WorkloadType.Cancelled:
                expCaught = self.VerifyException(
                    lambda ex, task=task: isinstance(ex, TaskCanceledError) and ex.task is task)

                if self._api == API.WaitAll:
                    assert expCaught, f"excepted TaskCanceledException in Task at Index = {i} NOT caught"
                else:  # must be API_WaitAllAny.WaitAny
                    if expCaught:  # waitAny will not fail if a number of tasks were cancelled
                        assert not expCaught, f"Unexpected TaskCanceledException in Task at Index = {i} caught"
            elif task.done() and not self.CheckResult(ti.Result):
                pytest.fail(f"Failed result verification in Task at Index = {i}")

        if not expCaught and self._caughtException is not None:
            pytest.fail(f"Caught unexpected exception of {self._caughtException!r}")

        if faultyTasks:
            # WaitHandle.WaitAll(faulty tasks' AsyncWaitHandles): block until they complete.
            try:
                Task.wait_all(list(faultyTasks.values()))
            except AggregateError:
                pass
            for key, faulty in faultyTasks.items():
                if not isinstance(faulty.exception(), TPLTestException):
                    pytest.fail(f"Unexpected Exception in Task at Index = {key} caught")

    def VerifyException(self, isExpectedExp: Callable[[Exception], bool]) -> bool:
        if self._caughtException is None:
            return False
        return any(isExpectedExp(ex) for ex in self._caughtException.exceptions)

    @staticmethod
    def CheckResult(result: float) -> bool:
        minLimit = 1.63
        maxLimit = 1.65
        return minLimit < result < maxLimit


# =============================================================================
# TaskWaitAllAny (generated cases, translated mechanically)
# =============================================================================

# upstream: [OuterLoop]
def test_TaskWaitAllAny0() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny1() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.Light)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny2() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny3() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny4() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny5() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny6() -> None:
    node1 = TaskInfo(WorkloadType.Light)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny7() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Heavy)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, -1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny8() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 0, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny9() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 0, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny10() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 0, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny11() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.Light)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 0, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny12() -> None:
    node1 = TaskInfo(WorkloadType.VeryHeavy)
    node2 = TaskInfo(WorkloadType.Light)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 197, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny13() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.VeryLight)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 197, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny14() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 197, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny15() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 197, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny16() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 197, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny17() -> None:
    node1 = TaskInfo(WorkloadType.VeryHeavy)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny18() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny19() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny20() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.VeryHeavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny21() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 47, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny22() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny23() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny24() -> None:
    node1 = TaskInfo(WorkloadType.VeryLight)
    node2 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny25() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny26() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAll, 7, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny27() -> None:
    node1 = TaskInfo(WorkloadType.Light)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 7, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny28() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Heavy)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 7, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny29() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.Heavy)
    node6 = TaskInfo(WorkloadType.Light)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAll, 7, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny30() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny31() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Heavy)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    node8 = TaskInfo(WorkloadType.Medium)
    node9 = TaskInfo(WorkloadType.Light)
    node10 = TaskInfo(WorkloadType.Heavy)
    node11 = TaskInfo(WorkloadType.Heavy)
    node12 = TaskInfo(WorkloadType.VeryHeavy)
    node13 = TaskInfo(WorkloadType.VeryLight)
    node14 = TaskInfo(WorkloadType.Medium)
    node15 = TaskInfo(WorkloadType.Medium)
    node16 = TaskInfo(WorkloadType.Light)
    node17 = TaskInfo(WorkloadType.Heavy)
    node18 = TaskInfo(WorkloadType.Heavy)
    node19 = TaskInfo(WorkloadType.VeryHeavy)
    node20 = TaskInfo(WorkloadType.VeryLight)
    node21 = TaskInfo(WorkloadType.Medium)
    node22 = TaskInfo(WorkloadType.Medium)
    node23 = TaskInfo(WorkloadType.Light)
    node24 = TaskInfo(WorkloadType.Heavy)
    node25 = TaskInfo(WorkloadType.Heavy)
    node26 = TaskInfo(WorkloadType.VeryHeavy)
    node27 = TaskInfo(WorkloadType.VeryLight)
    node28 = TaskInfo(WorkloadType.Medium)
    node29 = TaskInfo(WorkloadType.Medium)
    node30 = TaskInfo(WorkloadType.Light)
    node31 = TaskInfo(WorkloadType.Heavy)
    node32 = TaskInfo(WorkloadType.Heavy)
    node33 = TaskInfo(WorkloadType.VeryHeavy)
    node34 = TaskInfo(WorkloadType.VeryLight)
    node35 = TaskInfo(WorkloadType.Medium)
    node36 = TaskInfo(WorkloadType.Medium)
    node37 = TaskInfo(WorkloadType.Light)
    node38 = TaskInfo(WorkloadType.Heavy)
    node39 = TaskInfo(WorkloadType.Heavy)
    node40 = TaskInfo(WorkloadType.VeryHeavy)
    node41 = TaskInfo(WorkloadType.VeryLight)
    node42 = TaskInfo(WorkloadType.Medium)
    node43 = TaskInfo(WorkloadType.Medium)
    node44 = TaskInfo(WorkloadType.Light)
    node45 = TaskInfo(WorkloadType.Heavy)
    node46 = TaskInfo(WorkloadType.Heavy)
    node47 = TaskInfo(WorkloadType.VeryHeavy)
    node48 = TaskInfo(WorkloadType.VeryLight)
    node49 = TaskInfo(WorkloadType.Medium)
    node50 = TaskInfo(WorkloadType.Medium)
    node51 = TaskInfo(WorkloadType.Light)
    node52 = TaskInfo(WorkloadType.Heavy)
    node53 = TaskInfo(WorkloadType.Heavy)
    node54 = TaskInfo(WorkloadType.VeryHeavy)
    node55 = TaskInfo(WorkloadType.VeryLight)
    node56 = TaskInfo(WorkloadType.Medium)
    node57 = TaskInfo(WorkloadType.Medium)
    node58 = TaskInfo(WorkloadType.Light)
    node59 = TaskInfo(WorkloadType.Heavy)
    node60 = TaskInfo(WorkloadType.Heavy)
    node61 = TaskInfo(WorkloadType.VeryHeavy)
    node62 = TaskInfo(WorkloadType.VeryLight)
    node63 = TaskInfo(WorkloadType.Medium)
    node64 = TaskInfo(WorkloadType.Medium)
    node65 = TaskInfo(WorkloadType.Light)
    node66 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2, node3, node4, node5, node6, node7, node8, node9, node10, node11, node12, node13, node14, node15, node16, node17, node18, node19, node20, node21, node22, node23, node24, node25, node26, node27, node28, node29, node30, node31, node32, node33, node34, node35, node36, node37, node38, node39, node40, node41, node42, node43, node44, node45, node46, node47, node48, node49, node50, node51, node52, node53, node54, node55, node56, node57, node58, node59, node60, node61, node62, node63, node64, node65, node66]
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny32() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny33() -> None:
    node1 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny34() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.VeryHeavy)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny35() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny36() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.Light)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.None_, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny37() -> None:
    node1 = TaskInfo(WorkloadType.VeryHeavy)
    node2 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, -1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny38() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 0, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny39() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.VeryLight)
    node3 = TaskInfo(WorkloadType.Light)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 0, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny40() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, 0, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny41() -> None:
    node1 = TaskInfo(WorkloadType.VeryLight)
    node2 = TaskInfo(WorkloadType.VeryHeavy)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 0, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny42() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, 197, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny43() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 197, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny44() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 197, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# upstream: [OuterLoop]
def test_TaskWaitAllAny45() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Heavy)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    node8 = TaskInfo(WorkloadType.Medium)
    node9 = TaskInfo(WorkloadType.Light)
    node10 = TaskInfo(WorkloadType.Heavy)
    node11 = TaskInfo(WorkloadType.Heavy)
    node12 = TaskInfo(WorkloadType.VeryHeavy)
    node13 = TaskInfo(WorkloadType.VeryLight)
    node14 = TaskInfo(WorkloadType.Medium)
    node15 = TaskInfo(WorkloadType.Medium)
    node16 = TaskInfo(WorkloadType.Light)
    node17 = TaskInfo(WorkloadType.Heavy)
    node18 = TaskInfo(WorkloadType.Heavy)
    node19 = TaskInfo(WorkloadType.VeryHeavy)
    node20 = TaskInfo(WorkloadType.VeryLight)
    node21 = TaskInfo(WorkloadType.Medium)
    node22 = TaskInfo(WorkloadType.Medium)
    node23 = TaskInfo(WorkloadType.Light)
    node24 = TaskInfo(WorkloadType.Heavy)
    node25 = TaskInfo(WorkloadType.Heavy)
    node26 = TaskInfo(WorkloadType.VeryHeavy)
    node27 = TaskInfo(WorkloadType.VeryLight)
    node28 = TaskInfo(WorkloadType.Medium)
    node29 = TaskInfo(WorkloadType.Medium)
    node30 = TaskInfo(WorkloadType.Light)
    node31 = TaskInfo(WorkloadType.Heavy)
    node32 = TaskInfo(WorkloadType.Heavy)
    node33 = TaskInfo(WorkloadType.VeryHeavy)
    node34 = TaskInfo(WorkloadType.VeryLight)
    node35 = TaskInfo(WorkloadType.Medium)
    node36 = TaskInfo(WorkloadType.Medium)
    node37 = TaskInfo(WorkloadType.Light)
    node38 = TaskInfo(WorkloadType.Heavy)
    node39 = TaskInfo(WorkloadType.Heavy)
    node40 = TaskInfo(WorkloadType.VeryHeavy)
    node41 = TaskInfo(WorkloadType.VeryLight)
    node42 = TaskInfo(WorkloadType.Medium)
    node43 = TaskInfo(WorkloadType.Medium)
    node44 = TaskInfo(WorkloadType.Light)
    node45 = TaskInfo(WorkloadType.Heavy)
    node46 = TaskInfo(WorkloadType.Heavy)
    node47 = TaskInfo(WorkloadType.VeryHeavy)
    node48 = TaskInfo(WorkloadType.VeryLight)
    node49 = TaskInfo(WorkloadType.Medium)
    node50 = TaskInfo(WorkloadType.Medium)
    node51 = TaskInfo(WorkloadType.Light)
    node52 = TaskInfo(WorkloadType.Heavy)
    node53 = TaskInfo(WorkloadType.Heavy)
    node54 = TaskInfo(WorkloadType.VeryHeavy)
    node55 = TaskInfo(WorkloadType.VeryLight)
    node56 = TaskInfo(WorkloadType.Medium)
    node57 = TaskInfo(WorkloadType.Medium)
    node58 = TaskInfo(WorkloadType.Light)
    node59 = TaskInfo(WorkloadType.Heavy)
    node60 = TaskInfo(WorkloadType.Heavy)
    node61 = TaskInfo(WorkloadType.VeryHeavy)
    node62 = TaskInfo(WorkloadType.VeryLight)
    node63 = TaskInfo(WorkloadType.Medium)
    node64 = TaskInfo(WorkloadType.Medium)
    node65 = TaskInfo(WorkloadType.Light)
    node66 = TaskInfo(WorkloadType.Heavy)
    node67 = TaskInfo(WorkloadType.Heavy)
    node68 = TaskInfo(WorkloadType.VeryHeavy)
    node69 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2, node3, node4, node5, node6, node7, node8, node9, node10, node11, node12, node13, node14, node15, node16, node17, node18, node19, node20, node21, node22, node23, node24, node25, node26, node27, node28, node29, node30, node31, node32, node33, node34, node35, node36, node37, node38, node39, node40, node41, node42, node43, node44, node45, node46, node47, node48, node49, node50, node51, node52, node53, node54, node55, node56, node57, node58, node59, node60, node61, node62, node63, node64, node65, node66, node67, node68, node69]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 197, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny46() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, 1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny47() -> None:
    node1 = TaskInfo(WorkloadType.VeryHeavy)
    node2 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny48() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryHeavy)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 1, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny49() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 1, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny50() -> None:
    node1 = TaskInfo(WorkloadType.Light)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 47, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny51() -> None:
    node1 = TaskInfo(WorkloadType.Light)
    node2 = TaskInfo(WorkloadType.VeryLight)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 47, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny52() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.Medium)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 47, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny53() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny54() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.VeryHeavy)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 47, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny55() -> None:
    node1 = TaskInfo(WorkloadType.Light)
    allTasks = [node1]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 7, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny56() -> None:
    node1 = TaskInfo(WorkloadType.Heavy)
    node2 = TaskInfo(WorkloadType.Light)
    allTasks = [node1, node2]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 7, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny57() -> None:
    node1 = TaskInfo(WorkloadType.Medium)
    node2 = TaskInfo(WorkloadType.Light)
    node3 = TaskInfo(WorkloadType.Heavy)
    node4 = TaskInfo(WorkloadType.Medium)
    node5 = TaskInfo(WorkloadType.VeryLight)
    node6 = TaskInfo(WorkloadType.VeryLight)
    node7 = TaskInfo(WorkloadType.Medium)
    allTasks = [node1, node2, node3, node4, node5, node6, node7]
    parameters = TestParameters_WaitAllAny(API.WaitAny, 7, WaitBy.Millisecond, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


def test_TaskWaitAllAny58() -> None:
    allTasks: list[TaskInfo] = []
    parameters = TestParameters_WaitAllAny(API.WaitAny, 7, WaitBy.TimeSpan, allTasks)
    test = TaskWaitAllAnyTest(parameters)
    test.RealRun()


# =============================================================================
# WaitAll(IEnumerable<Task>)
# =============================================================================

def _canceled_token() -> CancellationToken:
    """``new CancellationToken(true)``: FlpIt tokens come from a source."""
    source = CancellationTokenSource()
    source.cancel()
    return source.token


def test_TaskWaitAll_Enumerable_InvalidArguments() -> None:
    # AssertExtensions.Throws<T>("tasks", ...): exact exception type and the parameter name.
    with pytest.raises(ArgumentNullError, match="tasks") as info:
        Task.wait_all(None)  # type: ignore[arg-type]
    assert type(info.value) is ArgumentNullError
    for tasks in ([None], [Task.completed_task, None], [None, Task.completed_task]):
        with pytest.raises(ArgumentError, match="tasks") as info:
            Task.wait_all(tasks)  # type: ignore[arg-type]
        assert type(info.value) is ArgumentError


def test_TaskWaitAll_Enumerable_Canceled() -> None:
    tcs: TaskCompletionSource[None] = TaskCompletionSource()
    with pytest.raises(OperationCanceledError) as info:
        Task.wait_all([tcs.task], token=_canceled_token())
    assert type(info.value) is OperationCanceledError

    with CancellationTokenSource() as cts:
        cts.cancel_after(0.001)  # new CancellationTokenSource(1)
        with pytest.raises(OperationCanceledError) as info:
            Task.wait_all([Task.completed_task, tcs.task], token=cts.token)
        assert type(info.value) is OperationCanceledError


def test_TaskWaitAll_Enumerable_AllComplete() -> None:
    # Upstream casts to IEnumerable<Task>, Task[] and List<Task>; every Python iterable
    # takes the same path, so lists, tuples and generators stand in for them.
    Task.wait_all([])
    Task.wait_all([Task.completed_task])
    Task.wait_all([Task.completed_task, Task.completed_task])
    Task.wait_all((Task.completed_task, Task.completed_task))
    Task.wait_all(task for task in ())
    Task.wait_all(task for task in [Task.completed_task])
    Task.wait_all(task for task in [Task.completed_task, Task.completed_task])
    Task.wait_all([Task.delay(0.001)])
    Task.wait_all(task for task in [Task.delay(0.001)])
    Task.wait_all([Task.delay(0.001), Task.completed_task, Task.delay(0.001), Task.completed_task, Task.delay(0.001)])
