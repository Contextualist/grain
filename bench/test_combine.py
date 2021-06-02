from grain.combine import open_waitgroup, exec1, run
from grain.resource import Memory, ZERO
import trio
from functools import partial

import pytest
from . import asyncify, N

async def nop():
    await trio.sleep(0)

async def _serial0():
    """{N} empty jobs with ZERO res, serial"""
    for _ in range(N):
        await exec1(ZERO, nop)

async def _parall0():
    """{N} empty jobs with ZERO res, parall"""
    async with open_waitgroup() as wg:
        for _ in range(N):
            wg.start_subtask(nop)

async def _serialx():
    """{N} empty jobs with some res, serial"""
    for _ in range(N):
        await exec1(Memory(0), nop)

async def _parallx():
    """{N} empty jobs with some res, parall"""
    async with open_waitgroup() as wg:
        for _ in range(N):
            wg.submit(Memory(0), nop)

async def _main(main, benchmark):
    await (asyncify(benchmark))(main)
@pytest.mark.parametrize(
    "main",
    [_serial0, _parall0, _serialx, _parallx],
)
def test_combine(benchmark, main):
    run(
        partial(_main, main, benchmark),
        config_file=False,
        rpw=Memory(0),
    )
