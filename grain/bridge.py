"""This is the first reference implementation, and it
will be removed in the future. Use the Go implementation
instead, which has more features and consumes less resources.
"""
import trio

from math import inf as INFIN
from collections import defaultdict
import argparse
from datetime import datetime
log = lambda s: print(f"[{datetime.now().strftime('%y/%m/%d %H:%M:%S')}]\t{s}", flush=True)

from .conn import send_packet, recv_packet

subd2head = defaultdict(lambda: trio.open_memory_channel(INFIN)) # { session_key: chan }
head2subd = defaultdict(lambda: trio.open_memory_channel(INFIN)) # { subd_publ_addr: chan }


async def _head_quit(s, cs):
    try:
        _ = await s.receive_some()
    except trio.BrokenResourceError:
        log("head connection is broken")
    finally:
        cs.cancel()
async def _head_loop(s, key):
    log(f"head {key} is ready")
    async for subd in subd2head[key][1]:
        await send_packet(s, subd)
        log(f"informed head {key} of new subd {subd}")

async def bridge(port):
    async def _handler(s):
        x_pbhost, x_pbport = s.socket.getpeername()
        x_publ = f"{x_pbhost}:{x_pbport}"
        try:
            CMD, key, payload = (await recv_packet(s)).decode().split(',')
        except (EOFError, trio.BrokenResourceError):
            log(f"broken connection from {x_publ}")
            return
        if CMD == "INIT": # head subscribes to subds from session {key}
            async with trio.open_nursery() as _n:
                _n.start_soon(_head_quit, s, _n.cancel_scope)
                _n.start_soon(_head_loop, s, key)
            log(f"head {key} quits")
        elif CMD == "SUBD": # subd requests connection to head in session {key}
            subd_publ, subd_priv = x_publ, payload
            log(f"subd {subd_publ} requests connection with head {key}")
            subd2head[key][0].send_nowait(f"{subd_publ}|{subd_priv}".encode())
            # NOTE: after this point, subd might close connection. Head shall make appropriate judgement 
            try:
                await send_packet(s, await head2subd[subd_publ][1].receive())
            except trio.BrokenResourceError:
                log(f"broken connection from {subd_publ}")
            else:
                log(f"subd {subd_publ} was assigned to an endpoint from head {key}")
            del head2subd[subd_publ]
        elif CMD == "HEAD": # head replies subd {subd_publ} with an available endpoint
            subd_publ, head_publ, head_priv = key, x_publ, payload
            head2subd[subd_publ][0].send_nowait(f"{head_publ}|{head_priv}".encode())
        else:
            log(f"unrecognized command {CMD} from {x_publ} ({key},{payload})")
    await trio.serve_tcp(_handler, port)

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Bridge rendezvous server")
    argp.add_argument('--port', '-p', type=int, default=9555, help="port for the bridge server")
    carg = argp.parse_args()

    trio.run(bridge, carg.port)
