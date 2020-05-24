from contextvars import ContextVar

_GVAR = dict(
    res      = ContextVar("GRAIN_RESOURCE"),
    instance = ContextVar("GRAIN_INSTANCE"),
)

_None = object()

class GrainVar:

    def __getattr__(self, k):
        return _GVAR.get(k).get()
    def __setattr__(self, k, v):
        _GVAR.get(k).set(v)

    def __getstate__(self):
        return { k:v.get() for k,v in _GVAR.items() if v.get(_None) is not _None }
    def __setstate__(self, state):
        for k,v in state.items(): setattr(self, k, v)

GVAR = GrainVar()
