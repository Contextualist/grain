"""Dask-like Delayed object, resource-centric and async/await-native
"""
from .resource import ZERO
from .contextvar import GVAR

import trio
import operator
from functools import partial
from inspect import iscoroutinefunction
from copy import copy
from collections.abc import Iterable


async def each(*dos):
    """A convinient helper function to await on a list
    of delayed objects.

    Args:
      \*dos (\*Delayed or [Iterable[Delayed]]): list of
        delayed objects

    Returns:
      list of corresponding results
    """
    if len(dos) == 1 and isinstance(dos[0], Iterable):
        dos = dos[0]
    return [await do for do in dos]


def delayed(fn=None, nout=None, copy_on_setitem=True):
    """Decorator to wraps an async function into a delayed
    function.
    """
    if fn is None:
        return partial(delayed, nout=nout, copy_on_setitem=copy_on_setitem)
    if not iscoroutinefunction(getattr(fn, "func", fn)):
        raise TypeError("delayed only wraps async functions")
    return DelayedFn(fn, nout, copy_on_setitem)

class DelayedFn:
    """A DelayedFn submit the function and returns a
    Delayed object when called. Resources could be bound
    to the function with ``@`` operator.
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
        sc, rc = trio.open_memory_channel(1)
        if self.res is not ZERO:
            tid = exer.submit(self.res, self.fn, *args, **kwargs)
            rch[tid] = sc
        else: # Currently non-leaf tasks are not guarded by the exer. We do not retry on exception.
            # We use an ordered nursery for first-come-first-serve guarentee
            _gn.start_now(partial(_run_and_send_result, sc, self.fn, *args, **kwargs))
        self.res = ZERO
        return Delayed(Future(rc), length=self.nout, copy_on_setitem=self.copy)

async def _run_and_send_result(chan, fn, *args, **kwargs):
    r = await fn(*args, **kwargs)
    chan.send_nowait(r)

PENDING = object()
class Future:
    __slots__ = ("v", "rchan")
    def __init__(self, rchan_or_v):
        if isinstance(rchan_or_v, trio.abc.ReceiveChannel):
            self.v = PENDING
            self.rchan = rchan_or_v
        else:
            self.v = rchan_or_v
    async def get(self):
        if self.v is PENDING:
            self.v = await self.rchan.receive()
        return self.v


class Delayed:
    """Represents a value to be computed by Grain.
    This is mostly a copy of the implementaton in Dask,
    but there are several main differences from Dask:

        1. Grain's Delayed assumes all ops are cheap
           and perform them locally.
        2. As all delayed objects are reduced locally,
           and Grain worker does not cache results, it is
           not allowed to pass delayed objects to a delayed
           function; we want to be explicit on the intention
           of dependent/serial jobs. e.g.::

               r1 = await dfn1()
               r2 = await dfn2(r1)

        3. Calling a delayed function submit the calculation
           immediately.
        4. A Delayed object is mutable, `setitem` and
           `setattr` are allowed.
    """
    __slots__ = ("_future", "_post_ops", "_length", "_copy")
    def __init__(self, future, post_ops=None, length=None, copy_on_setitem=True):
        self._future = future
        self._length = length
        self._copy = copy_on_setitem
        self._post_ops = post_ops or []
    def __getstate__(self):
        return tuple(getattr(self, i) for i in self.__slots__)
    def __setstate__(self, state):
        for k, v in zip(self.__slots__, state):
            setattr(self, k, v)

    async def result(self):
        r = await self._future.get()
        for op, other in self._post_ops:
            #print("post_op", op, "on", other)
            for i, o in enumerate(other):
                if not isinstance(o, Delayed): continue
                #print("eval", o)
                other[i] = await o.result() # eval o if not done
            if op is not operator.setitem: # NOTE: exclude the inplace op
                r = op(r, *other)
            else:
                if self._copy:
                    r = copy(r) # shallow copy is ok because setitem does not change the value itself
                op(r, *other)
        if self._post_ops:
            self._future = Future(r)
            self._post_ops.clear()
        return r
    def __await__(self):
        """Await on the Delayed object returns its result"""
        return self.result().__await__()

    def __dir__(self):
        return dir(type(self))

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(f"Attribute {attr} not found")
        return Delayed(self._future, [*self._post_ops, (getattr,[attr])], self._length, self._copy)

    def __setattr__(self, attr, val):
        if attr in self.__slots__:
            object.__setattr__(self, attr, val)
        else:
            raise TypeError("setattr on Delayed objects is not allowed")

    def __setitem__(self, index, val):
        #print("memorize op", operator.setitem, [index,val])
        self._post_ops.append((operator.setitem,[index,val])) # setitem is an inplace op

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

    @classmethod
    def _get_operator(cls, op, inv=False):
        """Returns the memorized version of op
        """
        if inv:
            op = right(op)
        def mem_op(self, *other): # record the op in the instance returned
            #print("memorize op", op, other)
            return cls(self._future, [*self._post_ops, (op,list(other))], self._length, self._copy)
        return mem_op

def right(op):
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
    meth = "__{0}__".format(name)
    setattr(cls, meth, cls._get_operator(op))
    if name not in (
        'add', 'and', 'divmod', 'floordiv', 'lshift', 'matmul', 'mod',
        'mul', 'or', 'pow', 'rshift', 'sub', 'truediv', 'xor',
    ):
        return
    rmeth = "__r{0}__".format(name)
    setattr(cls, rmeth, cls._get_operator(op, inv=True))
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
            try:
                rch[i].send_nowait(rslt)
            except trio.BrokenResourceError:
                # This usually happens when one of the main subtasks throws an error,
                # cancelling receive channel's task.
                # Suppress this so that the real error can surface.
                break
            del rch[i] # one job, one chan
async def boot(subtasks, args, kwargs):
    global exer, _gn, rch
    from .head import GrainExecutor
    from .delayed import relay # no global dependency
    from .util import open_ordered_nursery
    from collections.abc import Iterable
    async with trio.open_nursery() as _n, \
               GrainExecutor(_n=_n, *args, **kwargs) as exer:
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
    trio.run(boot, subtasks, args, kwargs)
