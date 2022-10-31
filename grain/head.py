import trio

from copy import deepcopy
from math import inf as INFIN
from functools import partial
import traceback
from contextlib import redirect_stdout, redirect_stderr, ExitStack
import sys
from fnmatch import fnmatchcase
import logging
logger = logging.getLogger(__name__)

from .contextvar import GVAR
from .util import timeblock, pickle_dumps, pickle_loads, WaitGroup, nullacontext, optional_cm, make_prependable, load_contextmod, load_mod, as_daemon
from .resource import Resource, ZERO, Reject
from .pair import SocketChannel, SocketChannelAcceptor, notify
from .subproc import subprocess_pool_daemon, BrokenSubprocessError
from .stat import log_event, log_timestart, log_timeend, stat_logger, ls_worker_res, reg_probe, collect_probe

FULL_HEALTH = 3
STATSPAN = 15 # minutes
HEARTBEAT_INTERVAL, HEARTBEAT_TOLERANCE = 10, 3 # 10s * 3

class GrainRemote:
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
                await c.try_send(dict(cmd="HBT"))
                await trio.sleep(HEARTBEAT_INTERVAL)
        async with self._c, \
                   trio.open_nursery() as _n:
            task_status.started()
            _n.start_soon(heartbeat_s, self._c)
            while True:
                x = None
                try:
                    with trio.move_on_after(HEARTBEAT_INTERVAL*HEARTBEAT_TOLERANCE):
                        x = await self._c.receive()
                except trio.EndOfChannel:
                    break
                if x is None:
                    logger.warning(f"remote {self.name} heartbeat response timeout")
                    break
                elif x == {'cmd':'HBT'}:
                    continue
                tid, ok, r = x['tid'], not x['exception'], x['result']
                rq = self.resultq.get(tid)
                if rq:
                    await rq.send((ok, pickle_loads(r)))
                else:
                    log_event("late_response")
                    logger.warning(f"remote {self.name} received phantom job {tid}'s result")
            _n.cancel_scope.cancel()
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
                await self._c.send(dict(tid=tid, res=res, func=pickle_dumps(fn)))
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
        await self._c.try_send(dict(cmd="FIN")) # fails if KI or connection lost
        logger.info(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        await self._c.aclose() # for P2P connection
        logger.info(f"worker {self.name} clear")

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
        if GVAR.instance.endswith("(local)"):
            return getattr(self._h, attr)
        return getattr(self._dh, attr)
class GrainPseudoRemote:
    def __init__(self, name, res, out="", cmod=nullacontext()):
        self.res = res
        self.name = name
        self.health = FULL_HEALTH
        self.wg = WaitGroup()
        self.cg = set()
        self.redi_cm = ExitStack()
        if out:
            outh = self.redi_cm.enter_context(open(out,'w'))
            self.redi_cm.enter_context(redirect_stdout(_cobj(outh,sys.stdout)))
            self.redi_cm.enter_context(redirect_stderr(_cobj(outh,sys.stderr)))
        self.cmod = cmod
        self.cmod_context = None
    async def _scope(self, task_status=trio.TASK_STATUS_IGNORED):
        with trio.CancelScope() as cs, \
             self.redi_cm:
            self.cg.add(cs)
            async with self.cmod as self.cmod_context:
                task_status.started()
                await trio.sleep_forever()
    async def connect(self, _n):
        await _n.start(self._scope)
    async def execf(self, tid, res, fn):
        with self.wg, \
             trio.CancelScope() as cs:
            self.cg.add(cs)
            GVAR.res = res
            GVAR.instance = self.name
            GVAR.context = self.cmod_context
            try:
                with optional_cm(trio.fail_after, getattr(res,'T',0)):
                    ok, r = True, await fn()
                    self.health = FULL_HEALTH
            except BaseException as e:
                ok, r = False, (traceback.format_exc(), e)
            self.cg.remove(cs)
            return ok, r
    async def aclose(self):
        for cs in self.cg:
            cs.cancel()
        logger.info(f"worker {self.name} starts cleaning up")
        await self.wg.wait()
        logger.info(f"worker {self.name} clear")

class GrainSpecializedRemote(GrainPseudoRemote):
    # TODO: heartbeat
    def __init__(self, name, res, _c, sw_kwargs):
        stype = sw_kwargs.pop("_stype")
        sw_mod = load_mod(stype)
        super().__init__(name, res, "", sw_mod.grain_context(**sw_kwargs))
        self._c = _c
    async def aclose(self):
        for cs in self.cg:
            cs.cancel()
        if self._c:
            await self._c.try_send(dict(cmd="FIN")) # fails if KI or connection lost
            logger.info(f"worker {self.name} starts cleaning up")
        else:
            logger.info(f"client for specialized worker {self.name} starts cleaning up")
        await self.wg.wait()
        if self._c:
            await self._c.aclose() # for P2P connection
            logger.info(f"worker {self.name} clear")
        else:
            logger.info(f"client for specialized worker {self.name} clear")


class GrainManager:
    """Manage workers and resources.
    """
    def __init__(self, pool_init, _n, temperr, persistent, listen_addr, sworker_config):
        self.pool = pool_init
        self._n = _n
        self.temperr = {*set(temperr), BrokenSubprocessError}
        self.persistent = persistent
        self.listen_addr = listen_addr
        self.sworker_config = sworker_config
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
                    logger.error(tb)
                if w.name.endswith('(local)'): raise RuntimeError("local worker quits")
                logger.warning(f"quit worker {w.name} due to poor health {w.health}")
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
    def _match_workers(self, p):
        # results are only meaningful within cond_res
        return [(i,w) for i,w in enumerate(self.pool)
                if fnmatchcase(w.name,p) and not w.name.endswith('(local)')]
    async def unregister(self, pattern, locked=False):
        async with nullacontext() if locked else self.cond_res:
            for i,w in reversed(self._match_workers(pattern)):
                logger.info(f"worker {w.name} is quitting now")
                await w.aclose() # notify exit and reschedule pending jobs
                if not self.persistent:
                    raise RuntimeError(f"worker {w.name} exits, abort.")
                del self.pool[i]
    async def terminate(self, pattern):
        async def _wait_n_unreg(w):
            await w.wg.wait() # wait till no job is running
            await self.unregister(w.name) # `self.pool` might have changed, do another lookup
        async with self.cond_res:
            for _,w in self._match_workers(pattern):
                if type(w.res) is Reject: continue
                logger.info(f"worker {w.name} is going to leave")
                w.res = Reject(w.res)
                self._n.start_soon(_wait_n_unreg, w)

    async def worker_manager(self, registered_stype, task_status=trio.TASK_STATUS_IGNORED):
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
                cmd = msg['cmd']
                if cmd == "CON": # connect
                    vaddr, res = msg['name'], msg['res']
                    logger.info(f"worker {vaddr} joined with {res}")
                    await self.register(GrainReverseRemote(_c, vaddr, res), _n)
                    continue
                elif cmd == "SRG": # specialized register
                    name, res, kwargs = msg['name'], msg['res'], msg['obj']
                    logger.info(f"worker {name} joined with {res}")
                    if kwargs['_stype'] not in registered_stype:
                        raise ValueError(f"Unknown specialized worker type {kwargs['_stype']}")
                    await self.register(GrainSpecializedRemote(name, res, _c, kwargs), _n)
                    continue
                async with _c: # The following are ephemeral cmds
                    if cmd == "REG": # register
                        addr, res = msg['name'], msg['res']
                        logger.info(f"worker {addr} joined with {res}")
                        await self.register(GrainRemote(addr, res), _n)
                    elif cmd == "UNR": # unregister
                        pattern = msg['name']
                        await self.unregister(pattern)
                    elif cmd == "STA": # statistics
                        sta = ls_worker_res(self.pool) + '\n' + \
                              collect_probe()
                        await _c.try_send(dict(result=sta.encode()))
                    elif cmd == "TRM": # graceful termination
                        pattern = msg['name']
                        await self.terminate(pattern)
                    else:
                        logger.warning(f"worker manager received unknown command {cmd} from {_c.host}")

    async def __aenter__(self):
        registered_stype, _, self.backendless_sworker_n = await self._n.start(
            backendless_sworker_manager,
            self.sworker_config, self.listen_addr,
        )
        await self._n.start(self.worker_manager, registered_stype)

    async def aclose(self):
        with trio.move_on_after(10) as cleanup_scope: # 10s cleanup
            cleanup_scope.shield = True
            self.backendless_sworker_n.cancel_scope.cancel()
            for w in self.pool:
                await w.aclose()
            await self.soacceptor.aclose()

    async def __aexit__(self, *exc):
        await self.aclose()
        return False


async def backendless_sworker_manager(sworker_config, manager_api, task_status=trio.TASK_STATUS_IGNORED):
    registered_stype = set()
    backendless_stype = set()
    async with trio.open_nursery() as backendless_sworker_n:
        for sw_conf in sworker_config:
            stype = sw_conf.specialized_type
            registered_stype.add(stype)
            sw_mod = load_mod(stype)
            if not sw_mod.GRAIN_SWORKER_CONFIG.get("BACKENDLESS", False):
                continue
            backendless_stype.add(stype)
            # Backendless sworker's `grain_run_sworker` should be a trivial context for returning `sw_info`
            sw_info = await backendless_sworker_n.start(as_daemon, sw_mod.grain_run_sworker())
            resd = dict()
            if sw_conf.script.cores or sw_conf.script.memory:
                resd["Node"] = dict(N=sw_conf.script.cores, M=sw_conf.script.memory)
            if sw_conf.script.walltime:
                resd["WTime"] = dict(T=sw_conf.script.walltime, countdown=True)
            res = Resource.from_dict({
                **resd,
                **sw_conf.res,
            })
            await notify(
                manager_api,
                dict(cmd="SRG", name=sw_info.pop("name"), res=res, obj=dict(_stype=stype, **sw_info)),
                seg=True,
            )
        task_status.started((registered_stype, backendless_stype, backendless_sworker_n))


class GrainExecutor:
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
        config=None,      # grain's head config
        stat_tag=lambda res: str(getattr(res,'T',"")), # define how timestat is categorized by resource
        sworker_config=(), # grain's specialized worker config
     ):
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_job = make_prependable(self.push_job)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.jobn = 0
        self.results = []
        self._n = _n
        self._wg = WaitGroup() # track the entire lifetime of each job
        self.reschedule = reschedule
        self.mgr = GrainManager(
            [GrainPseudoRemote(
                f"{trio.socket.gethostname()}(local)",
                deepcopy(rpw if not nolocal else ZERO),
                config.log_file,
                load_contextmod(config.contextmod)()
            )] + [GrainRemote(a, deepcopy(rpw)) for a in waddrs],
            self._n, temporary_err, persistent, config.listen, sworker_config)
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
    def _submit(self, tid, res, fn): # for internal use
        self._wg.add()
        self.push_job.send_nowait((tid, res, fn))
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
                logger.error(f"worker {w.name}'s task {fn} raises {err.__class__.__name__}: {err}, going to reschedule it...")
                await self.mgr.health_check(w, tb, err)
                self.resubmit(tid, res, fn) # preserve tid
            await self.mgr.dealloc(w, res)
        finally:
            self._wg.done()

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()

    async def run(self, task_status=trio.TASK_STATUS_IGNORED):
        res = None
        reg_probe("next pending job's res", lambda: res)
        with timeblock("all jobs"):
            async with self.mgr, \
                       stat_logger(STATSPAN), \
                       self.push_result, \
                       trio.open_nursery() as _n, \
                       self.pull_job:
                task_status.started()
                async for tid, res, fn in self.pull_job:
                    res, w = await self.mgr.schedule(res)
                    _n.start_soon(self.__task_with_res, tid, res, w, fn)

    async def __aenter__(self):
        await self._n.start(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        self._n.start_soon(self.sealer)

    async def run_till_finish(self):
        async with trio.open_nursery() as self._n:
            self.mgr._n = self._n
            await self._n.start(self.run)
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
