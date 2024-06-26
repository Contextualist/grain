from .combine import *
from .resource import ZERO

import pytest
import trio
try:
    from exceptiongroup import ExceptionGroup  # for Python < 3.11
except ImportError:
    pass

from functools import partial

run = partial(run, config_file=False)

async def _anop():
    await trio.sleep(0)

class Critical(Exception):
    pass

async def _main_subtask(i):
    async with open_waitgroup() as wg:
        wg.submit(ZERO, _anop)
    if i == 1:
        raise Critical

def test_main_subtask_exception():
    with pytest.raises(ExceptionGroup) as excinfo:
        run([partial(_main_subtask, i) for i in range(10)], [], ZERO)
    assert excinfo.group_contains(Critical)

async def _top_serial():
    for _ in range(3):
        async with open_waitgroup() as wg:
            wg.submit(ZERO, _anop)
        assert wg.results == [None]

def test_top_serial():
    run(_top_serial, [], ZERO)
