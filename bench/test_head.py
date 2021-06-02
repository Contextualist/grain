from grain.head import GrainExecutor
from grain.resource import Memory, ZERO
import trio

import pytest
from . import asyncify, N

async def nop():
    await trio.sleep(0)

async def _parallx(exer):
    for _ in range(N):
        exer.submit(Memory(0), nop)
    for _ in range(N):
        await exer.resultq.receive()

async def test_head(benchmark):
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, rpw=Memory(0), config_file=False) as exer:
        await (asyncify(benchmark))(_parallx, exer)
