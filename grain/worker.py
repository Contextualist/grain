import trio
from pynng import Pair0
import dill as pickle

from functools import partial
import traceback
import socket

from .contextvar import GVAR

async def exerf(tid, res, func):
    GVAR.res = res
    try:
        r = await func()
    except BaseException as e:
        if type(e) is trio.Cancelled: e = "trio.Cancelled"
        tid, r = -tid, (func, traceback.format_exc(), e) # negative tid for failure
    finally:
        await rep.asend(pickle.dumps((tid, r)))

async def grain_worker():
    async with trio.open_nursery() as _n:
        while True:
            msg = await rep.arecv()
            if msg == b"FIN": # end of queue / exception
                print("received FIN from head, worker exits")
                _n.cancel_scope.cancel()
                break
            tid, res, fn, args, kwargs = pickle.loads(msg)
            _n.start_soon(exerf, tid, res, partial(fn, *args, **kwargs))

if __name__ == "__main__":
    GVAR.instance = socket.gethostname()
    rep = Pair0(listen="tcp://0.0.0.0:4242")
    print("worker launched")
    trio.run(grain_worker)
    rep.close()
