import click
import toml
import trio

from grain.pair import SocketChannel, notify

from datetime import datetime
import subprocess
import tempfile
from time import sleep
import functools

DEFAULT_CONF = {
    "worker": {
        "name": "w{{HHMMSS}}",
        "log_filename": "w{{HHMMSS}}.log",
        "script": {
            "shebang": "#!/bin/bash",
            "queue": "''",
            "walltime": "12:00:00",
            "extra_args": [],
        }
    }
}

VAR = { # replace any occurance of `{{key}}` with `value()`. Evaluate at each submission
    "HHMMSS": (lambda: datetime.now().strftime('%H%M%S')),
}

MAIN = """echo "worker {worker.name}'s node is $(hostname)"

{worker.script.setup}

date
RES='Node(N={worker.script.PPN},M={worker.script.rMPN})&WTime("{worker.script.rwalltime}",countdown=True)'
python -m grain.worker --head {head.addr} --res "$RES"
date

{worker.script.cleanup}
"""

SLURM_TEMP = """{worker.script.shebang}
#SBATCH -J {worker.name}
#SBATCH -p {worker.script.queue}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node={worker.script.PPN}
#SBATCH --mem={worker.script.MPN}G
#SBATCH --time={worker.script.walltime}
#SBATCH -o {worker.log_dir}/{worker.log_filename}
#SBATCH --export=ALL
{worker.script.extra_args_str}

{{MAIN}}
"""

# XXX: If this causes excessive use of vmem, use `PBSW_TEMP`
PBS_TEMP = """{worker.script.shebang}
#PBS -N {worker.name}
#PBS -q {worker.script.queue}
#PBS -l nodes=1:ppn={worker.script.PPN},walltime={worker.script.walltime}
#PBS -l vmem={worker.script.MPN}gb
#PBS -j oe
#PBS -o {worker.log_dir}/{worker.log_filename}
{worker.script.extra_args_str}

cd $PBS_O_WORKDIR
{{MAIN}}
"""

# CAVEATE: all PBS_* variables are lost
PBSW_TEMP = """{worker.script.shebang}
#PBS -N {worker.name}
#PBS -q {worker.script.queue}
#PBS -l nodes=1:ppn={worker.script.PPN},walltime={worker.script.walltime}
#PBS -l vmem={worker.script.MPN}gb
#PBS -j oe
#PBS -o {worker.log_dir}/{worker.log_filename}
{worker.script.extra_args_str}

sshq=(ssh -q -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

read -r -d '' WRAPPED << 'EOS'
{{MAIN}}
EOS

"${{sshq[@]}}" localhost "cd $PBS_O_WORKDIR
$WRAPPED"
"""

MGR_SYS = {
    "slurm":    ("sbatch", "#SBATCH", SLURM_TEMP),
    "pbs":      ("qsub",   "#PBS",    PBS_TEMP),
    "pbs_wrap": ("qsub",   "#PBS",    PBSW_TEMP),
}

def eval_var(sc):
    for v, fn in VAR.items():
        sc = sc.replace("{{"+v+"}}", fn())
    return sc

def norm_wtime(wtime):
    wtime = wtime.replace('-', ':')
    *d, h, m, s = wtime.split(':')
    if len(d) > 1: raise ValueError(f"{wtime!r} is not a valid walltime")
    t = int(h)*60 + int(m)
    if len(d) == 1:
        t += int(d[0])*24*60
    tw = t - 3 # 3min for worker to quit, be polite
    return f"{t//60:02}:{t%60:02}:{s}", f"{tw//60:02}:{tw%60:02}:{s}"

def eval_defer(setup_cleanup):
    setup = setup_cleanup.split('\n')
    cleanup = []
    i = 0
    while i < len(setup):
        if not setup[i].startswith("defer "):
            i += 1
            continue
        cleanup.append(setup.pop(i)[6:])
    cleanup.reverse()
    return '\n'.join(setup), '\n'.join(cleanup)

def submit(scmd, sc, *args):
    with tempfile.NamedTemporaryFile(mode='w', dir=".", buffering=1) as f:
        f.write(sc)
        subprocess.run([scmd, f.name, *args])


class odict(dict):
    def __init__(self, d):
        d = { k:self.__attrify(k,v) for k, v in d.items() }
        dict.__init__(self, d)
    def __attrify(self, k, v):
        if isinstance(v, (list, tuple)):
           rv = [odict(x) if isinstance(x, dict) else x for x in v]
        else:
           rv = odict(v) if isinstance(v, dict) else v
        setattr(self, k, rv)
        return rv

def setdefault(d, dflt): # NOTE: not dealing with list & tuple
    for k,v in dflt.items():
        if k not in d:
            d[k] = v
            continue
        if isinstance(v, dict):
            setdefault(d[k],v)


click.option = functools.partial(click.option, show_default=True)

def global_options(fn):
    @click.option('-c', '--config', default="grain.toml", envvar='GRAIN_CONFIG', help="Grain config file. Can be set by envar `GRAIN_CONFIG`")
    @functools.wraps(fn)
    def _wrapped(config, *args, **kwargs):
        conf = toml.load(config)
        setdefault(conf, DEFAULT_CONF)
        conf = odict(conf)
        return fn(conf=conf, *args, **kwargs)
    return _wrapped

@click.group(help="CLI tool to manage Grain workers")
def main():
    pass

@main.command(help="Submit worker jobs (extra opts are forwarded to the submission command)",
              context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@global_options
@click.option('-n', type=int, default=1, help="Number of worker jobs/nodes to submit")
@click.option('--dry', is_flag=True, help="Dry run. Print out the job submission script without submitting. This ignores `-n`.")
@click.pass_context
def up(ctx, conf, n, dry):
    scriptc = conf.worker.script
    scriptc.rMPN = int(scriptc.MPN/15*14)
    scriptc.walltime, scriptc.rwalltime = norm_wtime(scriptc.walltime)
    scriptc.setup, scriptc.cleanup = eval_defer(scriptc.setup_cleanup)

    try:
        scmd, dirc, temp = MGR_SYS[conf.worker.system.lower()]
    except KeyError:
        print(f"Unknown conf.worker.system: {conf.worker.system}")
        return
    scriptc.extra_args_str = '\n'.join(f"{dirc} {l}" for l in scriptc.extra_args)
    sc = temp.replace("{{MAIN}}", MAIN).format(**conf)
    if dry:
        print(eval_var(sc))
        return
    for i in range(n):
        if i > 0: sleep(1)
        submit(scmd, eval_var(sc), *ctx.args)

@main.command(help="Overview of workers' status")
@global_options
def ls(conf):
    async def _ls(head):
        try:
            async with trio.open_nursery() as _n, \
                       SocketChannel(f"{head}:4242", dial=True, _n=_n) as c:
                await c.send(b"STA")
                print((await c.receive()).decode())
        except OSError:
            print(f"endpoint {head}:4242 is down")
    trio.run(_ls, conf.head.addr)

@main.command(help="Unregister a worker")
@global_options
@click.argument('worker_name')
def unreg(conf, worker_name):
    async def _unreg(head, name):
        try:
            await notify(f"{head}:4242", b"UNR"+name.encode(), seg=True)
        except OSError:
            print(f"endpoint {head}:4242 is down")
    trio.run(_unreg, conf.head.addr, worker_name)

if __name__=="__main__":
    main()
