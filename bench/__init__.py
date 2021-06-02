
N = 300 # tasks per batch

def asyncify(benchmark):
    import trio
    from functools import partial

    async def _wrapper(func, *args, **kwargs):
        await trio.to_thread.run_sync(
            benchmark,
            partial(trio.from_thread.run, partial(func, *args, **kwargs))
        )

    return _wrapper
