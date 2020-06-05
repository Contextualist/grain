import trio
import dill as pickle

from copy import deepcopy
from math import inf as INFIN
from functools import partial
import traceback
from contextlib import redirect_stdout, redirect_stderr, ExitStack
import sys

from .contextvar import GVAR
from .util import timeblock, WaitGroup, nullacontext, optional_cm, make_prependable
from .resource import ZERO, Reject
from .pair import SocketChannel, SocketChannelAcceptor
from .subproc import subprocess_pool_daemon, BrokenSubprocessError
from .stat import log_event, log_timestart, log_timeend, stat_logger, ls_worker_res, reg_probe, collect_probe
from .config import load_conf

FULL_HEALTH = 3
STATSPAN = 15 # minutes
HEARTBEAT_INTERVAL, HEARTBEAT_TOLERANCE = 10, 3 # 10s * 3

pickle_dumps = partial(pickle.dumps, protocol=4)
pickle_loads = pickle.loads

class GrainRemote(object):
    def __init__(self, addr, res):
        self._c = None
        self.res = res
        self.name = addr
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
        self.resultq = {}
    async def _loop(self, task_status=trio.TASK_STATUS_IGNORED):
        async def heartbeat_s(c):
            while True:
                await c.try_send(b"HBT")
                await trio.sleep(HEARTBEAT_INTERVAL)
        async def heartbeat_n_receive(c):
            async with trio.open_nursery() as _n:
                _n.start_soon(heartbeat_s, c)
                while True:
                    with trio.move_on_after(HEARTBEAT_INTERVAL*HEARTBEAT_TOLERANCE):
                        async for x in c:
                            if x == b"HBT": break
                            yield x
                        else: break
                        continue
                    print(f"remote {self.name} heartbeat response timeout")
                    break
                _n.cancel_scope.cancel()
        async with self._c:
            task_status.started()
            async for x in heartbeat_n_receive(self._c):
                tid, r = pickle_loads(x)
                rq = self.resultq.get(abs(tid))
                if rq:
                    await rq.send((tid>0, r))
                else:
                    log_event("late_response")
                    print(f"remote {self.name} received phantom job {abs(tid)}'s result")
        # well, we just let the remote decide when to leave
        #assert self._c.is_clean is False # NOTE: P2P conn doesn't get EOF when the other end quit, we need to close on our end
        # In case of connection lost, dismiss all pending jobs
        for rq in list(self.resultq.values()): # frozen
            await rq.aclose()
    async def connect(self, _n):
        self._c = SocketChannel(f"tcp://{self.name}:4242", dial=True, _n=_n)
        await _n.start(self._loop)
    async def execf(self, tid, res, fn):
        with self.wg:
            self.resultq[tid], rq = trio.open_memory_channel(0)
            try:
                await self._c.send(pickle_dumps((tid, res, fn)))
                with optional_cm(trio.fail_after, getattr(res,'T',-180)+180): # 3min grace period
                    ok, r = await rq.receive()
            except (trio.ClosedResourceError, trio.EndOfChannel):
                # TODO: dedicated error class?
                ok, r = False, ("",RuntimeError(f"remote {self.name} closed connection unexpectedly"))
            except trio.TooSlowError:
                log_event("lost_or_late_response")
                ok, r = False, ("",trio.TooSlowError(f"remote {self.name} lost track of job {tid}"))
            if ok: self.health = FULL_HEALTH
            del self.resultq[tid]
            return ok, r
    async def aclose(self):
        await self._c.try_send(b"FIN") # fails if KI or connection lost
        print(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        await self._c.aclose() # for P2P connection
        print(f"worker {self.name} clear")

class GrainReverseRemote(GrainRemote):
    """A Grain remote for which the worker dial in
    (e.g. in the case when worker doesn't have accessible
    port, but is able to access the head.)
    The registration message (i.e. (vaddr, res)) should
    be sent as the first message.
    See `GrainManager.worker_manager`.
    """
    def __init__(self, _c, vaddr, res):
        GrainRemote.__init__(self, vaddr, res)
        self._c = _c
    async def connect(self, _n):
        _n.start_soon(self._loop)

GVAR.instance = "N/A"
class _cobj:
    def __init__(self, fobj, dobj):
        self._h, self._dh = fobj, dobj
    def __getattr__(self, attr):
        if GVAR.instance == "local":
            return getattr(self._h, attr)
        return getattr(self._dh, attr)
class GrainPseudoRemote:
    def __init__(self, res, out=""):
        self.res = res
        self.name = f"{trio.socket.gethostname()}(local)"
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
        self.cg = set()
        self.redi_cm = ExitStack()
        if out:
            outh = self.redi_cm.enter_context(open(out,'w'))
            self.redi_cm.enter_context(redirect_stdout(_cobj(outh,sys.stdout)))
            self.redi_cm.enter_context(redirect_stderr(_cobj(outh,sys.stderr)))
    async def connect(self, _n):
        if self.res > ZERO:
            self.cg.add(await _n.start(subprocess_pool_daemon))
    async def execf(self, tid, res, fn):
        cs = trio.CancelScope()
        self.cg.add(cs)
        with self.wg, cs:
            GVAR.res = res
            GVAR.instance = "local"
            try:
                with optional_cm(trio.fail_after, getattr(res,'T',0)):
                    ok, r = True, await fn()
                    self.health = FULL_HEALTH
            except BaseException as e:
                if type(e) is trio.Cancelled: raise
                ok, r = False, (traceback.format_exc(), e)
            self.cg.remove(cs)
            return ok, r
    async def aclose(self):
        for cs in self.cg:
            cs.cancel()
        print(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        self.redi_cm.__exit__(None, None, None)
        print(f"worker {self.name} clear")


class GrainManager:
    """Manage workers and resources.
    """
    def __init__(self, pool_init, _n, temperr, persistent, listen_addr):
        self.pool = pool_init
        self._n = _n
        self.temperr = {*set(temperr), BrokenSubprocessError}
        self.persistent = persistent
        self.listen_addr = listen_addr
        self.cond_res = trio.Condition()
        self.soacceptor = None

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
                if type(err) not in self.temperr:
                    print(tb)
                if w.name.endswith('(local)'): raise RuntimeError("local worker quits")
                print(f"quit worker {w.name} due to poor health {w.health}")
                await self.unregister(w.name, locked=True)

    async def dealloc(self, w, res):
        if w.health > 0:
            async with self.cond_res:
                w.res.dealloc(res)
                self.cond_res.notify()

    async def register(self, w, _n):
        await w.connect(_n)
        async with self.cond_res:
            self.pool.append(w)
            self.cond_res.notify()
    async def unregister(self, name, locked=False):
        async with nullacontext() if locked else self.cond_res:
            # expect one and only name
            i,w = next(((i,x) for i,x in enumerate(self.pool) if x.name==name), (0,None))
            if not i: return
            self.pool.pop(i)
            await w.aclose() # notify exit and reschedule pending jobs
            if not self.persistent:
                raise RuntimeError(f"worker {name} exits, abort.")
    async def terminate(self, name):
        async with self.cond_res:
            # expect one and only name
            w = next((x for x in self.pool if x.name==name), None)
            if not w or type(w.res) is Reject: return
            w.res = Reject(w.res)
        await w.wg.wait() # wait till no job is running
        await self.unregister(name)

    async def worker_manager(self, task_status=trio.TASK_STATUS_IGNORED):
        async with trio.open_nursery() as _n, \
                   SocketChannelAcceptor(self.listen_addr, _n=_n) as self.soacceptor:
            for w in self.pool:
                await w.connect(_n)
            task_status.started()
            async for _c in self.soacceptor:
                try:
                    msg = await _c.receive()
                except trio.EndOfChannel:
                    continue
                cmd, msg = msg[:3], msg[3:]
                if cmd == b"CON": # connect
                    vaddr, res = pickle_loads(msg)
                    print(f"worker {vaddr} joined with {res}")
                    await self.register(GrainReverseRemote(_c, vaddr, res), _n)
                    continue
                async with _c: # The following are ephemeral cmds
                    if cmd == b"REG": # register
                        addr, res = pickle_loads(msg)
                        print(f"worker {addr} joined with {res}")
                        await self.register(GrainRemote(addr, res), _n)
                    elif cmd == b"UNR": # unregister
                        addr = msg.decode()
                        print(f"worker {addr} asked for quit")
                        await self.unregister(addr)
                    elif cmd == b"STA": # statistics
                        sta = ls_worker_res(self.pool) + '\n' + \
                              collect_probe()
                        await _c.try_send(sta.encode())
                    elif cmd == b"TRM": # graceful termination
                        addr = msg.decode()
                        print(f"worker {addr} is going to leave")
                        _n.start_soon(self.terminate, addr)
                    else:
                        print(f"worker manager received unknown command {cmd} from {_c.host}")

    async def __aenter__(self):
        await self._n.start(self.worker_manager)

    async def aclose(self):
        with trio.move_on_after(10) as cleanup_scope: # 10s cleanup
            cleanup_scope.shield = True
            for w in self.pool:
                await w.aclose()
            await self.soacceptor.aclose()

    async def __aexit__(self, *exc):
        await self.aclose()
        return False


class GrainExecutor(object):
    """There are two ways to use GrainExecutor: sync and async:
    sync: TODO
    async: TODO
    """
    def __init__(
        self,
        waddrs=(),        # list of initial passive workers' addresses
        rpw=ZERO,         # resource per worker for the initial passive workers
        _n=None,          # (in async mode) external trio.Nursery for self's and manager's run loop
        nolocal=False,    # run jobs on local or not
        temporary_err=(), # exceptions that's not critical to shutdown a worker
        reschedule=True,  # if False, abort on any exception
        persistent=True,  # if False, abort on any worker's exit
        config_file=None, # TOML grain config file name (Can be set by envar `GRAIN_CONFIG`)
        stat_tag=lambda res: str(getattr(res,'T',"")), # define how timestat is categorized by resource
     ):
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_job = make_prependable(self.push_job)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.jobn = 0
        self.results = []
        self._n = _n
        self._wg = WaitGroup() # track the entire lifetime of each job
        self.reschedule = reschedule
        conf_head = load_conf(config_file).head
        self.mgr = GrainManager(
            [GrainPseudoRemote(deepcopy(rpw if not nolocal else ZERO), conf_head.log_file)] + \
            [GrainRemote(a, deepcopy(rpw)) for a in waddrs],
            self._n, temporary_err, persistent, conf_head.listen)
        reg_probe("queued jobs", lambda: len(self.push_job._state.data))
        self.stat_tag = stat_tag

    async def asubmit(self, res, fn, *args, **kwargs):
        self._wg.add()
        tid = self.jobn = self.jobn+1
        await self.push_job.send((tid, res, partial(fn, *args, **kwargs)))
        return tid
    def submit(self, res, fn, *args, **kwargs):
        self._wg.add()
        tid = self.jobn = self.jobn+1
        self.push_job.send_nowait((tid, res, partial(fn, *args, **kwargs)))
        return tid
    def resubmit(self, tid, res, fn):
        self._wg.add()
        self.push_job.cutin_nowait((tid, res, fn)) # prepend the queue

    async def __task_with_res(self, tid, res, w, fn):
        try:
            tag = self.stat_tag(res)
            if tag: log_timestart(tag, tid)
            ok, r = await w.execf(tid, res, fn)
            if tag: log_timeend(tag, tid)
            if ok:
                log_event("completed")
                self.push_result.send_nowait((tid, r))
            else:
                log_event("error")
                tb, err = r
                if not self.reschedule:
                    raise RuntimeError(f"worker {w.name}'s task {fn} raises {err.__class__.__name__}: {err}, abort.")
                print(f"worker {w.name}'s task {fn} raises {err.__class__.__name__}: {err}, going to reschedule it...")
                await self.mgr.health_check(w, tb, err)
                self.resubmit(tid, res, fn) # preserve tid
            await self.mgr.dealloc(w, res)
        finally:
            self._wg.done()

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()

    async def run(self):
        res = None
        reg_probe("next pending job's res", lambda: res)
        with timeblock("all jobs"):
            async with self.mgr, \
                       stat_logger(STATSPAN), \
                       self.push_result, \
                       trio.open_nursery() as _n, \
                       self.pull_job:
                async for tid, res, fn in self.pull_job:
                    res, w = await self.mgr.schedule(res)
                    _n.start_soon(self.__task_with_res, tid, res, w, fn)

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
