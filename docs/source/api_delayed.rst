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
  is createed. Concurrent programming typically involves "spawn" (e.g. calling a
  delayed function) and "join" (e.g. await) actions. If two things happen in
  different scope, it is hard to track the status of the the coroutine. Thus come
  the idea of structured concurrency, which enforces the "spawn" and "join" to be
  fully resolved within a block or scope. Stuctured concurrency is the design
  principle behind Grain's previous frontend ``combine`` and Grain's underlying
  async library ``Trio``. Trio's author has written `a more thorough discussion`_
  on structured concurrency.

.. _a more thorough discussion: https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful


.. autofunction:: each
