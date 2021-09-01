import trio
import dill as pickle

from functools import partial
import traceback
import argparse
import time
from io import StringIO
import json
import logging
logger = logging.getLogger(__name__)

from .contextvar import GVAR
from . import resource
from .pair import notify, SocketChannel
from .util import load_contextmod, nullacontext

pickle_dumps = partial(pickle.dumps, protocol=4)
pickle_loads = pickle.loads

async def exerf(tid, res, func, so):
    GVAR.res = res
    try:
        with trio.fail_after(res.T) if hasattr(res, 'T') else nullacontext():
            ok, r = True, await func()
    except BaseException as e:
        if type(e) is trio.Cancelled: e = WorkerCancelled()
        ok, r = False, (traceback.format_exc(), e)
    finally:
        with trio.move_on_after(3) as cleanup_scope:
            cleanup_scope.shield = True
            await so.send(dict(tid=tid, ok=ok, result=pickle_dumps(r)))

NO_NEXT_URL = "NO_NEXT_URL"

async def grain_worker(RES, url):
    timesc = nullacontext()
    if hasattr(RES, 'T'):
        timesc = trio.fail_after(max(int(RES.deadline - time.time()), 0))
    passive = not (url and RES)
    if passive:
        sockopt = dict(url="tcp://:4242", listen=True)
        logger.info("passive mode enabled")
    else:
        sockopt = dict(url=url, dial=True) # TODO: connection timeout
        logger.info(f"connecting to head using {url!r}...")
    async with trio.open_nursery() as _cn, \
               SocketChannel(**sockopt, _n=_cn) as so, \
               trio.open_nursery() as _n:
        if not passive:
            await so.send(dict(cmd="CON", name=GVAR.instance, res=RES))
        logger.info("worker launched")
        try:
            with timesc:
                async for msg in so:
                    if 'cmd' not in msg:
                        tid, res, fn = msg['tid'], msg['res'], pickle_loads(msg['func'])
                        _n.start_soon(exerf, tid, res, fn, so)
                        continue
                    cmd = msg['cmd']
                    if cmd == "FIN": # end of queue / low health / server error
                        logger.info("received FIN from head, worker exits")
                        return NO_NEXT_URL
                    elif cmd == "HBT": # heartbeat
                        await so.send(dict(cmd="HBT"))
                        continue
                    elif cmd == "REC": # reconnect
                        return msg['name']
                else:
                    logger.warning("connection to head lost, worker exits")
                    so.send = anop
                    return url # connection loss, reconnect to the same addr?
        except BaseException as e:
            if passive:
                logger.info(f"interrupted by {e.__class__.__name__}")
                return NO_NEXT_URL # `GVAR.instance` might differ from head's record, so don't notify
            logger.info(f"interrupted by {e.__class__.__name__}, notify head")
            await notify(url, dict(cmd="UNR", name=GVAR.instance), seg=True)
            if (await so.receive()) != {'cmd': 'FIN'}: assert False
            logger.info("received FIN from head, worker exits")
            return NO_NEXT_URL
        finally:
            _n.cancel_scope.cancel()

async def __loop():
    RES = parse_res(carg.res)
    url = carg.url
    async with load_contextmod(carg.context)():
        while url != NO_NEXT_URL:
            url = await grain_worker(RES, url)

def parse_res(res_str):
    res_dict = json.loads(res_str.replace('\\n', '\n'))
    RES = resource.ZERO
    for rn, rargs in res_dict.items():
        RES &= getattr(resource, rn)(**rargs)
    return RES

async def anop(*_): pass

class WorkerCancelled(BaseException):
    def __str__(self):
        return "Cancelled"

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Worker instance for Grain")
    argp.add_argument('--url', default="", help="URL to connect to Grain's head instance")
    argp.add_argument('--res', '-r', default="None", help='the resource owned by the worker, in JSON '
                                                          '(e.g. \'{"Node": { "N": 16, "M": 32 }, "WTime": { "T": "1:00:00", "countdown": true }}\')')
    argp.add_argument('--context', default="", help="context module file")
    carg = argp.parse_args()

    GVAR.instance = trio.socket.gethostname()
    trio.run(__loop)
