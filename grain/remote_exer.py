import trio
import psutil

from .conn_msgp import send_packet
from .pair import SocketChannel
from .head import GrainSpecializedRemote
from .util import WaitGroup, pickle_dumps, pickle_loads, timeblock

import secrets
from functools import partial
from math import inf as INFIN
import getpass
import argparse
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

DAEMON = object()

class RemoteExecutor:
    """Pass the jobs on to an external scheduler

    Args:
      gnaw (Optional[str]): If set, connect to the Gnaw executor with address
        ``gnaw``, ignoring ``head.gnaw`` in the config. By default, the Gnaw
        executor is a managed daemon process.
    """
    def __init__(self, _n=None, config=None, gnaw=DAEMON, name="", prioritized=False, sworker_config=(), **kwargs):
        if kwargs:
            logger.warning(f"kwargs {kwargs} are ignored")
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
        self.side_c = None
        self.fnd = {}


    def submit(self, res, fn, *args, **kwargs):
        tid = self.jobn = self.jobn+1
        self.push_job.send_nowait((tid, res, partial(fn, *args, **kwargs)))
        return tid

    async def sealer(self):   # out of the executor scope => end of submission
        await self._wg.wait() # no pending task => end of resubmission
        await self.push_job.aclose()
        await self._c.aclose()
        await self.side_c.aclose()
    async def _sender(self):
        async with self.pull_job: # XXX: currently no ratelimit on sending
            async for tid, res, fargs in self.pull_job:
                self._wg.add()
                if not hasattr(res, "N"): # heuristic to determine if this is a sworker task
                    self.fnd[tid], func = fargs, None
                else:
                    func = pickle_dumps(fargs)
                await send_packet(self._c._so, dict(tid=tid, res=res, func=func)) # We don't need locking
    async def run(self, task_status=trio.TASK_STATUS_IGNORED):
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
                gnawproc = await trio.lowlevel.open_process(
                    ["gnaw", "-hurl", self.gnaw, "-wurl", self.listen, "-n", str(conf.max_conn),
                             "-log", conf.log_file, "-t", conf.idle_quit, "-swarm", str(conf.swarm), *conf.extra_args],
                    start_new_session=True, # daemon
                )
                for retry in range(7): # wait for gnaw startup
                    await trio.sleep(0.1 * 2**retry)
                    if Path(self.gnaw[len('unix://'):]).exists():
                        break
                    if gnawproc.returncode is not None:
                        raise RuntimeError(f"failed to start Gnaw, exit code {gnawproc.returncode}")
                else:
                    raise RuntimeError("Gnaw took too long to start")
        with timeblock("all jobs"):
            async with SocketChannel(self.gnaw, dial=True, _n=self._n) as self._c, \
                       self.push_result:
                # handshake
                await send_packet(self._c._so, dict(cmd="chTaskResult", name=self.name))
                hsmsg = await self._c.receive()
                await self._n.start(self.run_sworker_clients, hsmsg)
                self._n.start_soon(self._sender)
                task_status.started()
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
        await self._n.start(self.run)
        return self
    async def __aexit__(self, *exc):
        if any(exc):
            return False
        self._n.start_soon(self.sealer)

    # TODO: backendless sworker
    async def run_sworker_clients(self, hsmsg, task_status=trio.TASK_STATUS_IGNORED):
        assert hsmsg["cmd"] == "hsSynAck"
        pool = dict()

        async def _reg(name, kwargs):
            logger.info(f"client for specialized worker {name} started")
            # We don't need to manage resource or connection here
            sr = GrainSpecializedRemote(name, None, None, kwargs)
            await sr.connect(_n)
            pool[name] = sr
        async def _unreg(name):
            if (sr := pool.pop(name, None)) is not None:
                await sr.aclose()

        async def _run_task(tid, res, client_name):
            ok, r = await pool[client_name].execf(tid, res, self.fnd[tid])
            await self.side_c.send(dict(tid=tid, exception="Exception" if not ok else "", result=client_name))
            if ok:
                self.push_result.send_nowait((tid, r))
                self._wg.done()
                del self.fnd[tid]
            else:
                # TODO: buffered exp
                exp, tb = r
                logger.error(f"Exception from task: {exp}\n{tb}")

        async with trio.open_nursery() as _n:
            for name, kwargs in hsmsg["obj"].items():
                await _reg(name, kwargs)
            async with SocketChannel(self.gnaw, dial=True, _n=_n) as self.side_c:
                await send_packet(self.side_c._so, dict(cmd="chApprovalRStatus", name=str(hsmsg["name"])))
                assert (await self.side_c.receive())["cmd"] == "hsAck"
                task_status.started()
                async for x in self.side_c:
                    cmd = x.get("cmd", "")
                    if cmd == "":
                        tid, res, client_name = x["tid"], x["res"], x["func"]
                        _n.start_soon(_run_task, tid, res, client_name)
                    elif cmd == "pushSWorker":
                        await _reg(x["name"], x["obj"])
                    elif cmd == "quitSWorker":
                        await _unreg(x["name"])
                    else:
                        logger.warning(f"specialized worker client manager received unknown command {cmd}")
            for sr in pool.values():
                await sr.aclose()
