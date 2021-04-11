import trio

from math import inf as INFIN
from functools import partial
from urllib.parse import urlparse, parse_qsl

from .conn import open_tcp_stream_to_head, serve_tcp_p2p
from .conn_msgp import iter_packet, send_packet

async def notify(url, msg, seg=False): # TODO: retry until connected
    """Open a connection, send `msg`, then close the
    connection immediately.
    To be used with `listen_signal`.
    Or set `seg=True` to talk to `SocketChannel`.
    """
    proto, host, port, opts = parse_url(url)
    async with await open_tcp_stream(proto, host, port, opts) as s:
        if seg:
            await send_packet(s, msg)
        else:
            await s.send_all(msg)

class SocketReceiveChannel(trio.abc.ReceiveChannel):
    def __init__(self, url, _n):
        self.proto, self.host, self.port, self.opts = parse_url(url)
        self.in_s, self.in_r = trio.open_memory_channel(INFIN)
        self._n = _n # for any background loops
        self._cs = trio.CancelScope() # for terminating all loops while keep _n intact
    async def receive(self):
        return await self.in_r.receive()
    async def aclose(self):
        async with self.in_r, self.in_s:
            self._cs.cancel()

class EphemeralSocketReceiveChannel(SocketReceiveChannel):
    """Accept any connection. For each connection
    receive a single fragment (trailed by EOF) of data,
    then immediately close the connection.
    `receive` returns item type of
    `((addr: str, port: int), data: byte)`.
    To be used with `notify`.
    """
    async def __aenter__(self):
        await self._n.start(partial(serve_tcp, self.proto, self._handler,
                                    self.port, host=self.host, opts=self.opts, cs=self._cs))
        return self
    async def _handler(self, s):
        async with s: # one msg per connection
            msg = b''
            async for x in s: msg += x
            self.in_s.send_nowait((s.socket.getpeername(), msg))

listen_signal = EphemeralSocketReceiveChannel


class SocketChannel(trio.abc.SendChannel, SocketReceiveChannel):
    """Dial to one endpoint / accept one connection in
    order to setup a single duplex connection.
    Alternatively, pass in a connected socket stream.
    `receive` returns item type of `data: byte`
    """
    def __init__(self, url, _n=None, listen=False, dial=False, _so=None):
        SocketReceiveChannel.__init__(self, url, _n)
        self._send_lock = trio.Lock()
        assert (listen != dial and _n is not None) or _so is not None
        self._so, self.listen, self.dial = _so, listen, dial
        self.is_clean = True
    async def __aenter__(self):
        if self.listen:
            await self._n.start(partial(serve_tcp, self.proto, self._handler,
                                        self.port, host=self.host, opts=self.opts, cs=self._cs))
        elif self.dial:
            self._so = await open_tcp_stream(self.proto, self.host, self.port, self.opts)
            self._n.start_soon(self._handler_standalone, self._so)
        return self
    async def _handler(self, s):
        self._so = s
        async with s:
            async for p in iter_packet(s):
                self.in_s.send_nowait(p)
            else: # socket terminated by remote
                self.is_clean = False
                await self.in_s.aclose()
    async def _handler_standalone(self, s):
        # for listeners, we cancel the accept loop, while here we cancel the only stream
        with self._cs:
            await self._handler(s)
    async def send(self, data):
        if not self._so: raise TypeError("socket not connected")
        if not data: return
        async with self._send_lock:
            await send_packet(self._so, data)
    async def try_send(self, data):
        try:
            await self.send(data)
        except trio.ClosedResourceError:
            pass


class SocketChannelAcceptor(SocketReceiveChannel):
    """Listener-like object that wraps the accepted TCP socket
    connections with `SocketChannel`.
    It also implements `trio.abc.ReceiveChannel`, so it can be
    used as a generator of `SocketChannel`. Note that the
    `SocketChannel` it returns is already connected and has its
    internal loop run under an external nursery. This implies
    1) its `__aenter__` is a NOP, b/c it is ready to be used,
    and 2) calling `SocketChannelAcceptor.aclose` will not
    close any child `SocketChannel`.
    """
    async def __aenter__(self):
        await self._n.start(partial(serve_tcp, self.proto, self._handler, self.port, host=self.host,
                                    handler_nursery=self._n, opts=self.opts, cs=self._cs))
        return self
    async def _handler(self, so):
        # TODO: support unix server
        host, port, *_ = so.socket.getpeername()
        if so.socket.proto == 6:
            host = f"[{host}]"
        c = SocketChannel(f"tcp://{host}:{port}", _so=so)
        self.in_s.send_nowait(c)
        await c._handler_standalone(so) # to have the same lifetime as c
    accept = SocketReceiveChannel.receive


async def open_tcp_stream(proto, host, port, opts=None):
    if proto == "tcp":
        return await trio.open_tcp_stream(host, port, happy_eyeballs_delay=INFIN)
    elif proto == "bridge":
        assert opts
        return await open_tcp_stream_to_head(bridge=(host, port), **opts)
    elif proto == "unix":
        return await trio.open_unix_socket(host)

# adapted from `trio.serve_tcp`, adding a CancelScope that terminates the listeners
async def serve_tcp(proto, handler, port, cs, *, host=None, handler_nursery=None, opts=None, task_status=trio.TASK_STATUS_IGNORED):
    with cs:
        if proto == "tcp":
            listeners = await trio.open_tcp_listeners(port, host=host)
            await trio.serve_listeners(handler, listeners, handler_nursery=handler_nursery, task_status=task_status)
        elif proto == "bridge":
            assert opts
            await serve_tcp_p2p(handler, bridge=(host,port), handler_nursery=handler_nursery, task_status=task_status, **opts)
        elif proto == "unix":
            raise NotImplementedError("Unix domain socket server is not supported")

def parse_url(url):
    u = urlparse(url)
    if u.scheme == "tcp":
        return u.scheme, u.hostname, u.port, {}
    elif u.scheme == "bridge":
        assert u.username, "a session key must be specified for the bridge protocol"
        return u.scheme, u.hostname, u.port, { "key": u.username, **dict(parse_qsl(u.query)) }
    elif u.scheme == "unix":
        return u.scheme, u.path, None, {}
    else:
        raise ValueError(f"Unsupported protocol {u.scheme!r}")
