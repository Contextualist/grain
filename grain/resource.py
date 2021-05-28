__all__ = ["Resource", "ZERO", "Cores", "Memory", "Node", "WTime", "Token", "Capacity",
           "ONE_INSTANCE", "Reject", "REJECT", "res2link0"]

class Resource(object):
    def _request(self, res):
        """Return true if it is possible to alloc(res)
        """
    def _alloc(self, res):
        """Return allocated resources. Allocated resources
        should also be able to be used as request resources (i.e.
        ``B.request(A.alloc(some_res))``), but vice versa does not
        necessary need to be true.
        """
    def _dealloc(self, res):
        pass
    def _repr(self):
        """``__repr__``, for concatenating with other resources
        """
    def _stat(self):
        """Return (p,q) where p and q are `int`, and p/q
        represents the percentage resource availability.
        """

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
    def __eq__(self, other):
        return self.request(other) and other.request(self)

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
    def stat(self):
        return {k:v._stat() for k,v in self.__resm.items()}
    def encode_msgp(self):
        return {k:v._encode_msgp() for k,v in self.__resm.items()}



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
        if self.N == 0: return "CPU_Cores([])"
        first, *c = sorted(self.c)
        con = [[first,first]]
        for x in c:
            if x == con[-1][1]+1: con[-1][1] = x
            else: con.append([x,x])
        clist = ','.join((str(x) if x==y else f"{x}-{y}") for x,y in con)
        return f"CPU_Cores([{clist}])"

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

    def _stat(self):
        return len(self.c), self.N

    def _encode_msgp(self):
        return dict(N=sorted(self.c))


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

    def _stat(self):
        return self.m, self.M

    def _encode_msgp(self):
        return dict(M=self.M)


def Node(N, M):
    return Cores(N) & Memory(M)


import time
class WTime(Resource): # walltime, not restorable

    def __init__(self, T, softT=None, countdown=False): # countdown ? allocer : requester
        super().__init__()
        if isinstance(T, str):
            *d, h, m, s = map(int, T.replace('-',':').split(':'))
            T = 86400*(d or [0])[-1] + 3600*h + 60*m + s
        self.deadline = time.time() + T if countdown else 0
        self.T = T
        self.softT = softT or T
    def _repr(self):
        t = max(int(self.deadline - time.time()), 0) if self.deadline else self.T
        return f"Walltime({t//3600:02}:{t%3600//60:02}:{t%60:02})"

    def _request(self, res): # loose condition
        return self.deadline - time.time() >= res.softT

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} cannot allocate {res}")
        return res

    def _dealloc(self, res):
        pass

    def _stat(self):
        return 1, 1

    def _encode_msgp(self):
        if self.deadline:
            return dict(T=int(self.deadline-time.time()), countdown=True)
        else:
            return dict(T=int(self.T), softT=int(self.softT), countdown=False)


class Token(Resource):

    def __init__(self, token):
        super().__init__()
        self.token = token
    def _repr(self):
        return f"Token({self.token})"

    def _request(self, res):
        return self.token == res.token

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} does not match {res}")
        return res

    def _dealloc(self, res):
        pass

    def _stat(self):
        return 1, 1


class Capacity(Resource):

    def __init__(self, V):
        super().__init__()
        self.V = self.v = V
    def _repr(self):
        return f"Capacity({self.v})" if self.v != -1 else "ONE"

    def _request(self, res):
        return self.v > 0

    def _alloc(self, res):
        if not self._request(res):
            raise ValueError(f"{self} has no capacity")
        self.v -= 1
        return res

    def _dealloc(self, res):
        self.v += 1

    def _stat(self):
        return self.v, self.V

ONE_INSTANCE = Capacity(-1) # for requester
# This is not ideal as ONE_INSTANCE != ONE_INSTANCE


class Reject(Resource):
    """Similar to `ZERO`, but uncondionally suppress
    all request/alloc and absorb dealloc
    """
    def __init__(self, wrap=ZERO):
        super().__init__(init=False)
        self.__self = wrap
    def __repr__(self):
        return "N/A"
    def __and__(self, other):
        return self

    def request(self, res):
        return False
    def alloc(self, res):
        raise ValueError("No resource is or will be available")
    def dealloc(self, res):
        self.__self.dealloc(res) # Blackhole
    def stat(self):
        return self.__self.stat()

    def eject(self):
        return self.__self

REJECT = Reject()


def res2link0(res):
    s = ""
    if getattr(res, 'c', set()): s += f"%CPU={','.join(map(str,sorted(res.c)))}\n"
    if getattr(res, 'm', 0):     s += f"%Mem={res.m}GB\n"
    return s
