import trio
from pynng import Pair0
import dill as pickle

from functools import partial
import traceback

async def exerf(tid, func):
    try:
        r = await func()
    except BaseException:
        tid, r = -1, (func, traceback.format_exc())
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
            tid, fn, args, kwargs = pickle.loads(msg)
            _n.start_soon(exerf, tid, partial(fn, *args, **kwargs))

if __name__ == "__main__":
    rep = Pair0(listen="tcp://0.0.0.0:4242")
    print("worker launched")
    trio.run(grain_worker)
    rep.close()
