import logging
logging.getLogger('grain').setLevel(logging.DEBUG)
from .conn2 import *

import trio
import tempfile
from functools import partial

def tmpfname():
    with tempfile.NamedTemporaryFile() as f:
        return f.name

async def test_ping():
    async def _dial(edge_file):
        c = await open_tcp_edge_stream(edge_file=edge_file)
        async with c:
            await c.send_all(b"pong")
            assert (await c.receive_some()) == b"ping"
    async def _listen(edge_file, task_status=trio.TASK_STATUS_IGNORED):
        cs = trio.CancelScope()
        async def _handler(s):
            async with s:
                await s.send_all(b"ping")
                assert (await s.receive_some()) == b"pong"
            cs.cancel()
        with cs:
            await serve_tcp_edge(_handler, edge_file=edge_file, task_status=task_status)

    ef = tmpfname()
    async with trio.open_nursery() as _n:
        await _n.start(_listen, ef)
        await _dial(ef)
    async with trio.open_nursery() as _n:
        _n.start_soon(_dial, ef)
        await trio.sleep(.1)
        await _listen(ef)

async def test_double_listen(caplog):
    ef = tmpfname()
    async def _nop(s):
        pass
    async with trio.open_nursery() as _n:
        await _n.start(partial(serve_tcp_edge, _nop, edge_file=ef))
        await _n.start(partial(serve_tcp_edge, _nop, edge_file=ef))
        _n.cancel_scope.cancel()
    assert "another listener" in caplog.text
