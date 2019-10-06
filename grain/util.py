from contextlib import ContextDecorator
from timeit import default_timer as timer
from functools import wraps

def timeblock(text="this block", enter=False):
    class TimeblockCtx(ContextDecorator):
        def __enter__(self):
            if enter:
                print(f"Enter {text}")
            self.st = timer()
            return self
        def __exit__(self, *exc):
            print(f"Time elapsed for {text}: {timer()-self.st}")
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
