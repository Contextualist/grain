import trio
import dill as pickle

from copy import deepcopy
from math import inf as INFIN
from functools import partial
import traceback

from .contextvar import GVAR
from .util import timeblock, WaitGroup, nullacontext
from .resource import ZERO
from .pair import listen_signal, SocketChannel

FULL_HEALTH = 3

class GrainRemote(object):
    def __init__(self, addr, res):
        self._c = None
        self.res = res
        self.name = addr
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
    async def connect(self, _n):
        self._c = await (SocketChannel(f"{self.name}:4242", dial=True, _n=_n)).__aenter__()
    async def execf(self, tid, res, fn, args, kwargs):
        with self.wg:
            await self._c.send(pickle.dumps((tid, res, fn, args, kwargs)))
            tid2, r2 = pickle.loads(await self._c.receive()) # Not neccessary the matching response
            if tid2 > 0: self.health = FULL_HEALTH
            return tid2, r2
    async def aclose(self):
        await self._c.send(b"FIN")
        print(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        await self._c.aclose()
        print(f"worker {self.name} clear")

GVAR.instance = "local"
class GrainPseudoRemote(object):
    def __init__(self, res):
        self.res = res
        self.name = "local"
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
        self.cg = []
    async def connect(self, _n):
        pass
    async def execf(self, tid, res, fn, args, kwargs):
        cs = trio.CancelScope()
        self.cg.append(cs)
        with self.wg, cs:
            GVAR.res = res
            try:
                r = await fn(*args, **kwargs)
                self.health = FULL_HEALTH
            except Exception as e:
                tid, r = -tid, (partial(fn, *args, **kwargs), traceback.format_exc(), e)
            self.cg.remove(cs)
            return tid, r
    async def aclose(self):
        for cs in self.cg:
            cs.cancel()
        print(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        print(f"worker {self.name} clear")


class GrainManager(object):
    """Manage workers and resources.
    """
    def __init__(self, pool_init, _n, temperr, persistent, interface=True):
        self.pool = pool_init
        self._n = _n
        self.temperr = temperr
        self.persistent = persistent
        self.cond_res = trio.Condition()
        self.chsig = None

    async def schedule(self, res): # naive scheduling alg: greedy
        async with self.cond_res:
            while True:
                for w in self.pool:
                    if w.res >= res: return w.res.alloc(res), w
                await self.cond_res.wait()

    async def health_check(self, w, tb, err):
        async with self.cond_res:
            w.health -= 1 if type(err) in self.temperr else INFIN
            if w.health <= 0 and w in self.pool:
                print(tb)
                if w.name == 'local': raise RuntimeError("local worker quits")
                print(f"quit worker {w.name} due to poor health {w.health}")
                await self.unregister(w.name, locked=True)

    async def dealloc(self, w, res):
        if w.health > 0:
            async with self.cond_res:
                w.res.dealloc(res)
                self.cond_res.notify()

    async def register(self, w):
        await w.connect(self._n)
        async with self.cond_res:
            self.pool.append(w)
            self.cond_res.notify()
    async def unregister(self, name, locked=False):
        async with nullacontext() if locked else self.cond_res:
            # expect one and only name
            i,w = next(((i,x) for i,x in enumerate(self.pool) if x.name==name), (0,0))
            if not i: return
            self.pool.pop(i)
            await w.aclose() # notify exit and reschedule pending jobs
            if not self.persistent:
                raise RuntimeError(f"worker {name} exits, abort.")
    async def worker_manager(self, task_status=trio.TASK_STATUS_IGNORED):
        async with trio.open_nursery() as _n, \
                   listen_signal("0.0.0.0:4243", _n) as self.chsig:
            task_status.started()
            async for (addr, _), msg in self.chsig:
                #addr, _ = await trio.socket.getnameinfo((addr,0),0)
                cmd, msg = msg[:3], msg[3:]
                if cmd == b"REG":
                    addr, res = pickle.loads(msg)
                    print(f"worker {addr} joined with {res}")
                    await self.register(GrainRemote(addr, res))
                elif cmd == b"UNR":
                    addr = msg.decode()
                    print(f"worker {addr} asked for quit")
                    await self.unregister(addr)
                else:
                    print(f"worker manager received unknown command {cmd} from {addr}")

    async def __aenter__(self):
        for w in self.pool:
            await w.connect(self._n)
        await self._n.start(self.worker_manager)

    async def aclose(self):
        with trio.move_on_after(10) as cleanup_scope: # 10s cleanup
            cleanup_scope.shield = True
            await self.chsig.aclose()
            for w in self.pool:
                await w.aclose()

    async def __aexit__(self, *exc):
        await self.aclose()
        return False


class GrainExecutor(object):
    """There are two ways to use GrainExecutor: sync and async:
    sync: TODO
    async: TODO
    """
    def __init__(self,
                 waddrs,
                 rpw,
                 _n=None,
                 nolocal=False,    # run jobs on local or not
                 temporary_err=(), # exceptions that's not critical to shutdown a worker
                 reschedule=True,  # if False, abort on any exception
                 persistent=True,  # if False, abort on any worker's exit
                 ):
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.jobn = 0
        self.results = []
        self._n = _n
        self._wg = WaitGroup() # track the entire lifetime of each job
        self.hold = {}
        self.reschedule = reschedule
        self.mgr = GrainManager(
            [GrainPseudoRemote(deepcopy(rpw if not nolocal else ZERO))] + \
            [GrainRemote(a, deepcopy(rpw)) for a in waddrs],
            self._n, temporary_err, persistent)

    async def asubmit(self, res, fn, *args, **kwargs):
        self._wg.add()
        await self.push_job.send((0, res, fn, args, kwargs))
    def submit(self, res, fn, *args, **kwargs):
        self._wg.add()
        self.push_job.send_nowait((0, res, fn, args, kwargs))

    async def __task_with_res(self, tid, res, w, fn, args, kwargs):
        try:
            self.hold[tid] = res
            tid2, r2 = await w.execf(tid, res, fn, args, kwargs) # Not neccessary the matching response
            res2 = self.hold.pop(abs(tid2))
            if tid2 > 0:
                self.push_result.send_nowait((tid2, r2))
            else:
                fn2, tb, err = r2
                if not self.reschedule:
                    raise RuntimeError(f"worker {w.name}'s task {fn2} raises {err.__class__.__name__}: {err}, abort.")
                print(f"worker {w.name}'s task {fn2} raises {err.__class__.__name__}: {err}, going to reschedule it...")
                await self.mgr.health_check(w, tb, err)
                self._wg.add()
                self.push_job.send_nowait((-tid2, res2, fn2, [], {})) # preserve tid
            await self.mgr.dealloc(w, res2)
        finally:
            self._wg.done()

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()

    async def run(self):
        try:
            with timeblock("all jobs"):
                async with self.mgr, \
                           trio.open_nursery() as _n, \
                           self.pull_job:
                    async for tid, res, *fa in self.pull_job:
                        if not tid: tid = self.jobn = self.jobn+1
                        res, w = await self.mgr.schedule(res)
                        _n.start_soon(self.__task_with_res, tid, res, w, *fa)
        finally:
            await self.push_result.aclose()

    async def __aenter__(self):
        self._n.start_soon(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        self._n.start_soon(self.sealer)

    async def run_till_finish(self):
        async with trio.open_nursery() as self._n:
            self.mgr._n = self._n
            self._n.start_soon(self.run)
            self._n.start_soon(self.sealer)
        self.results = [None] * self.jobn
        async with self.resultq:
            async for i, r in self.resultq:
                self.results[i-1] = r
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        if any(exc):
            return False
        trio.run(self.run_till_finish)
