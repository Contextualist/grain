import trio
import dill as pickle

from functools import partial
import traceback

from .contextvar import GVAR
from .pair import SocketChannel

async def exerf(tid, res, func, so):
    GVAR.res = res
    try:
        r = await func()
    except BaseException as e:
        if type(e) is trio.Cancelled: e = WorkerCancelled()
        tid, r = -tid, (func, traceback.format_exc(), e) # negative tid for failure
    finally:
        with trio.move_on_after(3) as cleanup_scope:
            cleanup_scope.shield = True
            await so.send(pickle.dumps((tid, r)))

async def grain_worker():
    print("worker launched")
    async with trio.open_nursery() as _cn, \
               SocketChannel(":4242", listen=True, _n=_cn) as so, \
               trio.open_nursery() as _n:
        try:
            async for msg in so:
                if msg == b"FIN": # end of queue / low health / server error
                    print("received FIN from head, worker exits")
                    break
                tid, res, fn, args, kwargs = pickle.loads(msg)
                _n.start_soon(exerf, tid, res, partial(fn, *args, **kwargs), so)
            else:
                print("connection to head lost, worker exits")
        finally:
            _n.cancel_scope.cancel()

class WorkerCancelled(BaseException):
    def __str__(self):
        return "Cancelled"

if __name__ == "__main__":
    GVAR.instance = trio.socket.gethostname()
    trio.run(grain_worker)
