from .head import *
from .resource import Memory

import pytest
import trio
from trio.testing import MockClock

from functools import partial

sprint = partial(trio.run, clock=MockClock(rate=1000))


async def rev(n, i):
    await trio.sleep(n-i)
    return i

def test_order(monkeypatch):
    monkeypatch.setattr(trio, "run", sprint)
    N = 10
    with GrainExecutor([], Memory(8)) as exer:
        for i in range(N):
            exer.submit(Memory(2), rev, N, i)
    assert exer.results == list(range(N))


class Critical(Exception):
    pass
class Temporary(Exception):
    pass

def critical_err_task():
    raise Critical
trial = 0
def temporary_err_task():
    global trial
    trial += 1
    raise Temporary

def test_local_critical():
    with pytest.raises(RuntimeError, match="local worker quit"), \
         GrainExecutor([], Memory(8)) as exer:
        exer.submit(Memory(8), critical_err_task)

def test_local_lastjob_retry():
    with pytest.raises(RuntimeError, match="local worker quit"), \
         GrainExecutor([], Memory(8), temporary_err=(Temporary,)) as exer:
        exer.submit(Memory(8), temporary_err_task)
    assert trial == FULL_HEALTH
