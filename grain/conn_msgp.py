"""Packet handling with msgpack, compatible with functions from `conn.py`.
This file will eventually merge into `conn.py` once we finish migrating all
communications to msgpack.
"""
import msgpack
import trio

from . import resource

_p = msgpack.Packer()

async def send_packet(s: trio.SocketStream, obj):
    if 'res' in obj:
        obj['res'] = obj['res'].encode_msgp()
    await s.send_all(_p.pack(obj))

def decode_res(obj):
    if 'res' in obj:
        res = resource.ZERO
        for rn, rargs in obj['res'].items():
            res &= getattr(resource, rn)(**rargs)
        obj['res'] = res
    return obj

async def iter_packet(s: trio.abc.ReceiveStream):
    _u = msgpack.Unpacker()
    while True:
        try:
            data = await s.receive_some()
        except trio.BrokenResourceError:
            return
        if data == b"": # end of receive stream
            return
        _u.feed(data)
        for msg in _u:
            if type(msg) is not dict:
                print("received malformed packet:", data)
                return
            yield decode_res(msg)

async def recv_packet(s: trio.abc.ReceiveStream):
    try:
        return await (iter_packet(s).__aiter__().__anext__())
    except StopAsyncIteration:
        raise EOFError("end of receive stream")
