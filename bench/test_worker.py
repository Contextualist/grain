from grain.remote_exer import RemoteExecutor
from grain.head import GrainExecutor
from grain.delayed import delayed, each, run
from grain.config import load_conf
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

CONFIG_STR = """
head.listen = "tcp://localhost:4239"
head.log_file = "/dev/null"
head.gnaw.idle_quit = "0s"
head.gnaw.log_file = ""
head.gnaw.max_conn = 1
"""
CONFIG = load_conf(StringIO(CONFIG_STR), 'head')
async def test_exerworker(benchmark):
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, nolocal=True, config=CONFIG) as exer:
        await trio.sleep(0.1) # wait for exer to start
        _n.start_soon(_worker)
        exer.submit(Memory(0), nop)
        await exer.resultq.receive() # make sure the entire pipeline is up and running
        await (asyncify(benchmark))(_parallx, exer)
        _n.cancel_scope.cancel()

@pytest.mark.parametrize(
    "gt",
    ["go", "py"],
)
async def test_remoteexer(benchmark, gt):
    async with trio.open_nursery() as _n:
        if gt == "py":
            _n.start_soon(_gnaw_py)
            await trio.sleep(3) # wait for gnaw to start
        gopts = dict(gnaw="tcp://localhost:4238") if gt == "py" else {}
        async with RemoteExecutor(_n=_n, nolocal=True, config=CONFIG, **gopts, name="a-p") as exer:
            _n.start_soon(_worker)
            exer.submit(Memory(0), nop)
            await exer.resultq.receive() # make sure the entire pipeline is up and running
            await (asyncify(benchmark))(_parallx, exer)
            _n.cancel_scope.cancel()
    if gt == "go":
        await trio.run_process(["pkill", "gnaw"])

def test_delayed_re(benchmark):
    async def _main():
        async def _parallx_d():
            await each([(nop_@Memory(0))() for _ in range(N)])
        nop_ = delayed(nop)
        async with trio.open_nursery() as _n:
            _n.start_soon(_worker)
            await (nop_ @ Memory(0))() # make sure the entire pipeline is up and running
            await (asyncify(benchmark))(_parallx_d)
            _n.cancel_scope.cancel()
        await trio.run_process(["pkill", "gnaw"])
    run(_main, nolocal=True, config_file=StringIO(CONFIG_STR), name="a-p")


async def _worker():
    await trio.run_process([sys.executable, "-m", "grain.worker", "--url", "tcp://localhost:4239",
                            "--res", '{"Memory": { "M": 54 }}'])

async def _gnaw_py():
    await trio.run_process([sys.executable, "-m", "grain.gnaw", "--hurl", "tcp://localhost:4238",
                            "--wurl", "tcp://localhost:4239", "-n", "1"])
