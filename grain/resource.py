class Resource(object):
    """Return true if it is possible to alloc(res)
    """
    def _request(self, res):
        pass
    """Return allocated resources. Allocated resources
    should also be able to be used as request resources (i.e.
    `B.request(A.alloc(some_res))`), but vice versa does not
    necessary need to be true.
    """
    def _alloc(self, res):
        pass
    def _dealloc(self, res):
        pass
    """__repr__, for concatenating with other resources
    """
    def _repr(self):
        pass

    def __init__(self, init=True):
        self.__resm = { self.__class__.__name__: self } if init else {}
    def __repr__(self):
        if not self.__resm: return "Ø"
        return ' & '.join(map(lambda x:x._repr(), self.__resm.values()))
    def __and__(self, other):
        if any(k in self.__resm for k in other.__resm.keys()):
            raise ValueError("Combining resources of the same type is not supported")
        r = Resource(init=False)
        r.__resm = { **self.__resm, **other.__resm }
        return r
    def __getattr__(self, attr):
        if attr == "__setstate__": # pickle hook
            raise AttributeError
        for v in self.__resm.values():
            if attr in v.__dict__: # static lookup only
                return v.__dict__[attr]
        raise AttributeError(f"Resource object {self} has no attribute {attr}")
    def __ge__(self, other): # other is affordable
        return self.request(other)
    def __gt__(self, other):
        return not other.request(self)
    def __le__(self, other):
        return other.request(self)
    def __lt__(self, other):
        return not self.request(other)

    def request(self, res):
        for k,v in res.__resm.items():
            if (k not in self.__resm) or \
               (not self.__resm[k]._request(v)):
                return False
        return True
    def alloc(self, res):
        if any(k not in self.__resm for k in res.__resm.keys()):
            raise ValueError(f"Cannot alloc: resource {self} does not have the same shape as {res}")
        r = Resource(init=False)
        try:
            for k,v in res.__resm.items():
                r &= self.__resm[k]._alloc(v)
        except: # rewind side-effects
            self.dealloc(r)
            raise
        return r
    def dealloc(self, res):
        if any(k not in self.__resm for k in res.__resm.keys()):
            raise ValueError(f"Cannot dealloc: resource {self} does not have the same shape as {res}")
        for k,v in res.__resm.items():
            self.__resm[k]._dealloc(v)


ZERO = Resource(init=False)
        

class Cores(Resource): # CPU cores

    def __init__(self, N):
        super().__init__()
        if type(N) is int:
            self.c = set(range(N))
            self.N = N
        else: # assume iterable
            self.c = set(N)
            self.N = len(N)
    def _repr(self):
        return f"CPU_Cores([{','.join(map(str,sorted(self.c)))}])"

    # For request/alloc we only care about the count but not identities
    def _request(self, res):
        return len(self.c) >= res.N

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} cannot allocate {res.N} core(s)")
        a = list(self.c)[:res.N]
        self.c -= set(a)
        return Cores(a)

    def _dealloc(self, res):
        self.c |= res.c


class Memory(Resource): # vmem

    def __init__(self, M):
        super().__init__()
        self.m = M
        self.M = M
    def _repr(self):
        return f"Memory({self.m}GB)"

    def _request(self, res):
        return self.m >= res.m

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} cannot allocate {res}")
        res = Memory(res.m)
        self.m -= res.m
        return res

    def _dealloc(self, res):
        self.m += res.m


def Node(N, M):
    return Cores(N) & Memory(M)


import time
class WTime(Resource): # walltime, not restorable

    def __init__(self, T, countdown=False): # countdown ? allocer : requester
        super().__init__()
        self.deadline = time.time() + T if countdown else 0
        self.T = T
    def _repr(self):
        t = int(self.deadline - time.time()) if self.deadline else self.T
        return f"Walltime({t//3600:02}:{t%3600//60:02}:{t%60:02})"

    def _request(self, res):
        return self.deadline - time.time() >= res.T

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} cannot allocate {res}")
        return res

    def _dealloc(self, res):
        pass


def res2link0(res):
    s = ""
    if getattr(res, 'c', set()): s += f"%CPU={','.join(map(str,sorted(res.c)))}\n"
    if getattr(res, 'm', 0):     s += f"%Mem={res.m}GB\n"
    return s
