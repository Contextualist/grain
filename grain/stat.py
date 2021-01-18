from .resource import Reject

import time
from datetime import datetime
from bisect import bisect_right
from contextlib import asynccontextmanager
import logging
logger = logging.getLogger(__name__)

import trio

MAXSPAN = 30 # in min

punch_event = {}

def log_event(ev):
    now = time.time()
    l = punch_event.setdefault(ev, [])
    l.append(now)
    if len(l) > 1000: roll(l, now)

time_event = {}

def log_timestart(ev, uid):
    tstmp, span, pending = time_event.setdefault(ev, ([], [], {}))
    pending[uid] = time.time()
def log_timeend(ev, uid):
    now = time.time()
    tstmp, span, pending = time_event[ev]
    tstmp.append(now)
    span.append(now-pending[uid])
    del pending[uid]
    if len(tstmp) > 1000:
        roll(tstmp, now)
        del span[:len(span)-len(tstmp)]

def tally(span):
    if span > MAXSPAN:
        raise ValueError(f"span {span} is larger than MAXSPAN {MAXSPAN}")
    now = time.time()
    r = {}
    for k,l in punch_event.items():
        roll(l, now)
        count = len(l) - bisect_right(l, now-span*60)
        if count: r[k] = count
    for k,(ts,sp,_) in time_event.items():
        i0 = bisect_right(ts, now-span*60)
        frq = len(ts) - i0
        if frq: r[k] = f"{sum(sp[i0:])/frq:.3f}s*{frq}"
    return r

@asynccontextmanager
async def stat_logger(span):
    async def _loop():
        while True:
            await trio.sleep(span*60)
            logger.info(tally(span))
    async with trio.open_nursery() as _n:
        _n.start_soon(_loop)
        try:
            yield
        finally:
            _n.cancel_scope.cancel()

def roll(l, now=None):
    del l[:bisect_right(l, (now or time.time())-MAXSPAN*60)]


RES_TYPES = ("Cores", "Memory")
def ls_worker_res(workers):
    fs = ""
    len_name = max(len(w.name) for w in workers) + 4
    FMT = "{:>"+str(len_name)+"}" + "{:>10}"*len(RES_TYPES) + "  {}\n"
    def row(*cel):
        nonlocal fs
        fs += FMT.format(*cel)
    def ratio_map(pqs):
        return (f"{p}/{q}" for p,q in pqs)
    total = [[0,0] for _ in range(len(RES_TYPES))]
    row("", *RES_TYPES, "")
    for w in workers:
        wstat = w.res.stat()
        one = []
        for i,rt in enumerate(RES_TYPES):
            p,q = wstat.get(rt, (0,0))
            total[i][0] += p; total[i][1] += q
            one.append([p,q])
        row(w.name, *ratio_map(one), "paused" if type(w.res) is Reject else "")
    row("TOTAL", *ratio_map(total), "")
    return fs


PROBE_FN = {}
def reg_probe(ev, fn):
    PROBE_FN[ev] = fn

def collect_probe():
    ent = []
    for ev, fn in PROBE_FN.items():
        ent.append(f"{ev}: {fn()}")
    return '\n'.join(ent)
