import trio
import dill as pickle

from functools import partial
import traceback
import argparse

from .contextvar import GVAR
from .resource import *
from .pair import notify, SocketChannel
from .subproc import subprocess_pool_daemon

async def exerf(tid, res, func, so):
    GVAR.res = res
    try:
        with trio.fail_after(res.T) if hasattr(res, 'T') else nullcontext():
            r = await func()
    except BaseException as e:
        if type(e) is trio.Cancelled: e = WorkerCancelled()
        tid, r = -tid, (traceback.format_exc(), e) # negative tid for failure
    finally:
        with trio.move_on_after(3) as cleanup_scope:
            cleanup_scope.shield = True
            await so.send(pickle.dumps((tid, r)))

async def grain_worker():
    RES = eval(carg.res) # FIXME: better way to define res
    timesc = trio.fail_after(RES.T) if hasattr(RES, 'T') else nullcontext()
    passive = not (carg.head and RES)
    if passive:
        sockopt = dict(addr=":4242", listen=True)
        print("passive mode enabled")
    else:
        sockopt = dict(addr=f"{carg.head}:4242", dial=True)
        print(f"connecting to head {carg.head!r}...")
    async with trio.open_nursery() as _cn, \
               SocketChannel(**sockopt, _n=_cn) as so, \
               trio.open_nursery() as _n:
        await _n.start(subprocess_pool_daemon)
        if not passive:
            await so.send(b"CON"+pickle.dumps((GVAR.instance, RES)))
        print("worker launched")
        try:
            with timesc:
                async for msg in so:
                    if msg == b"FIN": # end of queue / low health / server error
                        print("received FIN from head, worker exits")
                        break
                    tid, res, fn = pickle.loads(msg)
                    _n.start_soon(exerf, tid, res, fn, so)
                else:
                    print("connection to head lost, worker exits")
                    so.send = anop
        except BaseException as e:
            if passive:
                print(f"interrupted by {e.__class__.__name__}")
                return # `GVAR.instance` might differ from head's record, so don't notify
            print(f"interrupted by {e.__class__.__name__}, notify head")
            await notify(f"{carg.head}:4242", b"UNR"+GVAR.instance.encode(), seg=True)
            if (await so.receive()) != b"FIN": assert False
            print("received FIN from head, worker exits")
        finally:
            _n.cancel_scope.cancel()

class nullcontext(object):
    def __enter__(self): return self
    def __exit__(self, *exc): return False

async def anop(*_): pass

class WorkerCancelled(BaseException):
    def __str__(self):
        return "Cancelled"

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Worker instance for Grain")
    argp.add_argument('--head', default="", help="address of Grain's head instance")
    argp.add_argument('--res', '-r', default="None", help="the resource owned by the worker (e.g. Node(N=16,M=28)&WTime(1800)")
    carg = argp.parse_args()

    GVAR.instance = trio.socket.gethostname()
    trio.run(grain_worker)
