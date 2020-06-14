from .head import *
from .resource import Memory, ZERO

import pytest
import trio
from trio.testing import MockClock

from functools import partial
from io import StringIO

sprint = partial(trio.run, clock=MockClock(rate=1000))
GrainExecutor = partial(GrainExecutor, config_file=False)

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

async def critical_err_task():
    raise Critical
trial = 0
async def temporary_err_task():
    global trial
    trial += 1
    raise Temporary

def test_local_critical():
    with pytest.raises(RuntimeError, match="local worker quit"), \
         GrainExecutor() as exer:
        exer.submit(ZERO, critical_err_task)

def test_local_lastjob_retry():
    with pytest.raises(RuntimeError, match="local worker quit"), \
         GrainExecutor(temporary_err=(Temporary,)) as exer:
        exer.submit(ZERO, temporary_err_task)
    assert trial == FULL_HEALTH


async def say_something():
    print("something")

def test_local_redirectouterr(capsys):
    with GrainExecutor() as exer:
        exer.submit(ZERO, say_something)
    captured = capsys.readouterr()
    assert "something\n" in captured.out

    with GrainExecutor(config_file=StringIO('''[head]
listen = "tcp://:4243"
log_file = "/dev/null"''')) as exer:
        exer.submit(ZERO, say_something)
    captured = capsys.readouterr()
    assert "something\n" not in captured.out
