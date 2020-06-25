import toml

from os import environ as ENV

DEFAULT_CONF = {
    "head": {
        "name": "grain_head",
        "main_log_file": "/dev/null",
        "log_file": "",
        "listen": "tcp://:4242",
        "script": {},
    },
    "worker": {
        "name": "w{{HHMMSS}}",
        "log_file": "w{{HHMMSS}}.log",
        "script": {},
        "res": {},
    },
    "script": {
        "shebang": "#!/bin/bash",
        "queue": "''",
        "walltime": "12:00:00",
        "extra_args": [],
    },
    "custom_system": {},
}

def load_conf(config=None):
    if config is False:
        print("Config file is disabled, using default settings.")
        return odict(DEFAULT_CONF)
    config = config or ENV.get("GRAIN_CONFIG", "grain.toml")
    try:
        conf = toml.load(config)
    except FileNotFoundError:
        print(f"Cannot find Grain config file {config!r}, using default settings.")
        conf = {}
    setdefault(conf, DEFAULT_CONF)
    return odict(conf)

def setdefault(d, dflt): # NOTE: not dealing with list & tuple
    for k,v in dflt.items():
        if k not in d:
            d[k] = v
            continue
        if isinstance(v, dict):
            setdefault(d[k],v)

class odict(dict):
    def __init__(self, d):
        d = { k:self.__attrify(k,v) for k, v in d.items() }
        dict.__init__(self, d)
    def __attrify(self, k, v):
        if isinstance(v, (list, tuple)):
           rv = [odict(x) if isinstance(x, dict) else x for x in v]
        else:
           rv = odict(v) if isinstance(v, dict) else v
        self.__dict__[k] = rv
        return rv
    def __setitem__(self, k, v):
        self.__dict__[k] = v
        dict.__setitem__(self, k, v)
    def __setattr__(self, k, v):
        dict.__setitem__(self, k, v)
        self.__dict__[k] = v

