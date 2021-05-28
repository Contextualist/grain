import trio
from trio import socket

import struct
import io
from contextlib import contextmanager, asynccontextmanager
from functools import partial
from math import inf as INFIN
import logging
logger = logging.getLogger(__name__)

RENDEZVOUS_TIMEOUT = 10
CONNECT_RETRY_INTERVAL = 0.5

# +--------+-----------+
# | LEN(4) | DATA(LEN) |
# +--------+-----------+
FMT, LEN = '>L', 4 # unsigned long / uint32


async def bound_socket(local_addr):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    await s.bind(local_addr)
    logger.debug(f"socket bound to {local_addr} created")
    return s

async def accept(s, win_s):
    with closing_otherwise(s):
        logger.debug("Accepting...")
        s.listen()
        conn, _ = await s.accept()
        logger.debug("Accepted")
        win_s.send_nowait(conn)

async def connect(s, peer_addr, win_s):
    with closing_otherwise(s):
        logger.debug(f"Connecting to {peer_addr}")
        while True:
            try:
                await s.connect(peer_addr)
            except Exception as e:
                logger.debug(e)
                await trio.sleep(CONNECT_RETRY_INTERVAL)
                continue
            else:
                logger.debug(f"Connected {peer_addr}")
                break
        win_s.send_nowait(s)

async def init_conn(bridge, iface=""):
    *sarg, _, rbridge = (await socket.getaddrinfo(*bridge, type=socket.SOCK_STREAM))[0]
    retry = 3
    for _ in range(retry):
        sa = socket.socket(*sarg)
        sa.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        await sa.connect(rbridge)
        priv_host, priv_port = sa.getsockname() # self, private
        if iface:
            priv_host, priv_port = get_priv_host(iface), 0
        try:
            s_cona = await bound_socket((priv_host, priv_port)) # for connect, a
            if iface:
                _, priv_port = s_cona.getsockname()
            s_conb = await bound_socket((priv_host, priv_port)) # for connect, b
            s_acp = await bound_socket(('', priv_port)) # for accept
            break
        except OSError: # NOTE: albeit SO_REUSEADDR set, bind still occassionally fails
            logger.debug(f"cannot bind to private addr {priv_host}:{priv_port}, retry")
            sa.close()
            await trio.sleep(0.1)
            continue
    else:
        raise OSError("failed to bind to a local address")
    logger.debug(f"self's private addr {priv_host}:{priv_port}")
    return trio.SocketStream(sa), f"{priv_host}:{priv_port}", s_acp, s_cona, s_conb

async def hole_punching(peer, s_acp, s_cona, s_conb):
    peer_publ_addr, peer_priv_addr = peer
    peer_publ_addr, peer_priv_addr = parse_addr(peer_publ_addr), parse_addr(peer_priv_addr)
    logger.debug(f"peer's public addr {peer_publ_addr}, private addr {peer_priv_addr}")

    win_s, win_r = trio.open_memory_channel(1)
    async with trio.open_nursery() as _n:
        _n.start_soon(accept, s_acp, win_s)
        _n.start_soon(connect, s_cona, peer_publ_addr, win_s)
        if peer_priv_addr != peer_publ_addr:
            _n.start_soon(connect, s_conb, peer_priv_addr, win_s)
        else:
            s_conb.close()
        conn = None
        with trio.move_on_after(RENDEZVOUS_TIMEOUT):
            conn = trio.SocketStream(await win_r.receive())
        if conn is None:
            raise OSError(f"failed to established a P2P connection with {peer}")
        _n.cancel_scope.cancel()
    return conn

"""2RTT per rendz
head            ===INIT,{key},===>           bridge
...
subd      ---SUBD,{key},{subd_priv}--->      bridge
head     <==={subd_publ}|{subd_priv}===      bridge
head   ---HEAD,{subd_publ},{head_priv}--->   bridge
head enters rendz
subd     <---{head_publ}|{head_priv}---      bridge
subd enters rendz
"""
async def open_tcp_stream_to_head(*, bridge, key, iface=""):
    """Open a P2P connection to head.
    """
    sa, priv_addr, s_acp, s_cona, s_conb = await init_conn(bridge, iface)
    async with sa:
        await send_packet(sa, f"SUBD,{key},{priv_addr}".encode())
        head = (await recv_packet(sa)).decode().split('|')
    return await hole_punching(head, s_acp, s_cona, s_conb)

async def serve_tcp_p2p(handler, *, bridge, key, iface="", handler_nursery=None, task_status=trio.TASK_STATUS_IGNORED):
    """Subscribe to subds' connection requests.
    For each request, open a P2P connection to the subd.
    """
    async with await trio.open_tcp_stream(*bridge, happy_eyeballs_delay=INFIN) as s, \
               use_or_open_nursery(handler_nursery) as _n:
        await send_packet(s, f"INIT,{key},".encode())
        task_status.started()
        async for subd in iter_packet(s):
            subd_publ_addr, subd_priv_addr = subd.decode().split('|')
            with suppress_then_log(OSError):
                sa, priv_addr, s_acp, s_cona, s_conb = await init_conn(bridge, iface)
                async with sa:
                    await send_packet(sa, f"HEAD,{subd_publ_addr},{priv_addr}".encode())
                stream = await hole_punching((subd_publ_addr, subd_priv_addr), s_acp, s_cona, s_conb)
                _n.start_soon(_run_handler, stream, handler)
        raise RuntimeError("bridge quits unexpectedly")


def get_priv_host(iface):
    import psutil
    i = psutil.net_if_addrs()[iface]
    return next(x.address for x in i if x.family == socket.AF_INET)

def parse_addr(host_port):
    host, port = host_port.split(':')
    if not host: host = "0.0.0.0"
    return host, int(port)

async def send_packet(s: trio.SocketStream, data):
    await s.send_all(struct.pack(FMT, len(data)) + data)

async def recv_packet(s: trio.abc.ReceiveStream):
    plen, = struct.unpack(FMT, await receive_exactly(s, LEN))
    return await receive_exactly(s, plen)

async def iter_packet(s: trio.abc.ReceiveStream):
    while True:
        try:
            yield await recv_packet(s)
        except (EOFError, trio.BrokenResourceError):
            return

async def receive_exactly(s: trio.abc.ReceiveStream, n):
    buf = io.BytesIO()
    while n > 0:
        # NOTE: Usually when the other end quits (gracefully
        # or not), `s.receive_some` returns b"" (indicating EOF).
        # However, this is not always the case for a P2P connection.
        data = await s.receive_some(n)
        if data == b"":
            raise EOFError("end of receive stream")
        buf.write(data)
        n -= len(data)
    return buf.getvalue()

@contextmanager
def closing_otherwise(s):
    try:
        yield
    except BaseException:
        s.close()
        raise

@asynccontextmanager
async def use_or_open_nursery(_n):
    if _n is not None:
        yield _n
    else:
        async with trio.open_nursery() as _n:
            yield _n

async def _run_handler(s, handler):
    try:
        await handler(s)
    finally:
        await trio.aclose_forcefully(s)

@contextmanager
def suppress_then_log(exctype=Exception):
    try:
        yield
    except exctype as e:
        logger.warning(f"{e.__class__.__name__}: {e}")
