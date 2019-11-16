import trio
import dill as pickle

from functools import partial
import traceback
import argparse

from .contextvar import GVAR
from .resource import *
from .pair import notify, SocketChannel

async def exerf(tid, res, func, so):
    GVAR.res = res
    try:
        r = await func()
    except BaseException as e:
        if type(e) is trio.Cancelled: e = WorkerCancelled()
        tid, r = -tid, (traceback.format_exc(), e) # negative tid for failure
    finally:
        with trio.move_on_after(3) as cleanup_scope:
            cleanup_scope.shield = True
            await so.send(pickle.dumps((tid, r)))

async def grain_worker():
    print(f"connecting to head {carg.head!r}...")
    RES = eval(carg.res) # FIXME: better way to define res
    timesc = trio.fail_after(RES.T) if hasattr(RES, 'T') else nullcontext()
    await notify(f"{carg.head}:4243", b"REG"+pickle.dumps((GVAR.instance, RES)))
    print("worker launched")
    async with trio.open_nursery() as _cn, \
               SocketChannel(":4242", listen=True, _n=_cn) as so, \
               trio.open_nursery() as _n:
        try:
            with timesc:
                async for msg in so:
                    if msg == b"FIN": # end of queue / low health / server error
                        print("received FIN from head, worker exits")
                        break
                    tid, res, fn, args, kwargs = pickle.loads(msg)
                    _n.start_soon(exerf, tid, res, partial(fn, *args, **kwargs), so)
                else:
                    print("connection to head lost, worker exits")
                    so.send = anop
        except BaseException as e:
            print(f"interrupted by {e.__class__.__name__}, notify head")
            await notify(f"{carg.head}:4243", b"UNR"+GVAR.instance.encode())
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
    argp.add_argument('--head', help="address of Grain's head instance")
    argp.add_argument('--res', '-r', help="the resource owned by the worker (e.g. Node(N=16,M=28)&WTime(1800)")
    carg = argp.parse_args()

    GVAR.instance = trio.socket.gethostname()
    trio.run(grain_worker)
