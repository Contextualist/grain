import trio
import psutil

from .conn_msgp import send_packet
from .pair import SocketChannel
from .util import WaitGroup, pickle_dumps, pickle_loads, timeblock

import os
import secrets
import sys
from functools import partial
from math import inf as INFIN
import getpass
import argparse
import logging
logger = logging.getLogger(__name__)

DAEMON = object()

class RemoteExecutor:
    """Pass the jobs on to an external scheduler"""
    def __init__(self, _n=None, nolocal=False, config=None, gnaw=DAEMON, name="", prioritized=False, **kwargs):
        if kwargs:
            logger.warning(f"kwargs {kwargs} are ignored")
        assert nolocal, "RemoteExecutor has no local worker, as scheduling is delegated"
        self.gnaw = gnaw
        self.name = name + ("-p" if prioritized else "")
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.jobn = 0
        assert _n is not None
        self._n = _n
        self._c = None
        self._cs = None
        self._wg = WaitGroup() # track the entire lifetime of each job
        if gnaw is DAEMON:
            self.listen = config.listen
            self.gnaw_conf = config.gnaw

    def submit(self, res, fn, *args, **kwargs):
        tid = self.jobn = self.jobn+1
        self.push_job.send_nowait((tid, res, partial(fn, *args, **kwargs)))
        return tid

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()
        await self._c.aclose()
    async def _sender(self):
        async with self.pull_job: # XXX: currently no ratelimit on sending
            async for tid, res, fargs in self.pull_job:
                self._wg.add()
                await send_packet(self._c._so, dict(tid=tid, res=res, func=pickle_dumps(fargs))) # We don't need locking
    async def run(self):
        if self.gnaw is DAEMON: # gnaw daemon with unixconn
            # process detection
            whoami = getpass.getuser()
            for p in psutil.process_iter(['cmdline', 'username', 'name']):
                if p.info['username'] != whoami or p.info['name'] != 'gnaw':
                    continue
                pargs = p.info['cmdline']
                parser = argparse.ArgumentParser()
                parser.add_argument('-wurl', '--wurl')
                parser.add_argument('-hurl', '--hurl')
                r, _ = parser.parse_known_args(pargs)
                if r.wurl != self.listen:
                    continue
                if r.hurl is None:
                    raise RuntimeError(f"The running Gnaw instance {pargs} does not have a `hurl` arg")
                logger.info(f"found a running Gnaw instance for {self.listen!r}, going to attach")
                self.gnaw = r.hurl
                break
            else:
                logger.info(f"starting a Gnaw instance at {self.listen!r}")
                self.gnaw = f"unix:///tmp/gnaw-{secrets.token_urlsafe()}"
                conf = self.gnaw_conf
                _ = await trio.open_process(
                    ["gnaw", "-hurl", self.gnaw, "-wurl", self.listen, "-n", str(conf.max_conn),
                             "-log", conf.log_file, "-t", conf.idle_quit, "-swarm", str(conf.swarm), *conf.extra_args],
                    start_new_session=True, # daemon
                )
                await trio.sleep(0.1) # wait for gnaw startup
        with timeblock("all jobs"):
            async with SocketChannel(self.gnaw, dial=True, _n=self._n) as self._c, \
                       self.push_result:
                await send_packet(self._c._so, dict(name=self.name)) # handshake
                self._n.start_soon(self._sender)
                async for x in self._c:
                    if x['exception']: # display exception
                        tb, exp = pickle_loads(x['result'])
                        logger.error(f"Exception from task: {x['exception']}: {exp}\n{tb}")
                        continue
                    self.push_result.send_nowait((x['tid'], pickle_loads(x['result'])))
                    self._wg.done()
            if not self._c.is_clean:
                raise RuntimeError("connection to Gnaw lost unexpectedly")
    async def __aenter__(self):
        self._n.start_soon(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        self._n.start_soon(self.sealer)
