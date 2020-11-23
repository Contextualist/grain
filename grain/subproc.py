import trio
import dill as pickle

from functools import wraps, partial
from inspect import iscoroutinefunction
import sys
import os
from math import inf as INFIN
from subprocess import SubprocessError
from contextlib import asynccontextmanager

from grain.contextvar import GVAR # process local

IDLE_TIMEOUT = 60 # keep idle subprocess for 1min

def subprocify(fn):
    """Subprocify is a decorator that turns a sync
    function (usually a CPU-bound job) into an async
    job to be executed on an external Python interpreter
    subprocess. Please allocate 1 processor and adequate
    vmem for this job.
    """
    if iscoroutinefunction(getattr(fn, "func", fn)):
        raise TypeError("subprocify only wraps sync functions, but an async function is given")
    @wraps(fn)
    async def _wrapped(*args, **kwargs):
        if idle_subp:
            p = idle_subp.pop()
        else:
            p = await start_worker_process()
        ok, r = await p.execf(GVAR, partial(fn, *args, **kwargs))
        # FIXME: for now, if the job is cancelled from outside (e.g. timeout), the worker
        # process is abandoned, because we cannot determine the worker's status and output.
        if ok or type(r) is not BrokenSubprocessError:
            idle_subp.add(p)
        if not ok:
            raise r.with_traceback(r.__traceback__)
        return r
    return _wrapped

_sn = None
idle_subp = set()

@asynccontextmanager
async def subprocess_pool_scope(): # process local
    """Initialize the nursery for subprocess workers
    """
    global _sn
    if _sn is not None and not _sn._closed:
        yield
        return
    async with trio.open_nursery() as _sn:
        yield
        _sn.cancel_scope.cancel()
async def subprocess_pool_daemon(task_status=trio.TASK_STATUS_IGNORED): # process local
    """Initialize the nursery for subprocess workers
    """
    global _sn
    if _sn is not None and not _sn._closed:
        task_status.started(_sn.cancel_scope)
        return
    async with trio.open_nursery() as _sn:
        task_status.started(_sn.cancel_scope)
        await trio.sleep_forever()

async def start_worker_process():
    p = _Process()
    await _sn.start(p.loop)
    return p

class _Process(object):
    def __init__(self):
        self.to_child, self.from_child = None, None
        self.idle_timeout = trio.move_on_after(INFIN)
    async def loop(self, task_status=trio.TASK_STATUS_IGNORED):
        child_r, parent_w = os.pipe()
        parent_r, child_w = os.pipe()
        async with trio.lowlevel.FdStream(parent_w) as self.to_child, \
                   trio.lowlevel.FdStream(parent_r) as self.from_child:
            task_status.started()
            with self.idle_timeout:
                await trio.run_process([sys.executable, "-m", "grain.subproc_worker", "--fd-read", str(child_r), "--fd-write", str(child_w)],
                                       check=False,
                                       pass_fds=(child_r, child_w))
            # idle timeout: SIGINT, then remove self from the pool
            try:
                idle_subp.remove(self)
            except KeyError:
                pass
    async def execf(self, gvar, fn):
        self.idle_timeout.deadline = INFIN
        try:
            await pickle_dump(self.to_child, (gvar, fn))
            ok, r = await pickle_load(self.from_child)
            self.idle_timeout.deadline = trio.current_time() + IDLE_TIMEOUT
            return ok, r
        except trio.ClosedResourceError as e: # pipe broken / subprocess die
            self.idle_timeout.cancel() # termiate process immediately
            return False, BrokenSubprocessError("broken pipe to subprocess").from_(e)
    async def aclose(self): # NOTE: not used
        idle_subp.remove(self)
        await pickle_dump(self.to_child, None) # FIN

async def pickle_dump(f, obj):
    d = pickle.dumps(obj)
    await f.send_all(d)
async def pickle_load(f):
    d = await f.receive_some()
    while d[-1] != 46: # '.'; legit b/c the worker will not start another job until we drain the result
        d += await f.receive_some()
    return pickle.loads(d)

class BrokenSubprocessError(SubprocessError):
    def from_(self, e):
        self.__cause__, self.__traceback__ = e, e.__traceback__
        return self
