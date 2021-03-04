from grain.subproc import subprocess_pool_scope
from rear import rear_fs

from contextlib import asynccontextmanager

@asynccontextmanager
async def grain_context():
    async with subprocess_pool_scope(), \
               rear_fs("/path/to/rear/base"):
        yield
