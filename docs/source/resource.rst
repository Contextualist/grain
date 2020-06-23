Resource: a language for coordination
=====================================

.. module:: grain.resource

This abstract description of resource is like a protocol or currency, understood by
multiple parts of Grain ecosystem. These parts of system regulate their own behaviors
or interact with other components with resource. Here are some major examples of how
resource affects the system:

- The executor / scheduler determines when and where a tasklet can be executed.
- The executor and the worker gets aware that a running tasklet is exceeding time limit.
- A new joining worker reports its capabilities to the manager.
- A running tasklet learns about the resource it is allowed to use.

Each kind of resource is a class implementing the :ref:`resource interface<resource-api>`
One resource class actually plays two roles: requested resource and allocated resource.
Depending on the nature of the resource, they can have similar or different behaviors in
these two status (e.g. A request for ``Cores(3)`` might yield ``Cores([1,3,4])``; a
request for ``Memory(8)`` will definitely return ``Memory(8)``).

A user of Grain should know how to construct requested resources, while a tasklet
implementer need to know how to get information from allocated resources' attributes.

In your Python program, create resource instances for tasklets you are going to submit::

    # Combine
    wg.submit(Memory(8), afn, ...)

    # Delayed
    (dfn @ Memory(8))(...)

Resource request can contain multiple kinds of resources. Use ``&`` operator to combine
them (e.g. ``Node(1,8) & WTime(600)``). The allocated resource object will have the
attributes from each resource. Note that you cannot combine two resource of the same kind 
(e.g ``Memory(2) & Memory(8)`` is invalid).

For a running tasklet, allocated resource can be accessed through `context variable
<https://trio.readthedocs.io/en/stable/reference-core.html#task-local-storage>`__
``grain.GVAR``. ``grain.GVAR.res`` will be an allocated resource object. Its attributes
contain specific allocation information. See the :ref:`reference<built-in-res>` below.

Grain config specifies resources held by a worker. Wall time, CPU cores, and virtual
memory are information related to the supercomputing job management system, so they are
speficied with config entries ``script.walltime``, ``script.cores``, ``script.memory``.
These three values are used to request resources from the management system as well as
set up the worker. You can observe the implementation details with ``grain up --dry``.

TODO: other resource in config

Grain provides several built-in resource classes, which should be enough to describe many
computational tasks. Although in theory a user can provide any custom class that implements
the resource interface as resource, registering custom resource class is not implemented
yet.


.. _built-in-res:

Built-in resources
------------------

The variables starts with a period are attributes for the allocated resource.

.. autoclass:: Cores

CPU Cores. As requested resource, ``N`` should be an `int`, specifying the number of cores
to request. For allocated resource, ``.c`` is a `List[int]` of allocated cores; ``.N`` is
``len(.c)``.

.. autoclass:: Memory

Virtual memory. ``M``, ``.M`` (`int` or `float`) both stand for memory in GB.

.. autofunction:: Node

A convenient function for ``Cores(N) & Memory(M)``.

.. autoclass:: WTime

Walltime limit for a tasklet or a worker. ``T``: `int` (in seconds) or `str` in format
``[d]-hh:mm:ss``, representing a hard time limit. ``softT``: `int`, soft time limit. If
unset, default to the same value as the hard time limit. ``countdown``: False for requested
and allocated resources; true for resource providers (i.e. workers).

A tasklet can run on a worker when the tasklet's soft time limit is satisfied by the worker.
When run time of a tasklet exceeds the tasklet's hard time limit, the run fails with exception
``trio.TooSlowError``. This timeout is handled by Grain, so a tasklet does not need to set a
timeout itself. When a worker runs out of its time, it quits.

.. attribute:: ZERO

"No resource is required to run the tasklet" / "The worker is holding no resource". Current
Grain implementation runs tasklets requiring no resource on local worker.

.. autoclass:: Token

A tag for matching resource requesters to the providers. ``token``, ``.token``: `str`, the
tag name. A tasklet carrying a token can only run on a worker with the exactly matched token.


.. _resource-api:

Resource interface
------------------

TODO: guide to implement a new resource class

.. autoclass:: Resource()

   .. automethod:: _request

   .. automethod:: _alloc

   .. automethod:: _dealloc

   .. automethod:: _repr

   .. automethod:: _stat
