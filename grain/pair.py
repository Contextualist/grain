import trio

from math import inf as INFIN
from functools import partial
import struct

async def notify(addr, msg): # TODO: retry until connected
    """Open a connection, send `msg`, then close the
    connection immediately.
    To be used with `listen_signal`.
    """
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


FMT, LEN = '>L', 4 # unsigned long / uint32
# +--------+-----------+
# | LEN(4) | DATA(LEN) |
# +--------+-----------+
class SocketChannel(trio.abc.SendChannel, SocketReceiveChannel):
    """Dial to one endpoint / accept one connection in
    order to setup a single deplex connection.
    `receive` returns item type of `data: byte`
    """
    def __init__(self, addr, _n, listen=False, dial=False, manual_close=True):
        SocketReceiveChannel.__init__(self, addr, _n)
        self._so = None
        self._send_lock = trio.Lock()
        assert listen != dial
        self.listen = listen
        self.manual_close = manual_close
    async def __aenter__(self):
        if self.listen:
            await self._n.start(partial(serve_tcp, self._handler, self.port, host=self.host, cs=self._cs))
        else:
            self._so = await trio.open_tcp_stream(self.host, self.port, happy_eyeballs_delay=INFIN)
            self._n.start_soon(self._handler_d, self._so)
        return self
    async def _handler(self, s):
        self._so = s
        size, data = 0, b'' # TODO: use byte buffer
        async with (s if not self.manual_close else nullacontext()):
            async for x in s:
                data += x
                if not size:
                    if len(data) >= LEN:
                        (size,), data = struct.unpack(FMT, data[:LEN]), data[LEN:]
                    else:
                        continue
                while size and len(data) >= size: # loop to consume sticky end
                    self.in_s.send_nowait(data[:size]) # NOTE: return data only
                    size, data = 0, data[size:]
                    if len(data) >= LEN:
                        (size,), data = struct.unpack(FMT, data[:LEN]), data[LEN:]
            else: # socket terminated
                await self.in_s.aclose()
    async def _handler_d(self, s):
        # for listeners, we cancel the accept loop, while here we cancel the only stream
        with self._cs:
            await self._handler(s)
    async def send(self, data):
        if not self._so: raise TypeError("socket not connected")
        if not data: return
        size = struct.pack(FMT, len(data))
        async with self._send_lock:
            await self._so.send_all(size+data)


# adapted from `trio.serve_tcp`, adding a CancelScope that terminates the listeners
async def serve_tcp(handler, port, cs, *, host=None, task_status=trio.TASK_STATUS_IGNORED):
    with cs:
        listeners = await trio.open_tcp_listeners(port, host=host)
        await trio.serve_listeners(handler, listeners, task_status=task_status)


def parse_addr(host_port):  
    host, port = host_port.split(':')
    if not host: host = "0.0.0.0"
    return host, int(port)

class nullacontext(object):
    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        return False
