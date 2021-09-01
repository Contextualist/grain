import tomli
import attr
attrs = attr.s(auto_attribs=True)
import cattr

from typing import Optional, List, Dict, Any, Literal
from os import environ as ENV
from collections import ChainMap
from io import StringIO
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

@attrs
class Script:
    cores:         int
    memory:        int
    setup_cleanup: str
    shebang:       str = "#!/bin/bash"
    queue:         str = "''"
    walltime:      str = "12:00:00"
    extra_args:    List[str] = attr.Factory(list)

@attrs
class CustomSystem:
    submit_cmd: str
    directory:  str
    template:   str

@attrs
class Config:
    system:        str
    script:        Script = attr.Factory(Script)
    contextmod:    str = ""
    custom_system: Optional[CustomSystem] = None

@attrs
class Head(Config):
    name:          str = "grain_head"
    main_log_file: str = "/dev/null"
    log_file:      str = ""
    listen:        str = "tcp://:4242"
    cmd:           str = ""

@attrs
class Worker(Config):
    name:     str = "w{{HHMMSS}}"
    log_file: str = "w{{HHMMSS}}.log"
    dial:     str = "UNSET"
    cli_dial: str = ""
    res:      Dict[str, Any] = attr.Factory(dict)
    def __attrs_post_init__(self):
        if self.dial == "UNSET":
            raise ValueError("Config `worker.dial` is not set")
        if not self.cli_dial:
            self.cli_dial = self.dial

@attrs
class GenericConfig:
    head:   Head
    worker: Worker

_loose_filler = dict(
    system="",
    head={},
    script=dict(cores=0, memory=0, setup_cleanup=""),
)

def ChainMapNested(d0, d1):
    for k in set(d0.keys()) & set(d1.keys()):
        if type(d0[k]) is dict and type(d1[k]) is dict:
            d0[k] = ChainMapNested(d0[k], d1[k])
    return ChainMap(d0, d1)

def load_conf(config=None, mode: Literal['', 'head', 'worker']=''):
    if config is False:
        logger.info("Config file is disabled, using default settings.")
        conf = _loose_filler
    else:
        config = config or ENV.get("GRAIN_CONFIG", "grain.toml")
        try:
            config_s = Path(config).read_bytes().decode() if type(config) is str else config.read()
            conf = tomli.loads(config_s)
        except FileNotFoundError:
            logger.error(f"Cannot find Grain config file {config!r}")
            exit(1)
        if type(config) is StringIO: # internal config fragment
            conf = ChainMap(conf, _loose_filler)
    if mode == 'worker':
        return cattr.structure(ChainMapNested(conf['worker'], conf), Worker)
    elif mode == 'head':
        return cattr.structure(ChainMapNested(conf['head'], conf), Head)
    return GenericConfig(
        worker=cattr.structure(ChainMapNested(conf['worker'], conf), Worker),
        head=cattr.structure(ChainMapNested(conf['head'], conf), Head),
    )
