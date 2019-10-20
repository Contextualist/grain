import contextvars

grain_resource = contextvars.ContextVar("GRAIN_RESOURCE")
grain_instance = contextvars.ContextVar("GRAIN_INSTANCE")

class GrainVar(object):

    @property
    def res(self):
        return grain_resource.get()
    @res.setter
    def res(self, v):
        grain_resource.set(v)

    @property
    def instance(self):
        return grain_instance.get()
    @instance.setter
    def instance(self, v):
        grain_instance.set(v)

GVAR = GrainVar()
