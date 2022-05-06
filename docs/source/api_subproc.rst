Incorporate computationally intensive Python functions (if you must)
====================================================================

.. module:: grain.subproc

Grain, as well as asynchronous programming in general, excels at managing external workloads (i.e. subprocesses).
However, there are times when part of the workflows consists of computationally intensive pure Python code or C-extension modules.
(If most of the workload are computationally intensive Python functions, Grain might not be your best choice.)
Module ``grain.subproc`` accommodates those cases by wrapping the function and offloading it to a separate Python subprocess.

Due to the restrictions of the Python GIL, the usual practice for dealing with computationally intensive Python code is multiprocessing.
``grain.subproc`` implements a similar approach behind the scenes by maintaining a process pool.
The processes spawned on demand are similar to local workers, but more lightweight.
Those processes are reused until they are shut down after a certain amount of idle time.
The size of the process pool is limited by the number of CPU cores available on the system;
we use the :doc:`Resource <resource>` notation to limit the concurrency, and each process occupies at least one CPU core.

Here is a demo of how ``grain.subproc`` can be used with ``grain.delayed``::

    from grain.subproc import subprocify, subprocess_pool_scope
    from grain.resource import Cores
    from grain.delayed import delayed, run

    @delayed
    @subprocify
    def f(x):
        """a synchronous, computationally intensive function"""
        print(f"Running in a subprocess with {GVAR.res}")
        return x**2

    async def main():
        async with subprocess_pool_scope():
            assert await (f @ Cores(1))(1) == 1
            assert await (f @ Cores(1))(2) == 4

    # Run with CPU cores 0, 1
    run(main, config_file=False, rpw=Cores([0, 1]))

Note in the example above, subprocified functions are executed within the subprocess pool context.
The subprocess pool is initialized once with :func:`subprocess_pool_scope`.
If any subprocified function is to be run in a Grain worker,
the context can be initialized with :ref:`context module <contextmod>` with code like this::
   
    from contextlib import asynccontextmanager
    from grain.subproc import subprocess_pool_scope

    @asynccontextmanager
    async def grain_context():
        async with subprocess_pool_scope():
            yield

Decorator :func:`@subprocify<subprocify>` simply wraps a synchronous function into an async function that offloads the workload to a subprocess.
Behind the scenes, it serializes and sends the function and its arguments to an available subprocess in the pool,
waits for the result, and at the end deserializes the result and returns it.

The followings are API reference for this submodule.

.. autofunction:: subprocify
   :decorator:

.. autofunction:: subprocess_pool_scope

.. autoclass:: BrokenSubprocessError
