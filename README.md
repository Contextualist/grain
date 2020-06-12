# Grain

[![Docs](https://img.shields.io/badge/docs-read%20now-blue.svg)](https://grain.readthedocs.io)
[![PyPI version](https://img.shields.io/pypi/v/grain-scheduler.svg)](https://pypi.org/project/grain-scheduler)

A scheduler for resource-aware parallel external computing on clusters.

### Install

```Bash
pip install grain-scheduler
```

### TL;DR

[Dask-like](https://docs.dask.org/en/latest/delayed.html) async-native delayed objects for you to run jobs in an arbitary mix of parallel and sequential manner.

```python
# "I want to run fn in parallel (local or remote), and let it return a placeholder for the result."
@delayed
async def fn(x):
    ...


# "I want to run it **locally** because it is a cheap function that launch other expensive calculations."
r_ = fn(a) # Note that `r_` is not the return value; it's a placeholder of the return value

# Or "I want to run it **remotely** (on a worker) with resource 4 CPU cores because it is an expensive, leaf function."
r_ = (fn @ Cores(4))(a)


# "I want the result, now!"
r = await r_ # ... and sure you can write them in one step: r = await (fn @ Cores(4))(a)

# Or "I need to do several things in parallel, and get the summed result afterwards."
r_ = (fn @ Cores(2))(a) + (fn @ Cores(6))(b)
r = await r_
```

Check out [tutorial](https://grain.readthedocs.io/en/latest/tutorial_delayed.html) for complete demos and how to set up workers.

### Resource-awareness

Every job in the job queue has a resource request infomation along with the job to run. Before the executor run each job, it queries each worker for resource availability. If resource is insufficient, the job queue is suspended until completed jobs return resources. Resources can be CPU cores, virtual memory, both, (or anything user defined following interface `grain.resource.Resource`).

Every time a job function runs, it has access to `grain.GVAR.res`, a [context-local variable](https://trio.readthedocs.io/en/stable/reference-core.html#task-local-storage) giving the information of specific resource dedicated to the job. (e.g. if a job is submitted with `Cores(3)`, asking for 3 CPU cores, it might receive allocation like `Cores([6,7,9])`.)

### Executor, Workers and communication

The top-level APIs (i.e. "delayed" and "combine") are built upon an [executor](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Executor)-like backend called `grain.GrainExecutor`. It schedules and dispatches jobs to workers, and it maintains a single job queue and a result queue.

Workers, one per node, simply receive async functions (i.e. jobs) from the executor and run them. Executor and workers use socket for communication, and [`dill`](https://dill.readthedocs.io/en/latest/) serializes the functions to byte payloads.
