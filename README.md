# Grain

A scheduler built with `trio` for resource-aware parallel computing on clusters.

### TL;DR

Three core functions for you to run async jobs in an arbitary mix of parallel and sequential manner.

```python
# Jobs/subtasks inside a waitgroup run parallelly
async with grain.open_waitgroup() as wg:

    # Put a job onto the waitgroup to be executed
    wg.submit(resource, fn, *args, **kwargs)

    # Put a subtask onto the waitgroup. Submit jobs / 
    # start other subtasks inside the subtask.
    wg.start_subtask(vfn, *args, **kwargs)

# Waitgroup blocks here until all of its jobs are done,
# so outside a waitgroup is essentially sequencial.

results = wg.results # sorted in the order of submission


# Execute one job sequentially
result = await grain.exec1(resource, fn, *args, **kwargs)
```

Entrypoint:

```python
async def main(): # top-level subtask
    # Submit jobs / start subtasks here
grain.run_combine(main, [worker1_addr, worker2_addr, ...], resource_per_worker)
# ... Or for top-level parallelism, ...
#grain.run_combine([main1, main2, ...], ...)
```

Check out [example](example) for complete demos / more patterns and configuration sample.

### Resource-awareness

Every job in the job queue has a resource request infomation along with the job to run. Before the executor run each job, it queries each worker for resource availability. If resource is insufficient, the job queue is suspended until completed jobs return resources. Resources can be CPU cores, virtual memory, both, (or anything user defined following interface `grain.resource.Resource`).

Every time a job function runs, it has access to `grain.GVAR.res`, a [context-local variable](https://trio.readthedocs.io/en/stable/reference-core.html#task-local-storage) giving the information of specific resource dedicated to the job. (e.g. if a job is submitted with `CPU(3)`, asking for 3 cores, it might receive allocation like `CPU([6,7,9])`.)

### Executor, Workers and communication

The top-level APIs (i.e. "combine") are built upon an [executor](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Executor)-like backend called `grain.GrainExecutor`. It schedules and dispatches jobs to workers, and it maintains a single job queue and a result queue. The executor usually runs on the head node in a cluster.

Workers, one per node, simply receive async functions (i.e. jobs) from the executor and run them. Executor and workers use socket for communication, and [`dill`](https://dill.readthedocs.io/en/latest/) serializes the functions to byte payloads.

### Acknowledgement

The API of Grain is largely insipred by [structured concurrency](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful), a major design principle behind [Trio](https://trio.readthedocs.io), and it is specifically inspired by the API of Trio. And of course, Grain uses Trio internally.

### Caveat

Relative import (import not on Python package path) should be within the job function. Global reference fails in this case.
