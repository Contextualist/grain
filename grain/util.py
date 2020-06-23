from contextlib import ContextDecorator
from timeit import default_timer as timer
from functools import wraps
import types
from math import inf as INF

def timeblock(text="this block", enter=False):
    class TimeblockCtx(ContextDecorator):
        def __enter__(self):
            if enter:
                print(f"Enter {text}")
            self.st = timer()
            return self
        def __exit__(self, *exc):
            print(f"Time elapsed for {text}{' (incomplete)' if any(exc) else ''}: {timer()-self.st}")
            return False
    return TimeblockCtx()


import trio
from trio.lowlevel import ParkingLot, checkpoint, enable_ki_protection
from outcome import Value
from async_generator import asynccontextmanager

class WaitGroup(object):

    def __init__(self):
        self._counter = 0
        self._lot = ParkingLot()

    def add(self):
        self._counter += 1

    @enable_ki_protection
    def done(self, *exc):
        self._counter -= 1
        if self._counter == 0:
            self._lot.unpark_all()
        return False

    __enter__ = add
    __exit__ = done

    async def wait(self):
        if self._counter == 0:
            await checkpoint()
        else:
            await self._lot.park()

PENDING = object()

class Future:
    __slots__ = ("_v", "_lot")
    def __init__(self, v=PENDING):
        self._v = v
        self._lot = ParkingLot()

    @enable_ki_protection
    def set(self, v):
        self._v = v
        self._lot.unpark_all()

    async def get(self):
        if self._v is not PENDING:
            await checkpoint()
        else:
            await self._lot.park()
        return self._v


@enable_ki_protection
def cutin_nowait(self, value):
    if self._closed:
        raise trio.ClosedResourceError
    if self._state.open_receive_channels == 0:
        raise trio.BrokenResourceError
    if self._state.receive_tasks:
        assert not self._state.data
        task, _ = self._state.receive_tasks.popitem(last=False)
        task.custom_sleep_data._tasks.remove(task)
        trio.lowlevel.reschedule(task, Value(value))
    elif len(self._state.data) < self._state.max_buffer_size:
        self._state.data.appendleft(value)
    else:
        raise trio.WouldBlock

def make_prependable(mschan):
    mschan.cutin_nowait = types.MethodType(cutin_nowait, mschan)
    return mschan


@asynccontextmanager
async def open_nursery_with_capacity(conc):
    """A patched Trio.Nursery with child task capacity
    limit. Its ``start_once_acquired`` blocks when the
    number of running child tasks started by it exceeds
    ``conc``.

    e.g.::

        async with open_nursery_with_capacity(10) as nursery:
            for _ in range(30):
                await nursery.start_once_acquired(trio.sleep, 1)
    """
    sema = trio.Semaphore(conc)
    async def _rl_task(fn, *args, task_status=trio.TASK_STATUS_IGNORED):
        async with sema:
            task_status.started()
            await fn(*args)
    async def start_once_acquired(self, fn, *args):
        await self.start(_rl_task, fn, *args)

    async with trio.open_nursery() as _n:
        _n.start_once_acquired = types.MethodType(start_once_acquired, _n)
        yield _n

@asynccontextmanager
async def open_ordered_nursery():
    """A patched Trio.Nursery that is able to start
    child task in strict first-come-first-served order,
    using its `start_now` method.
    """
    sq, rq = trio.open_memory_channel(INF)
    async def _starter():
        async for fargs in rq:
            _n.start_soon(*fargs)
    def start_now(self, *fargs):
        sq.send_nowait(fargs)

    async with trio.open_nursery() as _n:
        _n.start_soon(_starter)
        async with trio.open_nursery() as _on:
            _on.start_now = types.MethodType(start_now, _on)
            yield _on
        await sq.aclose()

@asynccontextmanager
async def QueueLimiter(conc):
    """Rate limit for the submission of delayed functions. Grain by
    default enqueues delayed functions eagerly (i.e. as soon as it
    is called). Sometimes if we have a lot of functions that can be
    run in parallel, we don't want to overwhelm the queue, so we could
    set a rate limit check prior submission. Note that the context
    scope blocks until all functions submitted through it are done.

    Args:
      conc (int): maximum number of concurrently running functions

    e.g.::

        @delayed
        async def dfn(x):
            await trio.sleep(1)
            return x+1
        r_ = 0
        async with QueueLimiter(10) as ql:
            for i in range(30):
                r_ += await ql(dfn)(i)
                #     ^^^^^wait for submission, not for result
        r = await r_
    """
    sema = trio.Semaphore(conc)
    async def sema2notify(dfn, args, kwargs, task_status):
        async with sema:
            do = dfn(*args, **kwargs)
            task_status.started(do)
            await do # sema is not released until calculation is done
    def _rl_wrapper(dfn):
        async def _rl_dfn(*args, **kwargs):
            do = await _n.start(sema2notify, dfn, args, kwargs)
            return do
        return _rl_dfn
    async with trio.open_nursery() as _n:
        yield _rl_wrapper


class nullacontext(object):
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

def optional_cm(cm, cond_arg):
    if cond_arg:
        return cm(cond_arg)
    return nullacontext()

def set_numpy_oneline_repr():
    """Change the default Numpy array ``__repr__`` to a
    compact one. This is useful for keeping the log
    clean when the job functions involve large Numpy
    arrays as args.
    """
    import numpy as np
    EDGEITEMS = 3
    def oneline_repr(a):
        N = np.prod(a.shape)
        ind = np.unravel_index(range(min(EDGEITEMS, N)), a.shape)
        afew = []
        for x,val in zip(np.c_[ind], a[ind]):
            for i,y in enumerate(x[::-1]):
                if y != 0: break
            else: i+=1
            for j,y in enumerate(x[::-1]):
                if y+1 != a.shape[len(x)-j-1]: break
            else: j+=1
            afew.append(f"{'['*i}{val}{']'*j}")
        return f"array[{a.shape}]({', '.join(afew)}{'...' if N > EDGEITEMS else ''})"
    np.set_string_function(oneline_repr, repr=True)
