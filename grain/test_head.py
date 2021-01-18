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


class MockRemote(GrainPseudoRemote):
    def __init__(self, name):
        self.res = Memory(1)
        self.name = name
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
        self.cg = set()
    async def connect(self, _n):
        pass

async def test_manager(autojump_clock):
    def _assert_qlen(q, l):
        assert len(q._state.data) == l
    def _from_result_take_exactly(n):
        _assert_qlen(exer.resultq, n)
        [exer.resultq.receive_nowait() for _ in range(n)]
    async def _job():
        await trio.sleep(3)
        return "retval"

    pool = map(MockRemote, ["w0", "u0", "w1"])
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n) as exer:
        # release queued job when there're new resources
        exer.submit(Memory(1), _job)
        for w in pool:
            await exer.mgr.register(w, _n)
        await trio.sleep(3.1)
        _from_result_take_exactly(1)

        # terminate waits for pending jobs to finish
        exer.submit(Memory(1), _job)
        exer.submit(Memory(1), _job)
        _assert_qlen(exer.resultq, 0)
        await trio.sleep(.1)
        _assert_qlen(exer.push_job, 0)
        await exer.mgr.terminate("w?")
        assert len(exer.mgr.pool) == 1+3
        await trio.sleep(3)
        _from_result_take_exactly(2)
        assert len(exer.mgr.pool) == 1+1 and exer.mgr.pool[1].name == "u0"

        # unregister cancels all pending jobs
        exer.submit(Memory(1), _job)
        await trio.sleep(.1)
        _assert_qlen(exer.resultq, 0)
        await exer.mgr.unregister("*")
        assert len(exer.mgr.pool) == 1+0
        _assert_qlen(exer.resultq, 0)
        # cleanup
        await exer.mgr.register(MockRemote("_cleanup"), _n)
        await trio.sleep(3.1)
        _from_result_take_exactly(1)
