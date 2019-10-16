import trio
from pynng import Pair0
import dill as pickle

from copy import deepcopy
import random
from math import inf as INFIN

from .util import timeblock
from .resource import ZERO

class GrainRemote(object):
    def __init__(self, addr, res):
        self._c = Pair0(dial=f"tcp://{addr}:4242")
        self.res = res
        self.name = addr
    async def execf(self, tid, fn, *args, **kwargs):
        await self._c.asend(pickle.dumps((tid, fn, args, kwargs)))
        tid2, r2 = pickle.loads(await self._c.arecv()) # Not neccessary the matching response
        if tid2 == -1:
            print(f"Remote {self.name}'s task {r2[0]!r} failed with exception:\n{r2[1]}")
            raise RuntimeError("Remote exception")
        return tid2, r2
    async def done(self):
        await self._c.asend(b"FIN")
        self._c.close()

class GrainPseudoRemote(object):
    def __init__(self, res):
        self.res = res
        self.name = "local"
    async def execf(self, tid, fn, *args, **kwargs):
        return tid, await fn(*args, **kwargs)
    async def done(self):
        pass


class GrainExecutor(object):
    """There are two ways to use GrainExecutor: sync and async:
    sync: TODO
    async: TODO
    """
    def __init__(self, waddrs, rpw, _n=None, nolocal=False):
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.results = []
        self.pool = [GrainPseudoRemote(deepcopy(rpw if not nolocal else ZERO))] + \
                    [GrainRemote(a, deepcopy(rpw)) for a in waddrs]
        self.hold = {}
        self.cond_res = trio.Condition()
        self._n = _n

    async def asubmit(self, res, fn, *args, **kwargs):
        await self.push_job.send((res, fn, args, kwargs))
    def submit(self, res, fn, *args, **kwargs):
        self.push_job.send_nowait((res, fn, args, kwargs))

    async def __schedule(self, res): # naive scheduling alg: greedy
        async with self.cond_res:
            while True:
                for w in self.pool:
                    if w.res >= res: return w.res.alloc(res), w
                await self.cond_res.wait()
    async def __task_with_res(self, tid, res, w, fn, args, kwargs):
        self.hold[tid] = res
        tid2, r2 = await w.execf(tid, fn, grain_res=res, *args, **kwargs) # Not neccessary the matching response
        async with self.cond_res:
            w.res.dealloc(self.hold.pop(tid2))
            self.cond_res.notify()
        self.push_result.send_nowait((tid2, r2))
    async def run(self):
        await trio.sleep(3) # wait for workers TODO
        try:
            with timeblock("all jobs"):
                async with trio.open_nursery() as _n, self.pull_job:
                    i = 0
                    async for res, *fa in self.pull_job:
                        res, w = await self.__schedule(res)
                        _n.start_soon(self.__task_with_res, i, res, w, *fa)
                        i += 1
        finally:
            with trio.move_on_after(10) as cleanup_scope: # 10s cleanup
                cleanup_scope.shield = True
                await self.push_result.aclose()
                for w in self.pool:
                    await w.done()
        return i

    async def __aenter__(self):
        self._n.start_soon(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        await self.push_job.aclose()

    async def run_till_finish(self):
        await self.push_job.aclose()
        n = await self.run()
        self.results = [None] * n
        async with self.resultq:
            async for i, r in self.resultq:
                self.results[i] = r

    def __enter__(self):
        return self
    def __exit__(self, *exc):
        if any(exc):
            return False
        trio.run(self.run_till_finish)
