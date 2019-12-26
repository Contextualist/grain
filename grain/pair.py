import trio

from math import inf as INFIN
from functools import partial
import struct
import io

# +--------+-----------+
# | LEN(4) | DATA(LEN) |
# +--------+-----------+
FMT, LEN = '>L', 4 # unsigned long / uint32

async def notify(addr, msg, seg=False): # TODO: retry until connected
    """Open a connection, send `msg`, then close the
    connection immediately.
    To be used with `listen_signal`.
    Or set `seg=True` to talk to `SocketChannel`.
    """
    if seg:
        msg = struct.pack(FMT,len(msg))+msg
    host, port = parse_addr(addr)
    async with await trio.open_tcp_stream(host, port, happy_eyeballs_delay=INFIN) as s:
        await s.send_all(msg)

class SocketReceiveChannel(trio.abc.ReceiveChannel):
    def __init__(self, addr, _n):
        self.host, self.port = parse_addr(addr)
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
        await self._n.start(partial(serve_tcp, self._handler, self.port, host=self.host, cs=self._cs))
        return self
    async def _handler(self, s):
        async with s: # one msg per connection
            msg = b''
            async for x in s: msg += x
            self.in_s.send_nowait((s.socket.getpeername(), msg))

listen_signal = EphemeralSocketReceiveChannel


class SocketChannel(trio.abc.SendChannel, SocketReceiveChannel):
    """Dial to one endpoint / accept one connection in
    order to setup a single deplex connection.
    Alternatively, pass in a connected socket stream.
    `receive` returns item type of `data: byte`
    """
    def __init__(self, addr, _n=None, listen=False, dial=False, _so=None):
        SocketReceiveChannel.__init__(self, addr, _n)
        self._send_lock = trio.Lock()
        assert listen != dial or _so is not None
        self._so, self.listen, self.dial = _so, listen, dial
        self.is_clean = True
    async def __aenter__(self):
        if self.listen:
            await self._n.start(partial(serve_tcp, self._handler, self.port, host=self.host, cs=self._cs))
        elif self.dial:
            self._so = await trio.open_tcp_stream(self.host, self.port, happy_eyeballs_delay=INFIN)
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
        size = struct.pack(FMT, len(data))
        async with self._send_lock:
            await self._so.send_all(size+data)
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
        await self._n.start(partial(serve_tcp, self._handler, self.port, host=self.host,
                                               handler_nursery=self._n, cs=self._cs))
        return self
    async def _handler(self, so): # run under `self._n`
        host, port = so.socket.getpeername()
        c = SocketChannel(f"{host}:{port}", _so=so)
        self.in_s.send_nowait(c)
        await c._handler_standalone(so) # to have the same lifetime as c
    accept = SocketReceiveChannel.receive


# adapted from `trio.serve_tcp`, adding a CancelScope that terminates the listeners
async def serve_tcp(handler, port, cs, *, host=None, handler_nursery=None, task_status=trio.TASK_STATUS_IGNORED):
    with cs:
        listeners = await trio.open_tcp_listeners(port, host=host)
        await trio.serve_listeners(handler, listeners, handler_nursery=handler_nursery, task_status=task_status)


def parse_addr(host_port):  
    host, port = host_port.split(':')
    if not host: host = "0.0.0.0"
    return host, int(port)

async def iter_packet(s: trio.abc.ReceiveStream):
    while True:
        try:
            plen, = struct.unpack(FMT, await receive_exactly(s, LEN))
            yield await receive_exactly(s, plen)
        except (EOFError, trio.BrokenResourceError):
            return

async def receive_exactly(s: trio.abc.ReceiveStream, n):
    buf = io.BytesIO()
    while n > 0:
        data = await s.receive_some(n)
        if data == b"":
            raise EOFError("end of receive stream")
        buf.write(data)
        n -= len(data)
    return buf.getvalue()
