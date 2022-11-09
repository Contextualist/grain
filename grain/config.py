try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from attrs import define, Factory
import cattr

from typing import Optional, List, Dict, Any, Literal
from os import environ as ENV
from collections import ChainMap
from io import StringIO
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

@define(slots=False)
class Script:
    cores:         int = 0
    memory:        int = 0
    setup_cleanup: str = ""
    shebang:       str = "#!/bin/bash"
    queue:         str = "''"
    walltime:      str = ""
    extra_args:    List[str] = Factory(list)

@define
class CustomSystem:
    submit_cmd: str
    directory:  str
    template:   str

@define
class Config:
    system:        str = ""
    script:        Script = Factory(Script)
    contextmod:    str = ""
    custom_system: Optional[CustomSystem] = None
    address:       str = ""
    def __attrs_post_init__(self):
        if not self.address:
            (_local_share := Path.home()/".local/share").mkdir(mode=0o755, parents=True, exist_ok=True)
            self.address = f"edge://{_local_share}/edge-file-default"

@define
class Gnaw:
    enabled:    bool = True
    log_file:   str = ""
    max_conn:   int = 8
    idle_quit:  str = "30m"
    swarm:      int = 0
    extra_args: List[str] = Factory(list)

@define
class Head(Config):
    name:          str = "grain_head"
    main_log_file: str = "/dev/null"
    log_file:      str = ""
    listen:        str = ""
    cmd:           str = ""
    gnaw:          Gnaw = Factory(Gnaw)
    def __attrs_post_init__(self):
        Config.__attrs_post_init__(self)
        if not self.listen:
            self.listen = self.address

@define
class Worker(Config):
    specialized_type: str = ""
    name:             str = "w{{HHMMSS}}"
    log_file:         str = "w{{HHMMSS}}.log"
    dial:             str = ""
    cli_dial:         str = ""
    res:              Dict[str, Any] = Factory(dict)
    def __attrs_post_init__(self):
        Config.__attrs_post_init__(self)
        if not self.dial:
            self.dial = self.address
        if not self.cli_dial:
            self.cli_dial = self.dial

@define
class GenericConfig:
    head:   Head
    worker: Worker

_loose_filler = dict(
    head=dict(gnaw=dict(enabled=False)), # disable gnaw for test purpose
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
            conf = tomllib.loads(config_s)
        except FileNotFoundError:
            logger.error(f"Cannot find Grain config file {config!r}")
            exit(1)
        if type(config) is StringIO: # internal config fragment
            conf = ChainMap(conf, _loose_filler)
    conf.setdefault('head', {})
    conf.setdefault('worker', {})
    if mode == 'worker':
        return cattr.structure(ChainMapNested(conf['worker'], conf), Worker)
    elif mode == 'head':
        return cattr.structure(ChainMapNested(conf['head'], conf), Head)
    return GenericConfig(
        worker=cattr.structure(ChainMapNested(conf['worker'], conf), Worker),
        head=cattr.structure(ChainMapNested(conf['head'], conf), Head),
    )

def load_conf_sworker(config=None):
    conf = load_conf(config, 'worker')
    if conf.specialized_type:
        return [conf]
    return []
