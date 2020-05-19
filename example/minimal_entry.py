"""A simple example to demonstrate grain's ability to 
orchestra a mix of parallel and seqential workflow.
The workflow is as below:
                  +-------------+
                  | run_combine |
                  +-------------+
          +--------------v-------------+
          |                            |
    +-----v------+              +------v-----+
    | frame(i=0) |              | frame(i=1) |
    +-----+------+              +------+-----+
          |                            |
    +--+-j=0-+--+                +--+-j=0-+--+
    |           |                |           |
+---v---+   +---v---+        +---v---+   +---v---+
| 0,0,a |   | 0,0,b |        | 1,0,a |   | 1,0,b |
+-------+   +-------+        +-------+   +-------+
    +-----+-----+                +-----+-----+
          |                            |
    +--+-j=1-+--+                +--+-j=1-+--+
    |           |                |           |
+---v---+   +---v---+        +---v---+   +---v---+
| 0,1,a |   | 0,1,b |        | 1,1,a |   | 1,1,b |
+-------+   +-------+        +-------+   +-------+

i.e. i: parallel, j: sequential, a/b: parallel
"""

import trio
from grain import run_combine, open_waitgroup, GVAR
from grain.resource import Node

from functools import partial

# `job`, sent to `wg.submit`, is an atomic job. The
# jobs are scheduled and sent to workers, local or
# remote, and their results are finally aggregated 
# and sent back to their waitgroup.
# `GVAR` contains the specific context information
# for the current job. `GVAR.res` is the resources
# allocated to the current job, but in this demo,
# we are not actually using them.
async def job(x):
    import random
    print(f"job {x} with {GVAR.res} starts")
    t = random.randint(1,3)
    await trio.sleep(t)
    print(f"job {x} ends after {t}s")
    return t

# Function `frame` here is for orchestration. Scheduler
# (but not workers) runs it to get job information.
# `frame` "talks" to scheduler through `open_waitgroup`.
# Use it for setting up a scope where jobs submitted
# inside are run parallelly until all results are collected.
# `open_waitgroup` can be called multiple times, and/
# or called recursively.
async def frame(i):
    for j in range(2):
        async with open_waitgroup() as wg:
            wg.submit(Node(N=1,M=8), job, f'{i}-{j}-a')
            wg.submit(Node(N=1,M=8), job, f'{i}-{j}-b')
        print(f"{i}-{j}: {wg.results}")


jobs = [partial(frame, i) for i in range(2)]
# ... is equivalent to ...
#async def main():
#    async with open_waitgroup() as wg:
#        for i in range(2):
#            wg.start_subtask(frame, i)
#jobs = main

# rpw: resource per worker; this is for the only local worker
run_combine(jobs, rpw=Node(N=4,M=24))
