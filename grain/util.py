from contextlib import ContextDecorator
from timeit import default_timer as timer
from functools import wraps
import types

def timeblock(text="this block", enter=False):
    class TimeblockCtx(ContextDecorator):
        def __enter__(self):
            if enter:
                print(f"Enter {text}")
            self.st = timer()
            return self
        def __exit__(self, *exc):
            print(f"Time elapsed for {text}{' (incomplete)' if any(exc) else ''}: {timer()-self.st}")
            return False
    return TimeblockCtx()

def aretry(attempts=3, dropafter=180, errtype=Exception, silent=False, kwargs1=None):
    if attempts <= 0:
        raise ValueError("Bad retry attempts")
    def __wrapper(fn):
        @wraps(fn)
        async def __aretry(*args, **kwargs):
            st = timer()
            err = None
            for _ in range(attempts):
                try:
                    return await fn(*args, **kwargs)
                except errtype as e:
                    if not silent: print(f"{fn.__name__!r} raises {e.__class__.__name__}: {e}, retry...")
                    err = e
                if timer()-st > dropafter: break
                if kwargs1: kwargs.update(kwargs1)
            if err: raise RuntimeError("No more retries") from err
        return __aretry
    return __wrapper


import trio
from trio.hazmat import ParkingLot, checkpoint, enable_ki_protection
from outcome import Value

class WaitGroup(object):

    def __init__(self):
        self._counter = 0
        self._lot = ParkingLot()

    def add(self):
        self._counter += 1

    @enable_ki_protection
    def done(self, *exc):
        self._counter -= 1
        if self._counter == 0:
            self._lot.unpark_all()
        return False

    __enter__ = add
    __exit__ = done

    async def wait(self):
        if self._counter == 0:
            await checkpoint()
        else:
            await self._lot.park()


@enable_ki_protection
def cutin_nowait(self, value):
    if self._closed:
        raise trio.ClosedResourceError
    if self._state.open_receive_channels == 0:
        raise trio.BrokenResourceError
    if self._state.receive_tasks:
        assert not self._state.data
        task, _ = self._state.receive_tasks.popitem(last=False)
        task.custom_sleep_data._tasks.remove(task)
        trio.hazmat.reschedule(task, Value(value))
    elif len(self._state.data) < self._state.max_buffer_size:
        self._state.data.appendleft(value)
    else:
        raise trio.WouldBlock

def make_prependable(mschan):
    mschan.cutin_nowait = types.MethodType(cutin_nowait, mschan)
    return mschan


class nullacontext(object):
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

def optional_cm(cm, cond_arg):
    if cond_arg:
        return cm(cond_arg)
    return nullacontext()

def set_numpy_oneline_repr():
    """Change the default Numpy array __repr__ to a
    compact one. This is useful for keeping the log
    clean when the job functions involve large Numpy
    arrays as args.
    """
    import numpy as np
    EDGEITEMS = 3
    def oneline_repr(a):
        N = np.prod(a.shape)
        ind = np.unravel_index(range(min(EDGEITEMS, N)), a.shape)
        afew = []
        for x,val in zip(np.c_[ind], a[ind]):
            for i,y in enumerate(x[::-1]):
                if y != 0: break
            else: i+=1
            for j,y in enumerate(x[::-1]):
                if y+1 != a.shape[len(x)-j-1]: break
            else: j+=1
            afew.append(f"{'['*i}{val}{']'*j}")
        return f"array[{a.shape}]({', '.join(afew)}{'...' if N > EDGEITEMS else ''})"
    np.set_string_function(oneline_repr, repr=True)
