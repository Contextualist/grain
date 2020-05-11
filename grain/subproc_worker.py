import dill as pickle
import psutil
from trio import TooSlowError

import os
import signal
import argparse

def exerf(GVAR, func):
    globals()['GVAR'] = GVAR # for func's convenience
    timeout = getattr(GVAR.res, 'T', 0)
    if timeout:
        signal.signal(signal.SIGALRM, raise_timeout)
        signal.alarm(timeout)
    core = getattr(GVAR.res, 'c', [])
    try:
        if len(core) == 0: # NOTE: This Python interpreter proc by default takes 1 proc and ~40mb vmem.
            raise TypeError(f"Subprocess job resource expects at least core, get {GVAR.res} instead")
        psutil.Process().cpu_affinity(core)
        return True, func()
    except BaseException as e:
        if type(e) is KeyboardInterrupt:
            raise
        return False, e
    finally:
        if timeout:
            signal.signal(signal.SIGALRM, signal.SIG_IGN)

def raise_timeout(signum, frame):
    raise TooSlowError()


if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="Subprocess worker that execute sync functions")
    argp.add_argument('--fd-read', type=int)
    argp.add_argument('--fd-write', type=int)
    A = argp.parse_args()

    with os.fdopen(A.fd_read, "rb", closefd=True) as from_parent, \
         os.fdopen(A.fd_write, "wb", closefd=True) as to_parent:
        while True:
            msg = pickle.load(from_parent)
            if msg is None: # FIN
                break
            r = exerf(*msg)
            pickle.dump(r, to_parent)
            to_parent.flush()
