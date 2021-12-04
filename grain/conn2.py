"""Edge protocol: connection discovery depending on network filesystem only
"""
import trio
from trio import socket
import psutil

from pathlib import Path
import json
import os
import fcntl
import logging
logger = logging.getLogger(__name__)

from .conn import use_or_open_nursery, _run_handler

HOST = socket.gethostname()

# """edge file spec"""
# class Listener:
#     host: str
#     lid:  int
#     urls: dict[str, str] # iface: url
# class Dialer:
#     host: str
#     urls: dict[str, str] # iface: url
# class EdgeFile:
#     listener: Listener
#     dialer:   list[Dialer]

async def open_tcp_edge_stream(*, edge_file):
    edge_file = Path(edge_file)
    edge_lock = edge_file.with_suffix('.lock')
    async with UnixFileLock(edge_lock):
        info = {}
        if edge_file.exists():
            info = json.loads(edge_file.read_text())
        if (linfo := info.get('listener')) is not None: # try connecting to the listener
            logger.debug(f"Try connecting to listener {linfo['host']}")
            urls = linfo['urls']
            if linfo['host'] == HOST and 'UDS' in urls: # use Unix domain socket if local
                urls = dict(UDS=urls['UDS'])
            stream = await try_urls(urls.items())
            if stream is not None:
                return stream
            logger.warning(f"Failed to established a connection with {linfo['host']}")

        # fall back: listen & enqueue self
        listeners, urls = await listen_all_iface()
        info.setdefault('dialer', []).append(dict(
            host=HOST, urls=urls,
        ))
        edge_file.write_text(json.dumps(info))
    stream = None
    async def _one_listener(l, cs):
        nonlocal stream
        stream = await l.accept()
        cs.cancel()
    async with trio.open_nursery() as _n:
        for l in listeners:
            _n.start_soon(_one_listener, l, _n.cancel_scope)
    return stream

async def serve_tcp_edge(handler, *, edge_file, handler_nursery=None, task_status=trio.TASK_STATUS_IGNORED):
    """Try connecting to all pending dialers, then listen and
    annonce itself.
    """
    edge_file = Path(edge_file)
    edge_lock = edge_file.with_suffix('.lock')
    async with use_or_open_nursery(handler_nursery) as _n:
        started = False
        async with UnixFileLock(edge_lock):
            if edge_file.exists():
                info = json.loads(edge_file.read_text())
                if (linfo := info.get('listener', None)) is not None:
                    logger.warning(f"Using an edge file claimed by another listener on host {linfo['host']}, "
                                    "which might be running or didn't exit cleanly.")
                for dinfo in info.get('dialer', []): # try connecting to all pending dialers
                    logger.debug(f"Try connecting to pending dialer {dinfo['host']}")
                    stream = await try_urls(dinfo['urls'].items())
                    if stream is None:
                        logger.warning(f"Failed to establish a connection with {dinfo['host']}")
                        continue
                    _n.start_soon(_run_handler, stream, handler)
                    if not started: # eagerly admit if any handler might start running
                        task_status.started()
                        started = True

            # listen on every iface
            listeners, urls = await listen_all_iface()
            lid = hash(tuple(urls.values()))
            # override, even if a server has been started before the current one
            edge_file.write_text(json.dumps(dict(
                listener=dict(host=HOST, lid=lid, urls=urls),
            )))

        try:
            # TODO: Unix domain socket server
            await trio.serve_listeners(handler, listeners, handler_nursery=_n, task_status=task_status if not started else trio.TASK_STATUS_IGNORED)
        finally:
            with trio.move_on_after(1) as cleanup_scope:
                cleanup_scope.shield = True
                async with UnixFileLock(edge_lock):
                    if edge_file.exists() and json.loads(edge_file.read_text())['listener']['lid'] == lid:
                        edge_file.unlink() # delete only if no other server is running


async def try_urls(urls, happy_eyeballs_delay=0.250):
    from .pair import parse_url, open_tcp_stream # avoid cyclic import

    winning_stream = None
    async def attempt_connect(attempt_failed, *sargs):
        nonlocal winning_stream
        try:
            winning_stream = await open_tcp_stream(*sargs)
            _n.cancel_scope.cancel()
        except OSError as e:
            logger.debug(f"OSError: {e}")
            attempt_failed.set()

    async with trio.open_nursery() as _n:
        for ifn, url in urls:
            logger.debug(f"Trying {ifn}: {url}")
            proto, host, port, opts = parse_url(url)
            attempt_failed = trio.Event()
            _n.start_soon(attempt_connect, attempt_failed, proto, host, port, opts)
            with trio.move_on_after(happy_eyeballs_delay):
                await attempt_failed.wait()
    return winning_stream

def make_ipaddr(addr, port):
    return f"[{addr}]:{port}" if ':' in addr else f"{addr}:{port}"

async def listen_all_iface():
    listeners = {
        ifn: (await trio.open_tcp_listeners(0, host=ifaddr.address))[0]
        for ifn, ifaddrs in psutil.net_if_addrs().items() if ifn != 'lo'
            for ifaddr in ifaddrs if ifaddr.family in {socket.AF_INET}#, socket.AF_INET6}
    } # FIXME: ipv6
    urls = {
        ifn: f"tcp://{make_ipaddr(*s.socket.getsockname())}"
        for ifn, s in listeners.items()
    }
    return list(listeners.values()), urls

class UnixFileLock:
    POLL_TIME = 0.01
    def __init__(self, filename):
        self._filename = filename
        self._fd = None
    async def acquire(self):
        fd = os.open(self._filename, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                await trio.sleep(self.POLL_TIME)
            else:
                self._fd = fd
                return self
    async def release(self, *_):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    __aenter__ = acquire
    __aexit__ = release
