"""Dask-like Delayed object, resource-centric and async/await-native
"""
from .resource import ZERO
from .contextvar import GVAR
from .util import Future

import trio

import operator
from functools import partial
from inspect import iscoroutinefunction
from copy import copy
from collections.abc import Iterable

MAX_OPS = 100


async def each(*dos):
    r"""A convinient helper function to await on a list of delayed
    objects.

    Args:
      \*dos (\*Delayed or [Iterable[Delayed],]): list of delayed
        objects

    Returns:
      list of corresponding results
    """
    if len(dos) == 1 and isinstance(dos[0], Iterable):
        dos = list(dos[0])
    return [await do for do in dos]

def delayedval(v, length=None, copy_on_setitem=True):
    """A convinient helper function that wraps any value into a
    delayed object that immediately return that value at evaluation.
    This is useful for testing and for the following edge case in NumPy::

        r_ = afn() # `afn` is a delayed function returning a len-2 array

        a = np.arange(3)
        #a[[0,1]] += r_ # ValueError; __setitem__ cannot turn `a` into a delayed object

        a = delayedval(np.arange(3))
        a[[0,1]] += r_ # Ok

    Args:
      v (Any): value to be wrapped
      length (int): see ``nout`` of :func:`delayed`
      copy_on_setitem (bool): see ``copy_on_setitem`` of :func:`delayed`

    Returns:
      a :class:`Delayed` object evaluted to ``v``
    """
    return Delayed(Future(v), length=length, copy_on_setitem=copy_on_setitem)


def delayed(fn=None, nout=None, copy_on_setitem=True, cache_hfn=None):
    """Wraps an async function into a delayed function (:class:`DelayedFn`).
    It can be used as a decorator, or around the function directly (i.e.
    ``fn = delayed(fn)``).

    Args:
      nout (int): If set, the return value of the function is assumed
        to be a iterable with length ``nout``, so that indexing and
        unpacking on the delayed object is allowed.
      copy_on_setitem (bool): The default (True) is a safe option to
        make sure previously unpacked values from a delayed objects
        are not affected by a later setitem op on that object. This
        is achieved by making a copy of the object at result evaluation,
        so this can be turned off for performance. Unlike other operations
        that can return a separate delayed object, ``setitem`` (e.g.
        ``a[1] = 1``) is an inplace mutating operatation. The following
        snippet illustrates a situation where a copy is needed::

            r_ = afn() # assume to be a delayed function returns `[3,4]`
            a_, b_ = r_
            r_[1] = 9
            assert (await r_ == [3,9])
            assert (await a_ == 3) and (await b_ == 4) # copy_on_setitem=True
            #assert (await a_ == 3) and (await b_ == 9) # copy_on_setitem=False
    """
    if fn is None:
        return partial(delayed, nout=nout, copy_on_setitem=copy_on_setitem)
    if not iscoroutinefunction(getattr(fn, "func", fn)):
        raise TypeError("delayed only wraps async functions")
    return DelayedFn(fn, nout, copy_on_setitem)

class DelayedFn:
    """A DelayedFn submits the function it wraps and returns a
    :class:`Delayed` object when called. Resources could be bound to
    the function with ``@`` operator.

    Do not construct this directly, use the :func:`@delayed<delayed>`
    decorator instead.
    """
    __slots__ = ("fn", "nout", "copy", "res")
    def __init__(self, fn, nout, copy_on_setitem):
        self.fn = fn
        self.nout = nout
        self.copy = copy_on_setitem
        self.res = ZERO
    def __matmul__(self, res):
        self.res = res
        return self
    def __call__(self, *args, **kwargs):
        # global: exer, _gn, rch
        if 'exer' not in globals():
            raise RuntimeError("Calling a delayed function is only valid inside `grain.delayed.run`")
        ft = Future()
        if self.res is not ZERO:
            tid = exer.submit(self.res, self.fn, *args, **kwargs)
            rch[tid] = ft
        else: # Currently non-leaf tasks are not guarded by the exer. We do not retry on exception.
            # We use an ordered nursery for first-come-first-serve guarentee
            _gn.start_now(partial(_run_and_set_result, ft, self.fn, *args, **kwargs))
        self.res = ZERO
        return Delayed(ft, length=self.nout, copy_on_setitem=self.copy)

async def _run_and_set_result(ft, fn, *args, **kwargs):
    r = await fn(*args, **kwargs)
    ft.set(r)


class Delayed:
    """A Delayed object represents a value to be computed by Grain.

    Do not construct this directly, this is intended to be the return
    value of a :class:`DelayedFn`. Alternatively, use :func:`delayedval`
    for wrapping a value into a Delayed object.

    A ``Delayed`` supports most python operations, each of which creates
    another ``Delayed`` representing the result:

        * Most operators (``*``, ``-``, ``+=`` (treated as ``+``), ...)
        * Item iteration, indexing, and slicing (``a[0]``)
        * Item mutation __setitem__ (``a[0] = 1``)
        * Attribute access (``a.size``)
        * Method calls (``a.index(0)``)
        * Most NumPy functions (``np.mean(a)``)

    Operations that aren’t supported include:

        * Attr mutation __setattr__ (``a.foo = 1``)
        * Use as a predicate (``if a: ...``)

    This is mostly a copy of the implementaton in Dask, but there are
    several main differences from Dask:

        1. Grain's Delayed assumes all ops are cheap and perform them
           locally.
        2. As all delayed objects are reduced locally, and Grain worker
           does not cache results, it is not allowed to pass delayed
           objects to a delayed function; we want to be explicit on
           the intention of dependent/serial jobs. e.g.::

               r1 = await dfn1()
               r2 = await dfn2(r1)

        3. Calling a delayed function submit the calculation immediately.
        4. A Delayed object is somehow mutable, ``setitem`` is allowed
           but ``setattr`` is not (implemented).
    """
    __slots__ = ("_future", "_post_ops", "_length", "_copy", "_eval_started")
    def __init__(self, future, post_ops=None, length=None, copy_on_setitem=True):
        self._future = future
        self._post_ops = post_ops or []
        self._length = length
        self._copy = copy_on_setitem
        self._eval_started = False
        if len(self._post_ops) > MAX_OPS:
            self._partition_ops()
    def __getstate__(self):
        return tuple(getattr(self, i) for i in self.__slots__)
    def __setstate__(self, state):
        for k, v in zip(self.__slots__, state):
            setattr(self, k, v)

    async def result(self):
        if self._eval_started: # the first call does the eval; the rest wait for its result
            return await self._future.get()
        self._eval_started = True
        _base_future, self._future = self._future, Future()
        r = await _base_future.get()
        for op, other, kwargs in self._post_ops:
            #print("post_op", op, "on", other)
            for i, o in enumerate(other):
                if not isinstance(o, Delayed): continue
                other[i] = await o.result() # eval o if not done
            for k, o in kwargs.items():
                if not isinstance(o, Delayed): continue
                kwargs[k] = await o.result() # eval o if not done
            if op is not operator.setitem: # NOTE: exclude the inplace op
                r = op(r, *other, **kwargs)
            else:
                if self._copy:
                    r = copy(r) # shallow copy is ok because setitem does not change the value itself
                op(r, *other)
        self._future.set(r)
        self._post_ops.clear()
        return r
    def __await__(self):
        """Await on the Delayed object returns its result"""
        return self.result().__await__()
    get = result # implements the Future interface

    def _partition_ops(self):
        chunk_ops, self._post_ops = self._post_ops[:MAX_OPS], self._post_ops[MAX_OPS:]
        self._future = Delayed(self._future, chunk_ops, self._length, self._copy)
        _gn.start_soon(self._future.get) # kickstart the chunked eval

    def __dir__(self):
        return dir(type(self))

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(f"Attribute {attr} not found")
        return self._get_operator(getattr)(self, attr)

    def __setattr__(self, attr, val):
        if attr in self.__slots__:
            object.__setattr__(self, attr, val)
        else:
            raise TypeError("setattr on Delayed objects is not allowed")

    def __setitem__(self, index, val):
        #print("memorize op", operator.setitem, [index,val])
        assert not self._eval_started, "cannot add inplace operation __setitem__ after evaluation has started"
        self._post_ops.append((operator.setitem,[index,val],{})) # setitem is an inplace op
        if len(self._post_ops) >= MAX_OPS:
            self._partition_ops()

    def __iter__(self):
        if self._length is None:
            raise TypeError("Delayed objects of unspecified length are not iterable")
        for i in range(self._length):
            yield self[i]

    def __len__(self):
        if self._length is None:
            raise TypeError("Delayed objects of unspecified length have no len()")
        return self._length

    def __bool__(self):
        raise TypeError("Truth of Delayed objects is not supported")
    __nonzero__ = __bool__

    def __get__(self, instance, cls):
        if instance is None:
            return self
        return types.MethodType(self, instance)

    def __array_function__(self, func, _types, args, kwargs): # NumPy function support
        return self._get_operator(_deself(func))(self, *args, **kwargs)
    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs): # NumPy ufunc support
        # Simply setting the __array_ufunc__ method to None does not support inplace op (e.g. +=)
        return self._get_operator(_deself(getattr(ufunc, method)))(self, *inputs, **kwargs)

    @classmethod
    def _get_operator(cls, op):
        """Returns the memorized version of op
        """
        def mem_op(self, *other, **kwargs): # record the op in the instance returned
            #print("memorize op", op, other)
            return cls(self._future, [*self._post_ops, (op,list(other),kwargs)], self._length, self._copy)
        return mem_op

def _deself(op):
    """For NumPy function / ufunc, self is amid the args, and the first self is redundant"""
    def _inner(_self, *args, **kwargs):
        return op(*args, **kwargs)
    return _inner

Delayed.__call__ = Delayed._get_operator(lambda fn, *args, **kwargs: fn(*args, **kwargs))

def _right(op):
    """Wrapper to create 'right' version of operator given left version"""
    def _inner(self, other):
        return op(other, self)
    return _inner

def _bind_operator(cls, op):
    """Bind operator to class"""
    name = op.__name__
    if name.endswith("_"):
        # for and_ and or_
        name = name[:-1]
    elif name == "inv":
        name = "invert"
    meth = f"__{name}__"
    setattr(cls, meth, cls._get_operator(op))
    if name not in (
        'add', 'and', 'divmod', 'floordiv', 'lshift', 'matmul', 'mod',
        'mul', 'or', 'pow', 'rshift', 'sub', 'truediv', 'xor',
    ):
        return
    rmeth = f"__r{name}__"
    setattr(cls, rmeth, cls._get_operator(_right(op)))
for op in (
    operator.abs,
    operator.neg,
    operator.pos,
    operator.invert,
    operator.add,
    operator.sub,
    operator.mul,
    operator.floordiv,
    operator.truediv,
    operator.mod,
    operator.pow,
    operator.and_,
    operator.or_,
    operator.xor,
    operator.lshift,
    operator.rshift,
    operator.eq,
    operator.ge,
    operator.gt,
    operator.ne,
    operator.le,
    operator.lt,
    operator.getitem,
    operator.matmul,
):
    _bind_operator(Delayed, op)


async def relay(inq):
    async with inq:
        async for i, rslt in inq:
            rch[i].set(rslt)
            del rch[i] # one job, one future
async def boot(subtasks, args, kwargs):
    global exer, _gn, rch
    from .head import GrainExecutor
    from .remote_exer import RemoteExecutor
    from .config import load_conf, load_conf_sworker
    from .delayed import relay # no global dependency
    from .util import open_ordered_nursery
    from collections.abc import Iterable
    if (local := kwargs.pop('local', None)) is not None:
        kwargs['rpw'] = local
    config_file = kwargs.pop('config_file', None)
    config = load_conf(config_file, 'head')
    kwargs['sworker_config'] = load_conf_sworker(config_file) if config_file is not False else []
    Exer = RemoteExecutor
    if local or not config.gnaw.enabled:
        Exer = GrainExecutor
    async with trio.open_nursery() as _n, \
               Exer(_n=_n, config=config, *args, **kwargs) as exer:
        rch = {}
        _n.start_soon(relay, exer.resultq)
        GVAR.instance = "N/A"
        GVAR.res = ZERO
        async with open_ordered_nursery() as _gn:
            if isinstance(subtasks, Iterable):
                for st in subtasks:
                    _gn.start_soon(st)
            else:
                await subtasks()

def run(subtasks, *args, **kwargs):
    """Delayed's main entry point. Start your "root" async function(s) here.
    Except for the first two args, all the other args are optional and are passed
    to :class:`grain.remote_exer.RemoteExecutor` (or to :class:`grain.head.GrainExecutor`
    if ``local`` is set or Gnaw is disabled in the config).
    Common options are listed below, for more options (usually for internal debug),
    see the executors.

    Args:
      subtasks: Root async function(s) that spawns all the other calculations.
        This could be an async function or an iterable of async functions. If
        an iterable is passed, all functions are run concurrently.
      local (Optional[~grain.resource.Resource]): Resource for local worker.
        Default to None (Gnaw executor has no local worker). If set, the built-in
        :class:`grain.head.GrainExecutor` will be used.
      config_file (str | Literal[False] | None): Grain's config file name. If
        not set or None, Grain will use the name provided by envar ``GRAIN_CONFIG``,
        and finally fallback to name ``grain.toml``. If set to False, Grain will
        use the default profile (see ``config.py``).
      name (str): For Gnaw executor only. Name to be recognized in the Gnaw's log
      prioritized (bool): Default to False. For Gnaw executor only. If true,
        submit tasks to the prioritized queue.
    """
    trio.run(boot, subtasks, args, kwargs)
