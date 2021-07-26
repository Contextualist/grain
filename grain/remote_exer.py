import trio
import dill as pickle

from .conn_msgp import send_packet
from .pair import SocketChannel, notify
from .util import timeblock, WaitGroup
from .config import load_conf

from math import inf as INFIN
import secrets
import sys
import os
from functools import partial

pickle_dumps = partial(pickle.dumps, protocol=4)
pickle_loads = pickle.loads

class RemoteExecutor:
    """Pass the jobs on to an external scheduler"""
    def __init__(self, _n=None, nolocal=False, config_file=None, gnaw="", gnawtype="go", name="", **kwargs):
        if kwargs:
            print(f"WARNING: kwargs {kwargs} are ignored")
        assert nolocal, "RemoteExecutor has no local worker, as scheduling is delegated"
        self.gnaw = gnaw
        self.gnawtype = gnawtype
        self.name = name
        self.push_job, self.pull_job = trio.open_memory_channel(INFIN)
        self.push_result, self.resultq = trio.open_memory_channel(INFIN)
        self.jobn = 0
        assert _n is not None
        self._n = _n
        self._c = None
        self._cs = None
        self._wg = WaitGroup() # track the entire lifetime of each job
        if gnaw == '':
            conf = load_conf(config_file, mode='')
            self.listen = conf.head.listen
            self.cli_dial = conf.worker.cli_dial

    def submit(self, res, fn, *args, **kwargs):
        tid = self.jobn = self.jobn+1
        self.push_job.send_nowait((tid, res, partial(fn, *args, **kwargs)))
        return tid

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()
        await self._c.aclose()
        if self._cs is not None: # subp gnaw cleanup
            await notify(self.cli_dial, dict(cmd="UNR", name='*'), seg=True)
            self._cs.cancel()
    async def _sender(self):
        async with self.pull_job: # XXX: currently no ratelimit on sending
            async for tid, res, fargs in self.pull_job:
                self._wg.add()
                await send_packet(self._c._so, dict(tid=tid, res=res, func=pickle_dumps(fargs))) # We don't need locking
    async def run(self):
        if self.gnaw == "": # pull up gnaw with unixconn
            self.gnaw = f"unix:///tmp/gnaw-{secrets.token_urlsafe()}" if self.gnawtype=="go" else "tcp://localhost:4224"
            wurl = self.listen
            async def _run():
                self._cs = trio.CancelScope()
                with self._cs:
                    await trio.run_process({
                        "py": [sys.executable, "-m", "grain.gnaw", "--hurl", self.gnaw, "--wurl", wurl, "-n", "1"],
                        "go": ["gnaw", "-hurl", self.gnaw, "-wurl", wurl, "-n", "1"],
                    }[self.gnawtype])
                if self.gnaw.startswith("unix://"): os.unlink(self.gnaw[7:])
            self._n.start_soon(_run)
            await trio.sleep(0.5 if self.gnawtype=="go" else 3) # wait for gnaw startup
        with timeblock("all jobs"):
            async with SocketChannel(self.gnaw, dial=True, _n=self._n) as self._c, \
                       self.push_result:
                await send_packet(self._c._so, dict(name=self.name)) # handshake
                self._n.start_soon(self._sender)
                async for x in self._c:
                    assert x['ok'] # gnaw handles all retries
                    self.push_result.send_nowait((x['tid'], pickle_loads(x['result'])))
                    self._wg.done()
                # FIXME: we cannot tell if gnaw quit unexpectedly
    async def __aenter__(self):
        self._n.start_soon(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        self._n.start_soon(self.sealer)
