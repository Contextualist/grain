from .head import GrainExecutor
from .resource import ZERO

from math import inf as INFIN
from contextlib import contextmanager
from collections.abc import Iterable

import trio

def open_waitgroup():
    if not CombineGroup:
        raise RuntimeError("`open_waitgroup` is only valid inside `run_combine`")
    return CombineGroup()

async def exec1(res, fn, *args, **kwargs):
    if not Exec1:
        raise RuntimeError("`exec1` is only valid inside `run_combine`")
    return await Exec1(res, fn, *args, **kwargs)
        
async def _grouped_task(gid, fn, *args, **kwargs):
    r = await fn(*args, **kwargs)
    return gid, r

CombineGroup, Exec1 = None, None
@contextmanager
def CombineGroup_ctxt(exer, push_newgroup):
    sema = trio.Semaphore(50) # rate limit
    gid = 0 # monotonously incremental with __aenter__'s side-effect

    class __CombineGroup(object):
        """A wait group that submit jobs to backend
        GrainExecutor and collect the results.
        This context manager is reusable, but single-use
        is recommended, because creating a instance
        each time allows nesting multiple ones.
        """
        def __init__(self):
            self.counter = 0
            self.results = []
        async def asubmit(self, res, fn, *args, **kwargs):
            await exer.asubmit(res, _grouped_task, self.gid, fn, *args, **kwargs)
            self.counter += 1
        def submit(self, res, fn, *args, **kwargs):
            exer.submit(res, _grouped_task, self.gid, fn, *args, **kwargs)
            self.counter += 1
        def start_subtask(self, fn, *args, **kwargs):
            # tasks requesting zero resource would be executed locally
            exer.submit(ZERO, _grouped_task, self.gid, fn, *args, **kwargs)
            self.counter += 1
        async def __aenter__(self): # async part of __init__
            if self.counter > 0:
                raise RuntimeError("attempt to re-enter a CombineGroup. For recursive use, create a new instance instead.")
            await sema.acquire()
            nonlocal gid
            self.gid = gid = gid + 1
            s, self.resultq = trio.open_memory_channel(INFIN)
            push_newgroup.send_nowait( (-1, (self.gid, s)) )
            return self
        async def __aexit__(self, *exc):
            if any(exc): return False
            resultd = {}
            async with self.resultq:
                if self.counter > 0:
                    async for i, r in self.resultq:
                        resultd[i] = r
                        self.counter -= 1
                        if self.counter == 0: break
            self.results = [v for k,v in sorted(resultd.items(), key=lambda x: x[0])]
            sema.release()

    async def __Exec1(res, fn, *args, **kwargs):
        nonlocal gid
        g = gid = gid + 1
        sq, rq = trio.open_memory_channel(0)
        push_newgroup.send_nowait( (-1, (g, sq)) )
        exer.submit(res, _grouped_task, g, fn, *args, **kwargs)
        async with rq, sq:
            return (await rq.receive())[1]

    global CombineGroup, Exec1
    CombineGroup, Exec1 = __CombineGroup, __Exec1
    try:
        yield
    finally:
        CombineGroup, Exec1 = None, None

async def relay(inq):
    # inq has two senders: push_newgroup; push_result.
    # This is an analogue of `select` in Golang
    outqs = {}
    async with inq:
        async for i, (g, outq_or_rslt) in inq:
            if i == -1:
                outqs[g] = outq_or_rslt # init outq
            else:
                outqs[g].send_nowait((i, outq_or_rslt))
async def boot_combine(frames, args, kwargs):
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, *args, **kwargs) as exer, \
               exer.push_result.clone() as push_newgroup:
        _n.start_soon(relay, exer.resultq)
        with CombineGroup_ctxt(exer, push_newgroup):
            if isinstance(frames, Iterable):
                async with trio.open_nursery() as _gn:
                    for frame in frames:
                        _gn.start_soon(frame)
            else:
                await frames()

def run_combine(frames, *args, **kwargs):
    trio.run(boot_combine, frames, args, kwargs)
