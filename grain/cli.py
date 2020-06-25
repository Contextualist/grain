import click
import trio
import toml

from .pair import SocketChannel, notify
from .config import load_conf, setdefault

from datetime import datetime
import subprocess
import tempfile
from time import sleep
import functools
from contextlib import contextmanager
import sys
import os
import json

VAR = { # replace any occurance of `{{key}}` with `value()`. Evaluate at each submission
    "HHMMSS": (lambda: datetime.now().strftime('%H%M%S')),
}

WORKER_MAIN = """echo "worker {name}'s node is $(hostname)"

{script.setup}

date
python -m grain.worker --url {worker.dial} --res {script.res_str}
date

{script.cleanup}
"""
HEAD_MAIN = """echo "head's node is $(hostname)"

{script.setup}

{head.cmd}

{script.cleanup}
"""

SLURM_TEMP = """{script.shebang}
#SBATCH -J {name}
#SBATCH -p {script.queue}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node={script.cores}
#SBATCH --mem={script.memory}G
#SBATCH --time={script.walltime}
#SBATCH -o {log_file}
{script.extra_args_str}

{{MAIN}}
"""

# XXX: If this causes excessive use of vmem, use `PBSW_TEMP`
PBS_TEMP = """{script.shebang}
#PBS -N {name}
#PBS -q {script.queue}
#PBS -l nodes=1:ppn={script.cores},walltime={script.walltime}
#PBS -l vmem={script.memory}gb
#PBS -j oe
#PBS -o {log_file}
{script.extra_args_str}

cd $PBS_O_WORKDIR
{{MAIN}}
"""

# CAVEATE: all PBS_* variables are lost
PBSW_TEMP = """{script.shebang}
#PBS -N {name}
#PBS -q {script.queue}
#PBS -l nodes=1:ppn={script.cores},walltime={script.walltime}
#PBS -l vmem={script.memory}gb
#PBS -j oe
#PBS -o {log_file}
{script.extra_args_str}

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

QUERY_TIMEOUT = 5

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

def submit(scmd, sc, *args, env=None):
    with tempfile.NamedTemporaryFile(mode='w', dir=".", buffering=1) as f:
        f.write(sc)
        subprocess.run([scmd, f.name, *args], env={**os.environ, **env} if env else None)


click.option = functools.partial(click.option, show_default=True)

def global_options(fn):
    @click.option('-c', '--config', default="grain.toml", envvar='GRAIN_CONFIG', help="Grain config file. Can be set by envar `GRAIN_CONFIG`")
    @functools.wraps(fn)
    def _wrapped(config, *args, **kwargs):
        return fn(conf=load_conf(config), *args, **kwargs)
    return _wrapped

def _toml_inline(**d):
    class InlineDict(dict, toml.decoder.InlineTableDict):
        pass
    for k,v in d.items():
        d[k] = InlineDict(v)
    return toml.dumps(d, encoder=toml.TomlPreserveInlineDictEncoder())
def gen_script(conf):
    scriptc = conf.script
    if hasattr(scriptc, "PPN"):
        scriptc.cores, scriptc.memory = scriptc.PPN, scriptc.MPN
    rmem = int(scriptc.memory/15*14)
    scriptc.walltime, rwalltime = norm_wtime(scriptc.walltime)
    # json.dumps is for linebreak and quote escape
    scriptc.res_str = json.dumps(_toml_inline( # only worker uses this
        Node=dict(N=scriptc.cores, M=rmem),
        WTime=dict(T=rwalltime, countdown=True),
        **conf.worker.res,
    ))
    scriptc.setup, scriptc.cleanup = eval_defer(scriptc.setup_cleanup)
    if conf.custom_system:
        scmd, dirc, temp = conf.custom_system.submit_cmd, conf.custom_system.directory, conf.custom_system.template
    else:
        try:
            scmd, dirc, temp = MGR_SYS[conf.system.lower()]
        except KeyError:
            print(f"Unknown conf.system: {conf.system}")
            sys.exit(1)
    scriptc.extra_args_str = '\n'.join(f"{dirc} {l}" for l in scriptc.extra_args)
    return scmd, temp

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
    setdefault(conf.worker.script, conf.script)
    conf.script = conf.worker.script
    scmd, temp = gen_script(conf)
    sc = temp.replace("{{MAIN}}", WORKER_MAIN).format(**conf, name=conf.worker.name, log_file=conf.worker.log_file)
    if dry:
        print(eval_var(sc))
        return
    for i in range(n):
        if i > 0: sleep(1)
        submit(scmd, eval_var(sc), *ctx.args)

@main.command(help="Start the head process")
@global_options
@click.option('--local', is_flag=True, help="Run locally instead of submitting a job")
@click.option('--dry', is_flag=True, help="Dry run. Print out the job submission script without submitting")
def start(conf, local, dry):
    setdefault(conf.head.script, conf.script)
    conf.script = conf.head.script
    scmd, temp = gen_script(conf)
    sc = temp.replace("{{MAIN}}", HEAD_MAIN).format(**conf, name=conf.head.name, log_file=conf.head.main_log_file)
    if dry:
        print(eval_var(sc))
        return
    if local: # FIXME: relay SIGINT
        submit(conf.script.shebang[2:], eval_var(sc), env=dict(PBS_O_WORKDIR=os.getcwd()))
    else:
        submit(scmd, eval_var(sc))

@main.command(help="Overview of workers' status")
@global_options
def ls(conf):
    async def _ls(head):
        with _handle_connection_error(head):
            async with trio.open_nursery() as _n, \
                       SocketChannel(f"{head}", dial=True, _n=_n) as c:
                await c.send(b"STA")
                print((await c.receive()).decode())
    trio.run(_ls, getattr(conf.worker, "cli_dial", conf.worker.dial))

@main.command(help="Quit a worker")
@global_options
@click.option('-f', '--force', is_flag=True, help="Kill the worker even if it still have running jobs")
@click.argument('worker_name')
def quit(conf, force, worker_name):
    async def _unreg(head, name):
        with _handle_connection_error(head):
            await notify(f"{head}", (b"UNR" if force else b"TRM")+name.encode(), seg=True)
    trio.run(_unreg, getattr(conf.worker, "cli_dial", conf.worker.dial), worker_name)

@contextmanager
def _handle_connection_error(url):
    try:
        with trio.fail_after(QUERY_TIMEOUT):
            yield
    except (OSError, trio.TooSlowError):
        print(f"unable to contact head through {url}")

if __name__=="__main__":
    main()
