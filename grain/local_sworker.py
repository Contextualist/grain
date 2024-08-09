"""
A dumb backendless specialized worker implementation for testing purpose.
By setting `worker.specialized_type = "grain.local_sworker"`,
tasklets are executed locally, subjected to resource constraint like `worker.res`.
Everything works similarly as if running `grain.delayed.run(local=...)`,
except that the Gnaw executor is being used.
"""
from contextlib import asynccontextmanager


GRAIN_SWORKER_CONFIG = dict(
    BACKENDLESS=True,
)


@asynccontextmanager
async def grain_context():
    yield None


@asynccontextmanager
async def grain_run_sworker():
    yield dict(name="local")

