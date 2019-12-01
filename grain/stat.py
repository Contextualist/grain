import time
from datetime import datetime
from bisect import bisect_right

import trio
from async_generator import asynccontextmanager

MAXSPAN = 30 # in min

all_event = {}

def log_event(ev):
    now = time.time()
    global all_event
    l = all_event.setdefault(ev, [])
    l.append(now)
    if len(l) > 1000: roll(l, now)

def tally(span):
    if span > MAXSPAN:
        raise ValueError(f"span {span} is larger than MAXSPAN {MAXSPAN}")
    now = time.time()
    r = {}
    for k,l in all_event.items():
        roll(l, now)
        r[k] = len(l) - bisect_right(l, now-span*60)
    return r

@asynccontextmanager
async def stat_logger(span):
    async def _loop():
        while True:
            await trio.sleep(span*60)
            print(f"[{datetime.now().strftime('%y/%m/%d %H:%M:%S')}]\t{tally(span)}", flush=True)
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
    FMT = "{:>25}" + "{:>10}"*len(RES_TYPES) + "\n"
    def row(*cel):
        nonlocal fs
        fs += FMT.format(*cel)
    def ratio_map(pqs):
        return (f"{p}/{q}" for p,q in pqs)
    total = [[0,0] for _ in range(len(RES_TYPES))]
    row("", *RES_TYPES)
    for w in workers:
        wstat = w.res.stat()
        one = []
        for i,rt in enumerate(RES_TYPES):
            p,q = wstat.get(rt, (0,0))
            total[i][0] += p; total[i][1] += q
            one.append([p,q])
        row(w.name, *ratio_map(one))
    row("TOTAL", *ratio_map(total))
    return fs


PROBE_FN = {}
def reg_probe(ev, fn):
    PROBE_FN[ev] = fn

def collect_probe():
    ent = []
    for ev, fn in PROBE_FN.items():
        ent.append(f"{ev}: {fn()}")
    return '\n'.join(ent)
