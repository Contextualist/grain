from grain.remote_exer import RemoteExecutor
from grain.head import GrainExecutor
from grain.resource import Memory
import trio
import sys
from io import StringIO

import pytest
from . import asyncify, N

async def nop():
    await trio.sleep(0)

async def _parallx(exer):
    for _ in range(N):
        exer.submit(Memory(0), nop)
    for _ in range(N):
        await exer.resultq.receive()

CONFIG = """
worker.dial = "tcp://localhost:4239"
head.listen = "tcp://localhost:4239"
head.log_file = "/dev/null"
"""
async def test_exerworker(benchmark):
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, nolocal=True, config_file=StringIO(CONFIG)) as exer:
        await trio.sleep(0.1) # wait for exer to start
        cs = trio.CancelScope()
        _n.start_soon(_worker, cs)
        exer.submit(Memory(0), nop)
        await exer.resultq.receive() # make sure the entire pipeline is up and running
        await (asyncify(benchmark))(_parallx, exer)
        cs.cancel()

@pytest.mark.parametrize(
    "gt",
    ["go", "py"],
)
async def test_remoteexer(benchmark, gt):
    async with trio.open_nursery() as _n, \
               RemoteExecutor(_n=_n, nolocal=True, config_file=StringIO(CONFIG), gnaw="", gnawtype=gt, name="a-p") as exer:
        await trio.sleep(3 if gt=="py" else 1) # wait for gnaw to start
        cs = trio.CancelScope()
        _n.start_soon(_worker, cs)
        exer.submit(Memory(0), nop)
        await exer.resultq.receive() # make sure the entire pipeline is up and running
        await (asyncify(benchmark))(_parallx, exer)
        cs.cancel()

async def _worker(cs):
    with cs:
        await trio.run_process([sys.executable, "-m", "grain.worker", "--url", "tcp://localhost:4239",
                                "--res", '{"Memory": { "M": 54 }}'])
        print("worker quit")
