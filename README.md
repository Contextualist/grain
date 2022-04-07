# Grain

[![Docs](https://img.shields.io/badge/docs-read%20now-blue.svg)](https://grain.readthedocs.io)
[![PyPI version](https://img.shields.io/pypi/v/grain-scheduler.svg)](https://pypi.org/project/grain-scheduler)

A scheduler for resource-aware parallel external computing on clusters.

### Install

```Bash
pip install grain-scheduler
```

### Overview

[Dask-like](https://docs.dask.org/en/latest/delayed.html) async-native delayed objects for you to run jobs in an arbitary mix of parallel and sequential manner.

```python
from grain.delayed import delayed
from grain.resource import Cores

@delayed
async def identity(x):
    # Access what CPU(s) have been allocated for us
    n_cpu, cpus = GVAR.res.N, ','.join(map(str,GVAR.res.c))
    # Pretend that we are doing something seriously ...
    await trio.run_process(f'mpirun -np {n_cpu} --bind-to cpulist:ordered --cpu-set {cpu} sleep 1')
    return x

@delayed
async def weighted_sum():
    # Run the expensive function **remotely** (on a worker) by demanding resource 1 CPU core
    # Note that `r_` is a Future, or a placeholder of the return value
    r_ = (identity @ Cores(1))(0)

    # Futures are composable
    # Composition implies dependency / parallelization opportunity
    r_ += (identity @ Cores(1))(1) * 1 + (identity @ Cores(1))(2) * 2
    # Block until all dependencies finish, then return the composed value
    return await r_

    # Or do the same in a fancier way
    #return await sum(
    #    (identity @ Cores(1))(i) * i for i in range(3)
    #)

# Run the cheap, orchestrating function **locally**
print(await (weighted_sum() + weighted_sum()))
# Output: 10
```

Check out [tutorial](https://grain.readthedocs.io/en/latest/tutorial_delayed.html) for complete demos and how to set up workers.

### Resource-awareness

Every job in the job queue has a resource request infomation along with the job to run. Before the executor run each job, it inspects each worker for resource availability. If resource is insufficient, the job queue is suspended until completed jobs return resources. Resources can be CPU cores, virtual memory, both, (or anything user defined following interface `grain.resource.Resource`).

Every time a job function runs, it has access to `GVAR.res`, a [context-local variable](https://trio.readthedocs.io/en/stable/reference-core.html#task-local-storage) giving the information of specific resource dedicated to the job. (e.g. if a job is submitted with `Cores(3)`, asking for 3 CPU cores, it might receive allocation like `Cores([6,7,9])`.)

### Ergonomic user interface

Async-native API introduces minimal changes to the serial code, while enabling access to the entire Python async ecosystem accommodating complex workflows.

Minimal configuration is needed for migrating to a new supercomputing cluster (See sample configs in the [`example/`](example) dir). When running, the `grain` commandline helper provides easy access to dashboard and worker scaling.
