Advanced usage
==============

Worker autoscaling
------------------

If you are running computations that range for days or even weeks, the workers can be outlived by the head process.
In that case you need to constantly supplying new workers by ``grain up``.
To automate this process, autoscaling is built in.
Autoscaling can either be enabled in the Grain config by setting ``head.gnaw.swarm = {N}``,
or by running ``grain scale {N}`` where ``{N}`` is the target number of workers.
``grain scale {N}`` can also be used to change the scaling on the fly.
Internally, a quota is maintained.
The quota is decremented by worker submission and recovers over time.
The quota constraint ensures that autoscaling will not blindly add workers in catastrophic failure cases
(e.g. issues from the task itself, filesystem failure).

.. _contextmod:

Context module: plugin system for worker
----------------------------------------

Grain config entry ``grain.script.setup_cleanup`` allows setup / cleanup procedures to be performed before and after the worker process.
Occassionally, there are setup / cleanup procedures within the worker Python process.
Context module provides a way for user to run arbitrary code once at the beginning and the end of the worker's life cycle.
Context module is simply an asynchronous context manager that wraps around all tasks executed by the worker.
A simplified worker life cycle is depicted as below ::

    async with (
        grain_context(),
        trio.open_nursery() as _n,
    ):
	async for afn in receive_tasks():
            _n.start_soon(run_and_send_result, afn)

where the asynchronous context manager ``grain_context`` can be defined by the user in a file,
and set through Grain config entry ``contextmod = "path/to/contextmod_file.py"``.

:func:`grain.subproc.subprocess_pool_scope` is an example that makes use of context module.
