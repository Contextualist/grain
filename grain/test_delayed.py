from .delayed import *
from .resource import ZERO, Memory
from .contextvar import GVAR

import pytest
import trio

from functools import partial

run = partial(run, config_file=False)

async def test_delayed_obj():
    r_ = Delayed(Future(42))
    assert await r_ == 42
    assert await (1 + r_ * 2) == 85
    assert await (r_ + r_) == 84

    # inplace operation (setitem) creates a copy by default
    r_ = Delayed(Future([3,4]), length=2)
    a, b = r_
    r_[1] += 99
    assert (await r_ == [3,103])
    assert (await a == 3) and (await b == 4)

    # causality is respected for inplace operation
    r_ = Delayed(Future([3,4]), length=2)
    r_[1] += 99
    a, b = r_
    assert (await r_ == [3,103])
    assert (await a == 3) and (await b == 103)

async def _await(r_):
    assert await r_ == 43
async def test_simutaneous_await():
    r_ = Delayed(Future(42)) + 1
    async with trio.open_nursery() as _n:
        for _ in range(3):
            _n.start_soon(_await, r_)

def test_delayed_errors():
    a = Delayed(Future([1, 2, 3]))
    # immutable
    pytest.raises(TypeError, lambda: setattr(a, "foo", 1))
    # can't iterate, or check if contains
    pytest.raises(TypeError, lambda: 1 in a)
    pytest.raises(TypeError, lambda: list(a))
    # no dynamic generation of magic/hidden methods
    pytest.raises(AttributeError, lambda: a._hidden())
    # truth of delayed forbidden
    pytest.raises(TypeError, lambda: bool(a))


@delayed
async def _anop():
    await trio.sleep(0)

class Critical(Exception):
    pass

async def _main_subtask(i):
    await _anop()
    if i == 1:
        raise Critical
def test_main_subtask_exception():
    with pytest.raises(Critical):
        run([partial(_main_subtask, i) for i in range(10)], [], ZERO)


async def _top_serial():
    for _ in range(3):
        r = await _anop()
        assert r == None
def test_top_serial():
    run(_top_serial, [], ZERO)


@delayed
async def _a1():
    return [GVAR.res == ZERO]

async def _zero_and_more():
    assert await((_a1 @ Memory(1))() + _a1()) == [False,True]
def test_zero_and_more():
    run(_zero_and_more, [], Memory(1))


_list = []
@delayed
async def _append(i):
    _list.append(i)

async def _ordered_local_task():
    await each(reversed(list(_append(i) for i in range(10))))
    assert _list == list(range(10))
def test_ordered_local_task():
    run(_ordered_local_task, [], ZERO)
