"""Gnaw's prototype implementation. Scheduling is provided by the built-in
GrainExecutor. For a better performance, use the Go implementation instead.
"""
import trio
import dill as pickle

import argparse
from io import StringIO
from functools import partial

from .head import GrainExecutor
from .pair import SocketChannelAcceptor
from .util import set_numpy_oneline_repr
set_numpy_oneline_repr()

pickle_dumps = partial(pickle.dumps, protocol=4)
pickle_loads = pickle.loads

CONFIG = """
[head]
listen = "{wurl}"
log_file = "/dev/null"
"""
DOCK_COOLDOWN = 180 # 3min

async def dock_loop(_c, exer, dock, rq):
    async def _rloop(task_status=trio.TASK_STATUS_IGNORED):
        try:
            task_status.started()
            async for i, rslt in rq:
                await _c.send(dict(ok=True, tid=i, result=pickle_dumps(rslt)))
        except trio.ClosedResourceError:
            _n.cancel_scope.cancel()
        # don't close rq, we'll reuse it
    # XXX: should we do heartbeat?
    async with _c, \
               trio.open_nursery() as _n:
        await _n.start(_rloop)
        while True:
            try:
                x = await _c.receive()
            except trio.EndOfChannel:
                break
            tid, res, fn = x['tid'], x['res'], pickle_loads(x['func'])
            # XXX: tid trick. Is this safe?
            exer._submit(tid * MAXDOCKS + dock, res, fn)
        _n.cancel_scope.cancel()
    docks_inuse.remove(dock)
    print(f"RemoteExer ?? at dock {dock} quits")
    await trio.sleep(DOCK_COOLDOWN)
    docks_avail.add(dock)
    print(f"Dock {dock} is now available")

async def relay(inq, chdocks):
    """Receive results from the exer and redistribute to docks"""
    async with inq:
        async for i, rslt in inq:
            if (dc := i % MAXDOCKS) in docks_inuse:
                chdocks[dc].send_nowait((i // MAXDOCKS, rslt))

async def main():
    # buffered for network latency to dock
    chdocks_s, chdocks_r = zip(*[trio.open_memory_channel(300) for _ in range(MAXDOCKS)])
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, nolocal=True, config_file=StringIO(CONFIG), temporary_err=(trio.TooSlowError,)) as exer, \
               SocketChannelAcceptor(_n=_n, url=carg.hurl) as soa:
        _n.start_soon(relay, exer.resultq, chdocks_s)
        async for _c in soa:
            x = await _c.receive()
            assert 'name' in x
            if not docks_avail:
                print(f"Number of RemoteExers exceeds {MAXDOCKS}, reject a connection")
                await _c.close()
                continue
            dc = docks_avail.pop()
            docks_inuse.add(dc)
            _n.start_soon(dock_loop, _c, exer, dc, chdocks_r[dc])
            print(f"RemoteExer ?? connected at dock {dc}")

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Exer-worker hub")
    argp.add_argument('--hurl', help="URL for RemoteExers to connect")
    argp.add_argument('--wurl', help="URL for Workers to connect")
    argp.add_argument('-n', '--maxdocks', type=int, default=3, help="Maximum numbers of RemoteExers allowed to connect")
    carg = argp.parse_args()
    CONFIG = CONFIG.format(wurl=carg.wurl)
    MAXDOCKS = carg.maxdocks
    docks_avail = set(range(MAXDOCKS))
    docks_inuse = set()
    trio.run(main)
