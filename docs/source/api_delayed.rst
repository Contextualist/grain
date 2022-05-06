API Reference: delayed
======================

.. module:: grain.delayed

.. autofunction:: delayed
   :decorator:

.. autoclass:: DelayedFn()

.. autoclass:: Delayed()

.. note:: Some words on structured concurrency: As you may have notice, it is
  possible to pass delayed objects around (e.g. to other functions), but in most
  of the case it makes more sense to evaluate/"await" it in the same function it
  is created. Concurrent programming typically involves "spawn" (e.g. calling a
  delayed function) and "join" (e.g. await) actions. If two things happen in
  different scopes, it is hard to track the status of the the coroutines. Thus come
  the idea of structured concurrency, which enforces the "spawn" and "join" to be
  fully resolved within a block or scope. Stuctured concurrency is the design
  principle behind Grain's previous frontend ``combine`` and Grain's underlying
  async library ``Trio``. Trio's author has written `a more thorough discussion`_
  on structured concurrency.

.. _a more thorough discussion: https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful

.. note:: Since the submission / enqueuing of a delayed function is synchronous,
  while function dispatching behind the scene is asynchronous (because it involves
  network or subprocess IO), going through too much submission without a checkpoint
  might overload the queue. Most of the ``await`` are a checkpoint; you can always
  use ``trio.sleep(0)`` as a trivial checkpoint. For more information read Trio's
  documentation on `checkpoints`_. Imposing a rate limit is another way to include
  checkpoints; see :func:`grain.util.QueueLimiter`

.. _checkpoints: https://trio.readthedocs.io/en/stable/reference-core.html#checkpoints


.. autofunction:: each

.. autofunction:: delayedval

.. autofunction:: run
