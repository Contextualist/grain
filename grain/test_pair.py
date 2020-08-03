from .pair import *

import pytest
import trio
trio_open_tcp_listeners = trio.open_tcp_listeners
from trio.testing import MockClock, open_stream_to_socket_listener

from functools import wraps

def mock_network(fn):
    listeners = {}
    async def open_tcp_listeners(port, *, host, **__):
        l, *_ = await trio_open_tcp_listeners(0) # take only one
        nonlocal listeners
        listeners[(host,port)] = l
        return [l]
    async def open_tcp_stream(host, port, **__):
        return await open_stream_to_socket_listener(listeners[(host,port)])

    @wraps(fn)
    async def __wrapped(monkeypatch):
        monkeypatch.setattr(trio, "open_tcp_listeners", open_tcp_listeners)
        monkeypatch.setattr(trio, "open_tcp_stream", open_tcp_stream)
        return await fn(monkeypatch)
    return __wrapped


@mock_network
async def test_signal(monkeypatch):
    # plain
    async def _listen(_n, task_status=trio.TASK_STATUS_IGNORED):
        async with listen_signal("tcp://test:8000", _n) as l:
            task_status.started()
            async for (_, m) in l:
                assert m == b"msg"
                break
            else:
                assert False, "listen_signal close before receiving"
    async with trio.open_nursery() as _n:
        await _n.start(_listen, _n)
        await notify("tcp://test:8000", b"msg")

    # segment
    async def _listen_sc(_n, task_status=trio.TASK_STATUS_IGNORED):
        async with SocketChannel("tcp://test:8001", _n=_n, listen=True) as l:
            task_status.started()
            async for m in l:
                assert m == dict(cmd="test")
                break
            else:
                assert False, "SocketChannel close before receiving"
    async with trio.open_nursery() as _n:
        await _n.start(_listen_sc, _n)
        await notify("tcp://test:8001", dict(cmd="test"), seg=True)
