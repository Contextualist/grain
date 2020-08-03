from .worker import *
from .head import GrainExecutor
from .resource import Memory, WTime
from .contextvar import GVAR

import pytest
import trio

from functools import partial

GrainExecutor = partial(GrainExecutor, config_file=False)

async def addone(x):
    return x+1

async def test_worker():
    N = 3
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, nolocal=True) as exer:
        GVAR.instance = "test-worker-A"
        _n.start_soon(grain_worker, Memory(4)&WTime(10,countdown=True), "tcp://localhost:4242")
        for i in range(N):
            exer.submit(Memory(2), addone, i)
    results = [None] * N
    async with exer.resultq:
        async for i, r in exer.resultq:
            results[i-1] = r
    assert results == list(range(1,N+1))
