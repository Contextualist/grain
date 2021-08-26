from ._version import __version__
from .contextvar import GVAR

import logging
logging.basicConfig(format='[%(asctime)s] %(name)s:%(levelname)s: %(message)s')
logging.getLogger('grain').setLevel(logging.INFO)
