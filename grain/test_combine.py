from .combine import *
from .resource import Memory

import pytest
import trio

from functools import partial

async def _anop():
    await trio.sleep(0)

class Critical(Exception):
    pass

async def _main_subtask(i):
    async with open_waitgroup() as wg:
        wg.submit(Memory(0), _anop)
    if i == 1:
        raise Critical

def test_main_subtask_exception():
    with pytest.raises(Critical):
        run_combine([partial(_main_subtask, i) for i in range(10)], [], Memory(0))
