Tutorial
========

.. module:: grain

This is a tutorial introducing ``grain.delayed``, the latest framework frontend,
and all basic aspects of Grain you need to start incorporating Grain into your
workflow. This tutorial assumes basic understanding of asynchorous programming.
For a quick introduction to asynchorous programming, refer to the first few
sections of `Trio's tutorial <https://trio.readthedocs.io/en/stable/tutorial.html>`__.

Before you begin
----------------

1. Make sure you're using Python 3.6 or newer.

2. ``pip install --upgrade grain-scheduler``

3. Can you ``import grain``? If so then you're good to go!


Delayed function and object
---------------------------

.. note:: If you are familiar with Dask's delayed, Grain's delayed interface is
   just similar, but there are some major design differences. You may want to read
   more about that in the :doc:`api_delayed`.

Let's say you have a function doing expensive calculations and another function
doing relatively cheap reduce-like operations. We will like to make them
parallelizable, so we make them **delayed functions** (or we can call it a
"tasklet"). ::

    from grain.delayed import delayed, run
    from grain import GVAR
    from functools import partial

    @delayed
    async def add(x):
        # import inside the function because a tasklet should not have global reference
        import trio
        print(f"start adding to {x} with resource {GVAR.res}")
        await trio.sleep(x/10) # stimulate lenthy calculation
        print(f"done adding to {x}")
        return x + 1

    async def elevated_sum(l):
        s_ = 0
        for x in l:
            s_ += add(x)
        s = await s_
        print(f"elevated_sum({l}) = {s}")

    run(
        partial(elevated_sum, [1,2,3]),
        config_file=False,
    )

.. code-block:: none

   Config file is disabled, using default settings.
   start adding to 3 with resource Ø
   start adding to 2 with resource Ø
   start adding to 1 with resource Ø
   done adding to 1
   done adding to 2
   done adding to 3
   elevated_sum([1, 2, 3]) = 9
   worker elogin1(local) starts cleaning up
   worker elogin1(local) clear
   Time elapsed for all jobs: 0.3028046750696376

We can observe that the three ``add`` tasklets run in parallel (You should see time
elaspse for all tasklets roughly equal to that of the tasklet taking the longest
time, in this case ``add(3)``, 0.3s). The three tasklets have no inter-dependancy,
so we can parallelize them.

``elevated_sum`` looks simple, but it is actually an ingenious process. The calling
of delayed function ``add(x)`` here actually returns an **delayed object** instead
of the result of the function. Delayed objects are placeholders of the pending actual
result. They are composable using Python operators (as you see here, '+='). Those
operations are memorized by the delayed objects. Finally, ``await`` on the final
delayed object wait for all delayed objects involved to finish calculaion and compose
the answer according to the memorized operations.

.. note:: Difference from Dask: instead of putting the functions to queue when
   ``await``-ed at the end, calling of delayed function immediately schedules the
   function for execution.


Resource binding
----------------

Also notice that the ``add`` tasklet here takes no resource to finish. In reality,
computationally intesive jobs often occupy some resource (e.g. CPU, memory, GPU) of a
worker machine, so we would like to specify resource and demands for each worker and
job. In the following code, we add ``rpw=Cores([0,1])`` (resource per worker: CPU
cores 0,1. Now we only have one local worker) for ``run`` to specify the resources
owned by local worker. Before calling the delayed function ``add``, we bind a resource
demand to it using the ``@`` operator (``@`` means dot product in Python, but here we
just redefine it as a handy way to specify resources). ``Cores(1)`` means the function
needs one CPU core to run. ::

    from grain.resource import Cores

    async def elevated_sum(l):
        s_ = 0
        for x in l:
            s_ += (add @ Cores(1))(x)
        s = await s_
        print(f"elevated_sum({l}) = {s}")

    run(
        partial(elevated_sum, [1,2,3]),
        config_file=False,
        rpw=Cores([0,1]),
    )

.. code-block:: none

   Config file is disabled, using default settings.
   start adding to 1 with resource CPU_Cores([0])
   start adding to 2 with resource CPU_Cores([1])
   done adding to 1
   start adding to 3 with resource CPU_Cores([0])
   done adding to 2
   done adding to 3
   elevated_sum([1, 2, 3]) = 9
   worker elogin1(local) starts cleaning up
   worker elogin1(local) clear
   Time elapsed for all jobs: 0.40786700299941003

Note that tasklet 3 only starts after tasklet 1 finishes and yields one CPU core, because
we only have two cores in total. In the case of CPU core, request is non-specific (any 1
CPU core), while the assigned resources are (Core 0 or core 1).

Grain only inform the function at run time what resources are allocated for it. However,
Grain never enforces that constraint. It is the responsibility of the function itself to
follow the rule. External programs usually have various ways to manage their own CPU,
memory, etc. consumptions, so the users are expected to inform them in their ways. In this
example, we are only demonstrating how Grain manage the resources. As you can see, function
``add`` does not actually use the CPU core assigned to it.

Here we specify resource for the *local* worker, and execute function locally. In production,
we usually have multiple remote workers (e.g. on the computation nodes of a cluster) connect
to the central scheduler, head. They will inform head the resources they own. Grain's head
dispatch jobs to them as long as there are enough resources. We will talk more on workers in
the later section.


Local or remote execution
-------------------------

So far you have seen two ways submitting functions for paralle execution: without or with
resource constraint. These two ways actually map to the two kinds of functions when we are
orgranizing our workflow. Function callstack in a workflow usually resembles a tree. The
"leaf functions" perform expensive calculations; the "branch functions" calls other branches
and/or leaves and reduce their results to final answers. The "branch functions" are usually
cheap compared to the "leaf functions", so we request resources for the "leaf functions."
Delayed functions requesting no resource ("branches") will be executed locally. Therefore
they have access to the local scheduler and can dispatch other delayed functions. Delayed
functions with resource demand ("leaves") are sent to workers (local or remote) with enough
resources.

Now, suppose we want to run the presumably cheap "branch" function ``elevated_sum`` for several
times, locally and in parallel. How will you modify the code? You can pause and think about
it. A solution is presented below::

    from grain.delayed import each

    @delayed
    async def elevated_sum(l):
        s_ = 0
        for x in l:
            s_ += (add @ Cores(1))(x)
        s = await s_
        print(f"elevated_sum({l}) = {s}")

    async def main():
        data = [[1,2,3], [4,5,6], [7,8,9]]
        jobs = [elevated_sum(d) for d in data]
        [await j for j in jobs]
        # the two lines above can be simplified with helper `each`
        #await each(elevated_sum(d) for d in data)

    run(
        main,
        config_file=False,
        rpw=Cores([0,1]),
    )

.. code-block:: none

   Config file is disabled, using default settings.
   start adding to 7 with resource CPU_Cores([0])
   start adding to 8 with resource CPU_Cores([1])
   done adding to 7
   start adding to 9 with resource CPU_Cores([0])
   done adding to 8
   start adding to 4 with resource CPU_Cores([1])
   done adding to 4
   start adding to 5 with resource CPU_Cores([1])
   done adding to 9
   elevated_sum([7, 8, 9]) = 27
   start adding to 6 with resource CPU_Cores([0])
   done adding to 5
   start adding to 1 with resource CPU_Cores([1])
   done adding to 1
   start adding to 2 with resource CPU_Cores([1])
   done adding to 2
   start adding to 3 with resource CPU_Cores([1])
   done adding to 6
   elevated_sum([4, 5, 6]) = 18
   done adding to 3
   elevated_sum([1, 2, 3]) = 9
   worker elogin1(local) starts cleaning up
   worker elogin1(local) clear
   Time elapsed for all jobs: 2.309883333975449

The order of execution for the three ``elevated_sum`` might be different each time.

So far, we can have a rule of thumb for using Grain:

- Parallel execution: wrap the function with ``@delayed``.
- Expensive "leaf function": call it with resource attached.


Getting real: workers
---------------------

Workers, residing on computaional node of a cluster, communicate with Grain's
head/scheduler to make parallel computaion across clusters possible. Unlike Dask,
we have one worker per machine / computation node. The worker have access to all
resources on the machine. When a worker connects to Grain's head, it will inform head
the resources they own. Grain's head dispatch jobs to it as long as it has enough
resources for the jobs. The jobs are async functions (e.g. of external processes), so
a worker can monitor the status of multiple execution concurrently.

For Grain to recognize your system, you need to have a profile/config. Full reference
and samples of Grain's config syntax can be found in the
`example <https://github.iu.edu/IyengarLab/grain/tree/master/example>`__ directory. You
can start with one of the sample config and further customize it according to
``grain.reference.toml``. Here we will walk through some essensial settings to get
started quickly.

- ``system``: the HPC job management system (slurm or pbs, if pbs does not work, use
  pbs_wrap).

- ``head.listen``: the listening address of the head. You can start with a local port
  (e.g. ``tcp://:4242``).

- ``worker.dial``: the address worker uses to find head. You can figure our head's
  address by running ``hostname``. (e.g. if your head is on ``elogin1`` and uses port
  4242, then you can fill in ``tcp://elogin1:4242``)

- ``script.[queue,walltime,cores,memory]``: These are the fields to be filled in when
  you are writing a HPC job script. Depending on your cluster they should have different
  values. It is recommend to start with a debug queue and short walltime (You can launch
  workers during a running Grain mission, so it is OK if it is less than the total time
  required). The cores and memory will be for one computational node and one worker, so
  it is usually a good idea to fill in the maximum number of processors and memory for
  one computational node.

- ``setup_cleanup``: commands to setup the running environments (e.g. load modules,
  source profiles, make cache dirs, etc.) and commands to clean up after a worker quits
  (e.g. delete cache dirs, transfer usage analytics). Prepend ``defer`` to mark a command
  to be clean up command (e.g. ``defer rm -r /tmp/cache``).

There are more options in the reference config, but now you should be all set to run
things on clusters. You may want to name the file ``grain.toml`` and put it in the
currect directory for Grain to pick it up automatically, or set an envar
``GRAIN_CONFIG=path/to/your_config.toml``, or just use flag ``-c path/to/your_config.toml``
when calling ``grain``.

Now, before you proceed, let's do a final check:

.. code-block:: none

   > grain up --dry

This command generates the worker submission script with your config. Instead of submiting
it right away, the dry run print out the script for your inspection. You can see how each
field in your config is represented here and check if anything does not look right.


When you are ready, run the following code. The tasklet here simply checks for the hostname,
and you can see where the job is running. ::

    from grain.delayed import delayed, each, run
    from grain.resource import Node
    from grain import GVAR

    @delayed(nout=2) # the function has 2 return values
    async def hostname():
        import trio
        cp = await trio.run_process(['hostname'], capture_stdout=True)
        return str(GVAR.res), cp.stdout.decode()

    async def main():
        summary = ""
        for i in range(4):
            res, hn = (hostname @ Node(N=16,M=10))() # Node is Cores & Memory
            summary += f"Job {i} with " + res + " is executed on a machine with hostname " + hn
        print("Waiting for calculation to start ...")
        print(await summary)

    run(
        main,
        nolocal=True,
    )

If you run the code above, you should see your program pause right after printing "Waiting
for calculation to start ...". Because we disable the local worker with option ``nolocal=True``,
there will be no calculation resource available until remote workers join.

.. note:: In actual calculations, if you are running Grain head on a login node, it is
   recommanded to set local worker's resource to ZERO (i.e. ``nolocal=True`` for
   ``grain.delayed.run``) so that no intensive calculation will be executed locally.

So let's launch some workers. On another shell, run the following to submit 2 workers:

.. code-block:: none

   > grain up -n 2

As soon as the HPC jobs begin to run and join the head, the jobs start to run. When all of
our jobs finish, all workers quit, too. You can repeat this with different resources assign
to the jobs, add delays in the jobs using ``trio.sleep``, and try to see if you can make
the jobs running on different computation nodes.


What's next?
------------

Now you are all set to run parallel calculation with Grain, orchestrating tasklets written by others,
or even implementing tasklets yourself. Here's what to explore:

- Tasklets in real world: run computational chemistry packages with `ASE-Grain <https://github.com/Contextualist/ase-grain>`__.
- Checkout :doc:`api_delayed`.
- Have a look at what built-in resources are available.
- Setup a Grain bridge that makes worker connection smarter and makes it possible to send
  your jobs across multiple clusters.
