import trio
import dill as pickle
import toml

from functools import partial
import traceback
import argparse
import time
from io import StringIO

from .contextvar import GVAR
from . import resource
from .pair import notify, SocketChannel
from .subproc import subprocess_pool_daemon

pickle_dumps = partial(pickle.dumps, protocol=4)
pickle_loads = pickle.loads

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
            await so.send(pickle_dumps((tid, r)))

NO_NEXT_URL = "NO_NEXT_URL"

async def grain_worker(RES, url):
    timesc = nullcontext()
    if hasattr(RES, 'T'):
        timesc = trio.fail_after(max(int(RES.deadline - time.time()), 0))
    passive = not (url and RES)
    if passive:
        sockopt = dict(url="tcp://:4242", listen=True)
        print("passive mode enabled")
    else:
        sockopt = dict(url=url, dial=True) # TODO: connection timeout
        print(f"connecting to head using {url!r}...")
    async with trio.open_nursery() as _cn, \
               SocketChannel(**sockopt, _n=_cn) as so, \
               trio.open_nursery() as _n:
        await _n.start(subprocess_pool_daemon)
        if not passive:
            await so.send(b"CON"+pickle_dumps((GVAR.instance, RES)))
        print("worker launched")
        try:
            with timesc:
                async for msg in so:
                    if msg == b"FIN": # end of queue / low health / server error
                        print("received FIN from head, worker exits")
                        return NO_NEXT_URL
                    elif msg == b"HBT": # heartbeat
                        await so.send(b"HBT")
                        continue
                    elif msg[:3] == b"REC": # reconnect
                        return msg[3:].decode()
                    tid, res, fn = pickle_loads(msg)
                    _n.start_soon(exerf, tid, res, fn, so)
                else:
                    print("connection to head lost, worker exits")
                    so.send = anop
                    return url # connection loss, reconnect to the same addr?
        except BaseException as e:
            if passive:
                print(f"interrupted by {e.__class__.__name__}")
                return NO_NEXT_URL # `GVAR.instance` might differ from head's record, so don't notify
            print(f"interrupted by {e.__class__.__name__}, notify head")
            await notify(url, b"UNR"+GVAR.instance.encode(), seg=True)
            if (await so.receive()) != b"FIN": assert False
            print("received FIN from head, worker exits")
            return NO_NEXT_URL
        finally:
            _n.cancel_scope.cancel()

async def __loop():
    RES = parse_res(carg.res)
    url = carg.url
    while url != NO_NEXT_URL:
        url = await grain_worker(RES, url)

def parse_res(res_str):
    res_dict = toml.load(StringIO(res_str.replace('\\n', '\n')))
    RES = resource.ZERO
    for rn, rargs in res_dict.items():
        RES &= getattr(resource, rn)(**rargs)
    return RES

class nullcontext(object):
    def __enter__(self): return self
    def __exit__(self, *exc): return False

async def anop(*_): pass

class WorkerCancelled(BaseException):
    def __str__(self):
        return "Cancelled"

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Worker instance for Grain")
    argp.add_argument('--url', default="", help="URL to connect to Grain's head instance")
    argp.add_argument('--res', '-r', default="None", help=r'the resource owned by the worker, in TOML '
                                                          r'(e.g. "Node = { N=16, M=32 }\nWTime = { T=\"1:00:00\", countdown=true }")')
    carg = argp.parse_args()

    GVAR.instance = trio.socket.gethostname()
    trio.run(__loop)
