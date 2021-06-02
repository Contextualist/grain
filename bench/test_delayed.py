from grain.delayed import delayed, each, run
from grain.resource import Memory
import trio
from functools import partial

import pytest
from . import asyncify, N

@delayed
async def nop():
    await trio.sleep(0)

async def _serial0():
    """{N} empty jobs with ZERO res, serial"""
    for _ in range(N):
        await nop()

async def _parall0():
    """{N} empty jobs with ZERO res, parall"""
    await each([nop() for _ in range(N)])

async def _serialx():
    """{N} empty jobs with some res, serial"""
    for _ in range(N):
        await (nop@Memory(0))()

async def _parallx():
    """{N} empty jobs with some res, parall"""
    await each([(nop@Memory(0))() for _ in range(N)])

async def _main(main, benchmark):
    await (asyncify(benchmark))(main)
@pytest.mark.parametrize(
    "main",
    [_serial0, _parall0, _serialx, _parallx],
)
def test_delayed(benchmark, main):
    run(
        partial(_main, main, benchmark),
        config_file=False,
        rpw=Memory(0),
    )
